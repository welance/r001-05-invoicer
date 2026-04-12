"""Unit tests for the invoicer.yaml loader and fuzzy project matcher."""

import os
from unittest.mock import patch

import pytest

from invoicer.project_config import (
    _normalize,
    _render_project_entry,
    activate_org,
    append_client_mapping,
    append_project_entry,
    find_projects,
    get_defaults,
    get_org,
    list_orgs,
    resolve_qonto_client_id,
)

_YAML_FIXTURE = {
    "clients": [],
    "projects": {
        "pid_aaa": {
            "alias": "r005-01",
            "name": "r005-01 - All-Safe Group Support",
        },
        "pid_bbb": {
            "alias": "r004-02",
            "name": "r004-02 - OptionFactory Recruitment SaaS",
        },
        "pid_ccc": {
            "alias": "r005-02",
            "name": "r005-02 - All-Safe Group Mobile App",
        },
    },
}


class TestNormalize:
    def test_lowercases(self):
        assert _normalize("Hello") == "hello"

    def test_strips_hyphens_and_spaces(self):
        assert _normalize("All-Safe Group") == "allsafegroup"

    def test_strips_underscores(self):
        assert _normalize("all_safe_group") == "allsafegroup"

    def test_empty_and_none(self):
        assert _normalize("") == ""
        assert _normalize(None) == ""


class TestFindProjects:
    def _find(self, query):
        with patch("invoicer.project_config.load_yaml", return_value=_YAML_FIXTURE):
            return find_projects(query)

    def test_exact_id_match(self):
        result = self._find("pid_aaa")
        assert len(result) == 1
        assert result[0][0] == "pid_aaa"

    def test_exact_alias_match(self):
        result = self._find("r005-01")
        assert len(result) == 1
        assert result[0][0] == "pid_aaa"

    def test_normalized_alias_match(self):
        # 'r00501' should match 'r005-01' after normalization
        result = self._find("r00501")
        assert len(result) == 1
        assert result[0][0] == "pid_aaa"

    def test_case_insensitive(self):
        result = self._find("R005-01")
        assert len(result) == 1
        assert result[0][0] == "pid_aaa"

    def test_substring_in_name(self):
        # 'OptionFactory' matches pid_bbb
        result = self._find("OptionFactory")
        assert len(result) == 1
        assert result[0][0] == "pid_bbb"

    def test_ambiguous_substring_returns_multiple(self):
        # 'All-Safe' or 'allsafe' matches both r005-01 and r005-02
        result = self._find("allsafe")
        assert len(result) == 2
        ids = {r[0] for r in result}
        assert ids == {"pid_aaa", "pid_ccc"}

    def test_empty_query(self):
        assert self._find("") == []

    def test_whitespace_only(self):
        assert self._find("   ") == []

    def test_no_match(self):
        assert self._find("completely-unknown-project-xyz") == []

    def test_query_with_punctuation_matches_normalized(self):
        # "All Safe!" normalizes to "allsafe" and matches
        result = self._find("All Safe!")
        assert len(result) == 2

    def test_empty_normalized_query_returns_empty(self):
        """Queries like '!!!' normalize to '' — must NOT return all projects."""
        assert self._find("!!!") == []
        assert self._find("...") == []
        assert self._find("  - - -  ") == []

    def test_exact_alias_preferred_over_substring(self):
        """If query exactly matches one alias, don't return substring matches from others."""
        # 'r005-01' exactly matches pid_aaa's alias — should return ONLY that one
        # even though 'r005' is a substring of both r005-01 and r005-02 aliases.
        result = self._find("r005-01")
        assert len(result) == 1
        assert result[0][0] == "pid_aaa"


_MULTI_ORG_FIXTURE = {
    "orgs": [
        {
            "id": "welance-srl",
            "country": "IT",
            "login_env": "QONTO_LOGIN_SRL",
            "secret_env": "QONTO_SECRET_KEY_SRL",
        },
        {
            "id": "welance-gmbh",
            "country": "DE",
            "login_env": "QONTO_LOGIN_GMBH",
            "secret_env": "QONTO_SECRET_KEY_GMBH",
        },
    ],
    "defaults": {
        "org": "welance-srl",
        "locale": "it",
    },
    "clients": [
        {
            "clockify_id": "cl_shared",
            "qonto_id": "q_srl_abc",
            "org": "welance-srl",
        },
        {
            "clockify_id": "cl_shared",
            "qonto_id": "q_gmbh_xyz",
            "org": "welance-gmbh",
        },
        {
            "clockify_id": "cl_orgless",
            "qonto_id": "q_legacy_123",
        },
    ],
}


