"""Unit tests for the defaults module — YAML block surgery and validation."""

from unittest.mock import patch

import pytest

from invoicer import defaults as defaults_mod
from invoicer.defaults import (
    _find_defaults_block,
    _render_block,
    set_default,
    unset_default,
    validate,
)


class TestValidate:
    def test_rejects_unknown_key(self):
        with pytest.raises(ValueError, match="Unknown default key"):
            validate("ssh_key", "foo")

    def test_rejects_empty_value(self):
        with pytest.raises(ValueError, match="Empty value"):
            validate("org", "")

    def test_locale_enum(self):
        for good in ["it", "en", "de"]:
            validate("locale", good)  # no raise
        with pytest.raises(ValueError, match="locale must be one of"):
            validate("locale", "fr")

    def test_org_must_exist(self):
        with patch(
            "invoicer.defaults.list_orgs",
            return_value=[{"id": "welance-srl"}, {"id": "welance-gmbh"}],
        ):
            validate("org", "welance-srl")  # no raise
            with pytest.raises(ValueError, match="not declared"):
                validate("org", "welance-nope")

    def test_org_skipped_when_no_orgs_declared(self):
        """Legacy single-org mode has no `orgs:` block — any org value passes."""
        with patch("invoicer.defaults.list_orgs", return_value=[]):
            validate("org", "anything")  # no raise


class TestFindDefaultsBlock:
    def test_finds_simple_block(self):
        lines = [
            "orgs:\n",
            "  - id: a\n",
            "\n",
            "defaults:\n",
            "  org: welance-srl\n",
            "  locale: it\n",
            "\n",
            "clients:\n",
            "  - clockify_id: x\n",
        ]
        start, end = _find_defaults_block(lines)
        assert start == 3
        # End includes the blank line 6 but stops before `clients:` at 7
        assert end == 7

    def test_missing_block(self):
        lines = ["orgs:\n", "  - id: a\n", "clients:\n"]
        assert _find_defaults_block(lines) is None

    def test_ignores_nested_defaults_key(self):
        """A `defaults:` appearing inside another block (indented) must not match."""
        lines = [
            "projects:\n",
            "  proj_abc:\n",
            "    defaults:\n",  # nested — not a top-level key
            "      foo: bar\n",
        ]
        assert _find_defaults_block(lines) is None


class TestRenderBlock:
    def test_empty_renders_to_empty_string(self):
        assert _render_block({}) == ""

    def test_fixed_key_order(self):
        """Keys render in KNOWN_KEYS order regardless of dict insertion order."""
        out = _render_block({"locale": "en", "gmail_sender": "a@b.c", "org": "x"})
        # KNOWN_KEYS is (org, locale, gmail_sender)
        lines = out.splitlines()
        assert lines[0] == "defaults:"
        assert lines[1] == "  org: x"
        assert lines[2] == "  locale: en"
        assert lines[3] == "  gmail_sender: a@b.c"

    def test_only_renders_known_keys(self):
        out = _render_block({"org": "x"})
        assert "org: x" in out
        assert "locale" not in out  # not set, not rendered


class TestWriteBlockRoundTrip:
    """Real file I/O via tmp_path — verifies text surgery preserves the rest."""

    def _write_yaml(self, tmp_path, content: str):
        path = tmp_path / "invoicer.yaml"
        path.write_text(content)
        return path

    def _patch_project_root(self, tmp_path):
        # defaults module calls get_project_root() to find invoicer.yaml
        return patch(
            "invoicer.defaults.get_project_root",
            return_value=tmp_path,
        )

    def test_insert_when_no_existing_block(self, tmp_path):
        initial = (
            "# my project config\n"
            "orgs:\n"
            "  - id: welance-srl\n"
            "    country: IT\n"
            "    login_env: QONTO_LOGIN_SRL\n"
            "    secret_env: QONTO_SECRET_KEY_SRL\n"
        )
        path = self._write_yaml(tmp_path, initial)
        with self._patch_project_root(tmp_path), patch(
            "invoicer.defaults.list_orgs",
            return_value=[{"id": "welance-srl"}],
        ), patch(
            "invoicer.defaults.get_defaults",
            return_value={},
        ):
            set_default("org", "welance-srl")

        text = path.read_text()
        # Original content intact
        assert "# my project config" in text
        assert "- id: welance-srl" in text
        # New defaults block present
        assert "defaults:\n  org: welance-srl\n" in text

    def test_update_existing_block_preserves_surrounding_content(self, tmp_path):
        initial = (
            "# header comment\n"
            "orgs:\n"
            "  - id: welance-srl\n"
            "\n"
            "defaults:\n"
            "  org: welance-srl\n"
            "  locale: it\n"
            "\n"
            "# below comment — MUST survive\n"
            "clients:\n"
            "  - clockify_id: abc\n"
        )
        path = self._write_yaml(tmp_path, initial)
        with self._patch_project_root(tmp_path), patch(
            "invoicer.defaults.list_orgs",
            return_value=[{"id": "welance-srl"}],
        ), patch(
            "invoicer.defaults.get_defaults",
            return_value={"org": "welance-srl", "locale": "it"},
        ):
            set_default("locale", "en")

        text = path.read_text()
        # Header comment survived
        assert "# header comment" in text
        # orgs block survived
        assert "  - id: welance-srl" in text
        # Below-defaults content survived (the critical test)
        assert "# below comment — MUST survive" in text
        assert "clients:" in text
        assert "- clockify_id: abc" in text
        # New locale in the defaults block
        assert "locale: en" in text
        # Old locale not there twice
        assert text.count("locale:") == 1

    def test_unset_removes_key_from_block(self, tmp_path):
        initial = (
            "defaults:\n"
            "  org: welance-srl\n"
            "  locale: it\n"
            "\n"
            "clients: []\n"
        )
        path = self._write_yaml(tmp_path, initial)
        with self._patch_project_root(tmp_path), patch(
            "invoicer.defaults.get_defaults",
            return_value={"org": "welance-srl", "locale": "it"},
        ):
            unset_default("locale")

        text = path.read_text()
        assert "org: welance-srl" in text
        assert "locale" not in text
        # Other content intact
        assert "clients: []" in text

    def test_unset_last_key_drops_whole_block(self, tmp_path):
        initial = (
            "orgs:\n"
            "  - id: welance-srl\n"
            "\n"
            "defaults:\n"
            "  org: welance-srl\n"
            "\n"
            "clients: []\n"
        )
        path = self._write_yaml(tmp_path, initial)
        with self._patch_project_root(tmp_path), patch(
            "invoicer.defaults.get_defaults",
            return_value={"org": "welance-srl"},
        ):
            unset_default("org")

        text = path.read_text()
        assert "defaults:" not in text
        # Surrounding content intact
        assert "orgs:" in text
        assert "clients: []" in text


class TestKnownKeys:
    def test_module_exposes_known_keys(self):
        assert set(defaults_mod.KNOWN_KEYS) == {"org", "locale", "gmail_sender"}
        assert set(defaults_mod.LOCALE_CHOICES) == {"it", "en", "de"}
