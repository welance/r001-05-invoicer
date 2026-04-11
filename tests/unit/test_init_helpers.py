"""Unit tests for init_cmd detection helpers and orgs-block surgery.

The interactive prompt flow (`_ensure_*` functions) is intentionally NOT
tested here — mocking questionary round-trips is more pain than value
and those functions are thin wrappers around pure helpers we DO test.
"""

from unittest.mock import patch

from invoicer.init_cmd import (
    _WIZARD_STEPS,
    _check_prerequisites,
    _detect_anthropic_configured,
    _detect_clockify_configured,
    _detect_gmail_sender_configured,
    _detect_qonto_orgs_in_env,
    _env_suffix,
    _orgs_blocks_differ,
    _print_welcome_panel,
)
from invoicer.project_config import (
    _find_orgs_block,
    _find_secrets_block,
    render_orgs_block,
    render_secrets_block,
    write_orgs_block,
    write_secrets_credentials_json_block,
)


class TestDetectQontoOrgsInEnv:
    def test_single_org_paired(self):
        env = {
            "QONTO_LOGIN_WELANCE_SRL": "welance-srl-1234",
            "QONTO_SECRET_KEY_WELANCE_SRL": "secret123",
        }
        out = _detect_qonto_orgs_in_env(env)
        assert len(out) == 1
        assert out[0]["id"] == "welance-srl"
        assert out[0]["login"] == "welance-srl-1234"
        assert out[0]["secret"] == "secret123"
        assert out[0]["country"] == ""  # unknown from .env

    def test_multiple_orgs(self):
        env = {
            "QONTO_LOGIN_WELANCE_SRL": "srl-slug",
            "QONTO_SECRET_KEY_WELANCE_SRL": "srl-secret",
            "QONTO_LOGIN_WELANCE_GMBH": "gmbh-slug",
            "QONTO_SECRET_KEY_WELANCE_GMBH": "gmbh-secret",
        }
        out = _detect_qonto_orgs_in_env(env)
        assert len(out) == 2
        ids = {o["id"] for o in out}
        assert ids == {"welance-srl", "welance-gmbh"}

    def test_unpaired_login_without_secret_is_skipped(self):
        env = {"QONTO_LOGIN_FOO": "slug-only", "CLOCKIFY_API_KEY": "abc"}
        assert _detect_qonto_orgs_in_env(env) == []

    def test_unpaired_secret_without_login_is_skipped(self):
        env = {"QONTO_SECRET_KEY_FOO": "secret-only"}
        assert _detect_qonto_orgs_in_env(env) == []

    def test_empty_env(self):
        assert _detect_qonto_orgs_in_env({}) == []

    def test_ignores_legacy_qonto_login_without_suffix(self):
        """Legacy single-org mode has bare QONTO_LOGIN / QONTO_SECRET_KEY
        without a suffix. The detector must not pair them into a malformed
        org entry."""
        env = {
            "QONTO_LOGIN": "legacy-slug",
            "QONTO_SECRET_KEY": "legacy-secret",
        }
        assert _detect_qonto_orgs_in_env(env) == []


class TestDetectOtherSections:
    def test_clockify_both_keys_required(self):
        assert _detect_clockify_configured({"CLOCKIFY_API_KEY": "x"}) is False
        assert _detect_clockify_configured({"CLOCKIFY_WORKSPACE_ID": "x"}) is False
        assert (
            _detect_clockify_configured(
                {"CLOCKIFY_API_KEY": "x", "CLOCKIFY_WORKSPACE_ID": "y"}
            )
            is True
        )

    def test_gmail_sender_only_checks_env_key(self):
        assert _detect_gmail_sender_configured({}) is False
        assert _detect_gmail_sender_configured({"GMAIL_SENDER": ""}) is False
        assert (
            _detect_gmail_sender_configured({"GMAIL_SENDER": "a@b.c"}) is True
        )

    def test_anthropic(self):
        assert _detect_anthropic_configured({}) is False
        assert (
            _detect_anthropic_configured({"ANTHROPIC_API_KEY": "sk-..."}) is True
        )