class TestListOrgs:
    def test_lists_orgs_when_present(self):
        with patch(
            "invoicer.project_config.load_yaml_or_empty",
            return_value=_MULTI_ORG_FIXTURE,
        ):
            orgs = list_orgs()
        assert len(orgs) == 2
        assert orgs[0]["id"] == "welance-srl"

    def test_empty_when_no_orgs_block(self):
        with patch(
            "invoicer.project_config.load_yaml_or_empty",
            return_value={"projects": {}},
        ):
            assert list_orgs() == []


class TestGetOrg:
    def test_found(self):
        with patch(
            "invoicer.project_config.load_yaml_or_empty",
            return_value=_MULTI_ORG_FIXTURE,
        ):
            org = get_org("welance-gmbh")
        assert org["country"] == "DE"

    def test_missing_raises(self):
        with patch(
            "invoicer.project_config.load_yaml_or_empty",
            return_value=_MULTI_ORG_FIXTURE,
        ):
            with pytest.raises(RuntimeError, match="not found"):
                get_org("welance-nope")


class TestActivateOrg:
    def test_sets_qonto_env_vars(self, monkeypatch):
        monkeypatch.setenv("QONTO_LOGIN_GMBH", "welance-gmbh-9999")
        monkeypatch.setenv("QONTO_SECRET_KEY_GMBH", "secret-gmbh")
        monkeypatch.delenv("QONTO_LOGIN", raising=False)
        monkeypatch.delenv("QONTO_SECRET_KEY", raising=False)

        with patch(
            "invoicer.project_config.load_yaml_or_empty",
            return_value=_MULTI_ORG_FIXTURE,
        ):
            activate_org("welance-gmbh")

        assert os.environ["QONTO_LOGIN"] == "welance-gmbh-9999"
        assert os.environ["QONTO_SECRET_KEY"] == "secret-gmbh"

    def test_missing_env_var_raises(self, monkeypatch):
        monkeypatch.delenv("QONTO_LOGIN_SRL", raising=False)
        monkeypatch.delenv("QONTO_SECRET_KEY_SRL", raising=False)
        with patch(
            "invoicer.project_config.load_yaml_or_empty",
            return_value=_MULTI_ORG_FIXTURE,
        ):
            with pytest.raises(RuntimeError, match="not set"):
                activate_org("welance-srl")


class TestResolveClientWithOrg:
    def test_org_scoped_mapping(self):
        with patch("invoicer.project_config.load_yaml", return_value=_MULTI_ORG_FIXTURE):
            # Same clockify_id, different qonto ids per org
            assert resolve_qonto_client_id("cl_shared", org_id="welance-srl") == "q_srl_abc"
            assert resolve_qonto_client_id("cl_shared", org_id="welance-gmbh") == "q_gmbh_xyz"

    def test_orgless_mapping_matches_regardless(self):
        """A mapping without `org:` is org-agnostic — matches any org context."""
        with patch("invoicer.project_config.load_yaml", return_value=_MULTI_ORG_FIXTURE):
            assert resolve_qonto_client_id("cl_orgless", org_id="welance-srl") == "q_legacy_123"
            assert resolve_qonto_client_id("cl_orgless", org_id="welance-gmbh") == "q_legacy_123"


class TestGetDefaults:
    def test_reads_defaults_block(self):
        with patch(
            "invoicer.project_config.load_yaml_or_empty",
            return_value=_MULTI_ORG_FIXTURE,
        ):
            d = get_defaults()
        assert d == {"org": "welance-srl", "locale": "it"}

    def test_empty_when_no_defaults(self):
        with patch(
            "invoicer.project_config.load_yaml_or_empty",
            return_value={"projects": {}},
        ):
            assert get_defaults() == {}

    def test_empty_when_invoicer_yaml_missing(self, tmp_path, monkeypatch):
        """Regression: `invoicer defaults` must NOT crash with a traceback
        when invoicer.yaml doesn't exist in the current directory.

        The failing case happens e.g. when a user runs `invoicer defaults`
        from a clone that hasn't gone through `invoicer init` yet.
        """
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        # Fresh tmp_path has no invoicer.yaml — get_defaults should return {}
        assert get_defaults() == {}

    def test_list_orgs_empty_when_invoicer_yaml_missing(self, tmp_path, monkeypatch):
        """Same regression guard for list_orgs — it feeds into _resolve_org,
        which must work before `invoicer init` has run."""
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        assert list_orgs() == []