class TestEnvSuffix:
    def test_simple(self):
        assert _env_suffix("welance-srl") == "WELANCE_SRL"

    def test_already_uppercase(self):
        assert _env_suffix("WELANCE_SRL") == "WELANCE_SRL"

    def test_collapses_multiple_non_alnum(self):
        assert _env_suffix("welance--srl  gmbh") == "WELANCE_SRL_GMBH"

    def test_strips_leading_trailing_underscores(self):
        assert _env_suffix("-welance-") == "WELANCE"

    def test_empty_falls_back(self):
        assert _env_suffix("") == "ORG"


class TestOrgsBlocksDiffer:
    def test_empty_vs_empty(self):
        assert _orgs_blocks_differ([], []) is False

    def test_empty_vs_populated(self):
        assert _orgs_blocks_differ([], [{"id": "a"}]) is True

    def test_same_list_no_diff(self):
        a = [
            {
                "id": "welance-srl",
                "country": "IT",
                "login_env": "QONTO_LOGIN_WELANCE_SRL",
                "secret_env": "QONTO_SECRET_KEY_WELANCE_SRL",
            }
        ]
        assert _orgs_blocks_differ(a, a) is False

    def test_country_mismatch_is_diff(self):
        a = [
            {
                "id": "welance-srl",
                "country": "IT",
                "login_env": "QONTO_LOGIN_WELANCE_SRL",
                "secret_env": "QONTO_SECRET_KEY_WELANCE_SRL",
            }
        ]
        b = [{**a[0], "country": "DE"}]
        assert _orgs_blocks_differ(a, b) is True

    def test_different_lengths(self):
        a = [{"id": "a"}]
        b = [{"id": "a"}, {"id": "b"}]
        assert _orgs_blocks_differ(a, b) is True

    def test_different_ids(self):
        a = [
            {
                "id": "welance-srl",
                "country": "IT",
                "login_env": "X",
                "secret_env": "Y",
            }
        ]
        b = [
            {
                "id": "welance-gmbh",
                "country": "IT",
                "login_env": "X",
                "secret_env": "Y",
            }
        ]
        assert _orgs_blocks_differ(a, b) is True


class TestRenderOrgsBlock:
    def test_empty_renders_empty(self):
        assert render_orgs_block([]) == ""

    def test_single_org(self):
        out = render_orgs_block(
            [
                {
                    "id": "welance-srl",
                    "country": "IT",
                    "login_env": "QONTO_LOGIN_WELANCE_SRL",
                    "secret_env": "QONTO_SECRET_KEY_WELANCE_SRL",
                }
            ]
        )
        assert "orgs:" in out
        assert "- id: welance-srl" in out
        assert "country: IT" in out
        assert "login_env: QONTO_LOGIN_WELANCE_SRL" in out
        assert "secret_env: QONTO_SECRET_KEY_WELANCE_SRL" in out
        assert out.endswith("\n")

    def test_preserves_key_order(self):
        out = render_orgs_block(
            [
                {
                    "id": "a",
                    "country": "IT",
                    "login_env": "L",
                    "secret_env": "S",
                }
            ]
        )
        lines = out.splitlines()
        # Order is id → country → login_env → secret_env
        assert lines[1].strip() == "- id: a"
        assert lines[2].strip() == "country: IT"
        assert lines[3].strip() == "login_env: L"
        assert lines[4].strip() == "secret_env: S"


class TestFindOrgsBlock:
    def test_finds_simple_block(self):
        lines = [
            "# header\n",
            "orgs:\n",
            "  - id: welance-srl\n",
            "    country: IT\n",
            "    login_env: QONTO_LOGIN_WELANCE_SRL\n",
            "    secret_env: QONTO_SECRET_KEY_WELANCE_SRL\n",
            "\n",
            "clients:\n",
            "  - clockify_id: abc\n",
        ]
        found = _find_orgs_block(lines)
        assert found is not None
        start, end = found
        assert start == 1
        # End should include the blank line but stop before `clients:`
        assert end == 7

    def test_missing_block(self):
        lines = ["clients:\n", "  - foo: bar\n"]
        assert _find_orgs_block(lines) is None

    def test_ignores_nested_orgs(self):
        lines = [
            "projects:\n",
            "  proj_abc:\n",
            "    orgs:\n",  # nested — not top-level
            "      foo: bar\n",
        ]
        assert _find_orgs_block(lines) is None