class TestAppendClientMapping:
    def _write_yaml(self, tmp_path, content):
        p = tmp_path / "invoicer.yaml"
        p.write_text(content)
        return p

    def test_creates_clients_block_when_missing(self, tmp_path, monkeypatch):
        self._write_yaml(tmp_path, "projects:\n  \"pid\": {}\n")
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        append_client_mapping({"clockify_id": "c1", "qonto_id": "q1"})
        text = (tmp_path / "invoicer.yaml").read_text()
        assert "clients:" in text
        assert 'clockify_id: "c1"' in text
        assert 'qonto_id: "q1"' in text

    def test_appends_to_existing_clients_block(self, tmp_path, monkeypatch):
        self._write_yaml(
            tmp_path,
            'clients:\n  - clockify_id: "existing"\n    qonto_id: "q_old"\n\nprojects: {}\n',
        )
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        append_client_mapping({"clockify_id": "c2", "qonto_id": "q2"})
        text = (tmp_path / "invoicer.yaml").read_text()
        assert 'clockify_id: "existing"' in text
        assert 'clockify_id: "c2"' in text
        assert "projects:" in text

    def test_idempotent_on_duplicate(self, tmp_path, monkeypatch):
        self._write_yaml(
            tmp_path,
            'clients:\n  - clockify_id: "c1"\n    qonto_id: "q1"\n',
        )
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        append_client_mapping({"clockify_id": "c1", "qonto_id": "q1"})
        text = (tmp_path / "invoicer.yaml").read_text()
        assert text.count("c1") == 1

    def test_org_scoped_not_duplicate_of_orgless(self, tmp_path, monkeypatch):
        self._write_yaml(
            tmp_path,
            'clients:\n  - clockify_id: "c1"\n    qonto_id: "q1"\n',
        )
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        append_client_mapping({"clockify_id": "c1", "qonto_id": "q2", "org": "srl"})
        text = (tmp_path / "invoicer.yaml").read_text()
        assert text.count("c1") == 2

    def test_raises_when_yaml_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        with pytest.raises(FileNotFoundError):
            append_client_mapping({"clockify_id": "c1", "qonto_id": "q1"})


class TestRenderProjectEntry:
    def test_basic_render(self):
        text = _render_project_entry("pid123", {
            "alias": "r001-03",
            "name": "r001-03 - ommi.shop",
            "rate_eur_per_hour": 85,
            "vat_rate": 0,
            "vat_exemption_reason": "N3.2",
            "payment_terms_days": 30,
            "rounding_minutes": 15,
        })
        assert '"pid123":' in text
        assert 'alias: "r001-03"' in text
        assert "rate_eur_per_hour: 85" in text
        assert "vat_rate: 0" in text
        assert 'vat_exemption_reason: "N3.2"' in text

    def test_skips_none_and_empty_values(self):
        text = _render_project_entry("pid", {
            "alias": "r",
            "name": "r",
            "rate_eur_per_hour": 100,
            "vat_exemption_reason": None,
            "description_template": "",
        })
        assert "vat_exemption_reason" not in text
        assert "description_template" not in text


class TestAppendProjectEntry:
    def _write_yaml(self, tmp_path, content):
        p = tmp_path / "invoicer.yaml"
        p.write_text(content)
        return p

    def test_creates_projects_block_when_missing(self, tmp_path, monkeypatch):
        self._write_yaml(tmp_path, "clients: []\n")
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        append_project_entry("pid_new", {"alias": "r", "name": "R", "rate_eur_per_hour": 85})
        text = (tmp_path / "invoicer.yaml").read_text()
        assert "projects:" in text
        assert '"pid_new":' in text
        assert "clients:" in text

    def test_appends_to_existing_projects_block(self, tmp_path, monkeypatch):
        self._write_yaml(
            tmp_path,
            'projects:\n  "pid_old":\n    alias: "old"\n    rate_eur_per_hour: 50\n',
        )
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        append_project_entry("pid_new", {"alias": "new", "name": "New", "rate_eur_per_hour": 85})
        text = (tmp_path / "invoicer.yaml").read_text()
        assert '"pid_old":' in text
        assert '"pid_new":' in text

    def test_replaces_existing_entry(self, tmp_path, monkeypatch):
        self._write_yaml(
            tmp_path,
            'projects:\n  "pid":\n    alias: "old"\n    rate_eur_per_hour: 50\n',
        )
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        append_project_entry("pid", {"alias": "updated", "name": "U", "rate_eur_per_hour": 100})
        text = (tmp_path / "invoicer.yaml").read_text()
        assert text.count('"pid":') == 1
        assert 'alias: "updated"' in text
        assert "rate_eur_per_hour: 100" in text
        assert "rate_eur_per_hour: 50" not in text

    def test_preserves_other_entries(self, tmp_path, monkeypatch):
        self._write_yaml(
            tmp_path,
            'projects:\n  "pid_a":\n    alias: "a"\n    rate_eur_per_hour: 50\n  "pid_b":\n    alias: "b"\n    rate_eur_per_hour: 60\n',
        )
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        append_project_entry("pid_c", {"alias": "c", "name": "C", "rate_eur_per_hour": 70})
        text = (tmp_path / "invoicer.yaml").read_text()
        assert '"pid_a":' in text
        assert '"pid_b":' in text
        assert '"pid_c":' in text

    def test_raises_when_yaml_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        with pytest.raises(FileNotFoundError):
            append_project_entry("pid", {"alias": "x"})