class TestWriteOrgsBlockRoundTrip:
    def _patch_root(self, tmp_path):
        return patch(
            "invoicer.project_config.get_project_root",
            return_value=tmp_path,
        )

    def test_insert_into_yaml_with_no_orgs_block(self, tmp_path):
        initial = (
            "# my project\n"
            "clients:\n"
            "  - clockify_id: abc\n"
            "    qonto_id: xyz\n"
        )
        (tmp_path / "invoicer.yaml").write_text(initial)
        with self._patch_root(tmp_path):
            write_orgs_block(
                [
                    {
                        "id": "welance-srl",
                        "country": "IT",
                        "login_env": "QONTO_LOGIN_WELANCE_SRL",
                        "secret_env": "QONTO_SECRET_KEY_WELANCE_SRL",
                    }
                ]
            )
        text = (tmp_path / "invoicer.yaml").read_text()
        assert "orgs:" in text
        assert "- id: welance-srl" in text
        # Header comment still there
        assert "# my project" in text
        # Original clients block still there
        assert "- clockify_id: abc" in text

    def test_replace_existing_orgs_block_preserves_surrounding(self, tmp_path):
        initial = (
            "# header\n"
            "orgs:\n"
            "  - id: welance-srl\n"
            "    country: IT\n"
            "    login_env: OLD_LOGIN\n"
            "    secret_env: OLD_SECRET\n"
            "\n"
            "# below comment — MUST survive\n"
            "clients:\n"
            "  - clockify_id: abc\n"
        )
        (tmp_path / "invoicer.yaml").write_text(initial)
        with self._patch_root(tmp_path):
            write_orgs_block(
                [
                    {
                        "id": "welance-srl",
                        "country": "IT",
                        "login_env": "QONTO_LOGIN_WELANCE_SRL",
                        "secret_env": "QONTO_SECRET_KEY_WELANCE_SRL",
                    },
                    {
                        "id": "welance-gmbh",
                        "country": "DE",
                        "login_env": "QONTO_LOGIN_WELANCE_GMBH",
                        "secret_env": "QONTO_SECRET_KEY_WELANCE_GMBH",
                    },
                ]
            )
        text = (tmp_path / "invoicer.yaml").read_text()
        # New values present
        assert "QONTO_LOGIN_WELANCE_SRL" in text
        assert "QONTO_LOGIN_WELANCE_GMBH" in text
        assert "- id: welance-gmbh" in text
        assert "country: DE" in text
        # Old values GONE
        assert "OLD_LOGIN" not in text
        assert "OLD_SECRET" not in text
        # Surrounding content preserved
        assert "# header" in text
        assert "# below comment — MUST survive" in text
        assert "clients:" in text
        assert "- clockify_id: abc" in text

    def test_raises_when_invoicer_yaml_missing(self, tmp_path):
        with self._patch_root(tmp_path):
            import pytest

            with pytest.raises(FileNotFoundError, match="Run `invoicer init`"):
                write_orgs_block(
                    [
                        {
                            "id": "a",
                            "country": "IT",
                            "login_env": "L",
                            "secret_env": "S",
                        }
                    ]
                )


class TestRenderSecretsBlock:
    def test_empty_renders_empty(self):
        assert render_secrets_block({}) == ""

    def test_quotes_vault_name_with_spaces(self):
        out = render_secrets_block(
            {
                "source": "1password",
                "vault": "p007-01 Welance",
                "item": "invoicer-credentials-json",
                "file": "credentials.json",
            }
        )
        # Vault name MUST be quoted because it has spaces
        assert 'vault: "p007-01 Welance"' in out

    def test_no_quotes_for_simple_vault_name(self):
        out = render_secrets_block(
            {
                "source": "1password",
                "vault": "Engineering",
                "item": "invoicer-credentials-json",
                "file": "credentials.json",
            }
        )
        # No spaces → no quotes (cleaner output)
        assert "vault: Engineering" in out
        assert 'vault: "Engineering"' not in out

    def test_fixed_key_order(self):
        out = render_secrets_block(
            {
                "file": "credentials.json",
                "source": "1password",
                "vault": "V",
                "item": "I",
            }
        )
        lines = out.splitlines()
        # Order is source → vault → item → file regardless of dict insertion
        assert lines[0] == "secrets:"
        assert lines[1] == "  credentials_json:"
        assert lines[2] == "    source: 1password"
        assert lines[3] == "    vault: V"
        assert lines[4] == "    item: I"
        assert lines[5] == "    file: credentials.json"

    def test_skips_empty_values(self):
        out = render_secrets_block(
            {
                "source": "1password",
                "vault": "V",
                "item": "",  # empty, must be skipped
                "file": None,  # None, must be skipped
            }
        )
        assert "item:" not in out
        assert "file:" not in out


class TestFindSecretsBlock:
    def test_finds_simple_block(self):
        lines = [
            "# header\n",
            "orgs:\n",
            "  - id: a\n",
            "\n",
            "secrets:\n",
            "  credentials_json:\n",
            '    source: 1password\n',
            '    vault: "p007-01 Welance"\n',
            "    item: invoicer-credentials-json\n",
            "    file: credentials.json\n",
            "\n",
            "clients:\n",
            "  - foo: bar\n",
        ]
        found = _find_secrets_block(lines)
        assert found is not None
        start, end = found
        assert start == 4
        # End should include the blank line after the block but stop before `clients:`
        assert end == 11

    def test_missing_block(self):
        lines = ["orgs:\n", "  - id: a\n", "clients:\n"]
        assert _find_secrets_block(lines) is None

    def test_ignores_nested_secrets_key(self):
        lines = [
            "projects:\n",
            "  proj_abc:\n",
            "    secrets:\n",  # nested — not a top-level key
            "      foo: bar\n",
        ]
        assert _find_secrets_block(lines) is None


class TestWizardHelpers:
    """The welcome panel and pre-flight check are pure output helpers —
    they have no return value to assert on, so we just verify they run
    without exploding and that key content lands in stdout/stderr."""

    def test_wizard_steps_not_empty(self):
        assert len(_WIZARD_STEPS) >= 4, "wizard should have multiple steps"

    def test_wizard_steps_look_sane(self):
        # Each step is a non-empty human-readable string
        for step in _WIZARD_STEPS:
            assert isinstance(step, str)
            assert len(step) > 5

    def test_print_welcome_panel_runs_without_error(self, capsys):
        _print_welcome_panel()
        captured = capsys.readouterr()
        # The panel should mention the step count and the name
        assert "invoicer setup wizard" in captured.out
        # All step descriptions should appear somewhere
        for step in _WIZARD_STEPS:
            # Partial match because rich may wrap long lines
            first_word = step.split()[0]
            assert first_word in captured.out

    def test_check_prerequisites_all_present(self, capsys):
        """When every tool is on PATH, the output shows green checks
        and no install hints."""
        with patch(
            "invoicer.init_cmd.shutil.which",
            side_effect=lambda name: f"/usr/local/bin/{name}",
        ):
            _check_prerequisites()
        captured = capsys.readouterr()
        # All three tool names appear with a success marker
        for tool in ["uv", "git", "op"]:
            assert tool in captured.out
        # No install URLs should land in stderr when everything's found
        assert "install:" not in captured.err

    def test_check_prerequisites_all_missing(self, capsys):
        """When nothing is on PATH, each tool shows a cross + install URL
        in stderr. Non-blocking — no raise."""
        with patch("invoicer.init_cmd.shutil.which", return_value=None):
            _check_prerequisites()
        captured = capsys.readouterr()
        # All three tool names still appear
        for tool in ["uv", "git", "op"]:
            assert tool in captured.out
        # And install hints land in stderr for all of them
        assert "install:" in captured.err
        # The reassurance message appears
        assert "aren't blockers" in captured.err

    def test_check_prerequisites_partial(self, capsys):
        """Mixed state: uv present, git missing, op missing. Output should
        be clear about which is which."""

        def which(name):
            return "/usr/local/bin/uv" if name == "uv" else None

        with patch("invoicer.init_cmd.shutil.which", side_effect=which):
            _check_prerequisites()
        captured = capsys.readouterr()
        # git and op show install URLs
        assert "git-scm.com" in captured.err
        assert "developer.1password.com" in captured.err
        # uv does not
        assert "astral.sh/uv" not in captured.err


class TestIsFirstRun:
    """help_cmd._is_first_run detects whether the current directory looks
    like an unconfigured clone — if so, the `invoicer help` welcome panel
    shows a prominent call-to-action pointing at `invoicer init`."""

    def test_first_run_when_no_env_or_yaml(self, tmp_path, monkeypatch):
        from invoicer.help_cmd import _is_first_run

        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        assert _is_first_run() is True

    def test_not_first_run_when_env_exists(self, tmp_path, monkeypatch):
        from invoicer.help_cmd import _is_first_run

        (tmp_path / ".env").write_text("CLOCKIFY_API_KEY=foo\n")
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        assert _is_first_run() is False

    def test_not_first_run_when_invoicer_yaml_exists(self, tmp_path, monkeypatch):
        from invoicer.help_cmd import _is_first_run

        (tmp_path / "invoicer.yaml").write_text("clients: []\n")
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        assert _is_first_run() is False

    def test_not_first_run_when_both_exist(self, tmp_path, monkeypatch):
        from invoicer.help_cmd import _is_first_run

        (tmp_path / ".env").write_text("CLOCKIFY_API_KEY=foo\n")
        (tmp_path / "invoicer.yaml").write_text("clients: []\n")
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        assert _is_first_run() is False


class TestWriteSecretsCredentialsJsonBlockRoundTrip:
    def _patch_root(self, tmp_path):
        return patch(
            "invoicer.project_config.get_project_root",
            return_value=tmp_path,
        )

    def test_insert_into_yaml_with_no_secrets_block(self, tmp_path):
        initial = (
            "# my project\n"
            "orgs:\n"
            "  - id: welance-srl\n"
            "    country: IT\n"
            "    login_env: QONTO_LOGIN_WELANCE_SRL\n"
            "    secret_env: QONTO_SECRET_KEY_WELANCE_SRL\n"
            "\n"
            "clients:\n"
            "  - clockify_id: abc\n"
        )
        (tmp_path / "invoicer.yaml").write_text(initial)
        with self._patch_root(tmp_path):
            write_secrets_credentials_json_block(
                vault="p007-01 Welance",
                item="invoicer-credentials-json",
                file="credentials.json",
            )
        text = (tmp_path / "invoicer.yaml").read_text()
        # secrets block was inserted
        assert "secrets:" in text
        assert "credentials_json:" in text
        assert 'vault: "p007-01 Welance"' in text  # quoted because of space
        assert "item: invoicer-credentials-json" in text
        # Original content survived
        assert "# my project" in text
        assert "QONTO_LOGIN_WELANCE_SRL" in text
        assert "- clockify_id: abc" in text

    def test_replace_existing_secrets_block_preserves_surrounding(self, tmp_path):
        initial = (
            "# header\n"
            "secrets:\n"
            "  credentials_json:\n"
            "    source: 1password\n"
            "    vault: Old Vault\n"
            "    item: old-item\n"
            "    file: old.json\n"
            "\n"
            "# below comment — MUST survive\n"
            "orgs:\n"
            "  - id: welance-srl\n"
        )
        (tmp_path / "invoicer.yaml").write_text(initial)
        with self._patch_root(tmp_path):
            write_secrets_credentials_json_block(
                vault="New Vault With Space",
                item="new-item",
                file="credentials.json",
            )
        text = (tmp_path / "invoicer.yaml").read_text()
        # New values present
        assert 'vault: "New Vault With Space"' in text
        assert "item: new-item" in text
        assert "file: credentials.json" in text
        # Old values GONE
        assert "Old Vault" not in text
        assert "old-item" not in text
        assert "old.json" not in text
        # Surrounding content survived
        assert "# header" in text
        assert "# below comment — MUST survive" in text
        assert "- id: welance-srl" in text

    def test_raises_when_invoicer_yaml_missing(self, tmp_path):
        import pytest

        with self._patch_root(tmp_path):
            with pytest.raises(FileNotFoundError, match="Run `invoicer init`"):
                write_secrets_credentials_json_block(
                    vault="v", item="i", file="credentials.json"
                )
