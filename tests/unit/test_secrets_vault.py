"""Unit tests for secrets_vault — 1Password CLI fetch for credentials.json.

All subprocess calls are mocked. We never shell out to a real `op` during
tests — that would require a signed-in 1Password account, defeating the
"no secrets in CI" invariant.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from invoicer.secrets_vault import (
    VaultError,
    check_op_authenticated,
    check_op_installed,
    fetch_credentials_json,
    fetch_credentials_json_from_config,
)


class TestCheckOpInstalled:
    def test_present_returns_cleanly(self):
        with patch("invoicer.secrets_vault.shutil.which", return_value="/usr/local/bin/op"):
            check_op_installed()  # no raise

    def test_absent_raises_with_install_hint(self):
        with patch("invoicer.secrets_vault.shutil.which", return_value=None):
            with pytest.raises(VaultError, match="not installed"):
                check_op_installed()

    def test_error_message_includes_platform_hints(self):
        with patch("invoicer.secrets_vault.shutil.which", return_value=None):
            try:
                check_op_installed()
            except VaultError as e:
                msg = str(e)
        # User should see actionable instructions for all three platforms
        assert "brew install 1password-cli" in msg
        assert "Windows" in msg
        assert "Linux" in msg
        # And the desktop-app integration hint
        assert "Integrate with 1Password CLI" in msg


class TestCheckOpAuthenticated:
    def _mock_run(self, *, returncode: int, stdout: str, stderr: str = ""):
        """Return a mock subprocess.CompletedProcess."""
        return subprocess.CompletedProcess(
            args=["op", "whoami", "--format=json"],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def test_signed_in_returns_email(self):
        payload = json.dumps(
            {
                "email": "enricoz@welance.com",
                "user_uuid": "abc123",
                "account_uuid": "xyz789",
            }
        )
        with patch(
            "invoicer.secrets_vault.subprocess.run",
            return_value=self._mock_run(returncode=0, stdout=payload),
        ):
            assert check_op_authenticated() == "enricoz@welance.com"

    def test_not_signed_in_raises_with_both_options(self):
        with patch(
            "invoicer.secrets_vault.subprocess.run",
            return_value=self._mock_run(
                returncode=1,
                stdout="",
                stderr="[ERROR] you are not currently signed in",
            ),
        ):
            try:
                check_op_authenticated()
                raise AssertionError("should have raised")
            except VaultError as e:
                msg = str(e)
        assert "Not signed in" in msg
        # Both auth paths mentioned
        assert "desktop app" in msg
        assert "op signin" in msg
        # stderr is surfaced for debugging
        assert "you are not currently signed in" in msg

    def test_timeout_raises_clean(self):
        with patch(
            "invoicer.secrets_vault.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                cmd=["op", "whoami"], timeout=10
            ),
        ):
            with pytest.raises(VaultError, match="timed out"):
                check_op_authenticated()

    def test_malformed_json_stdout_degrades_gracefully(self):
        """If `op whoami` returns success but non-JSON output, we don't
        crash — we fall back to a sentinel string."""
        with patch(
            "invoicer.secrets_vault.subprocess.run",
            return_value=self._mock_run(returncode=0, stdout="not json"),
        ):
            result = check_op_authenticated()
        assert "signed in" in result.lower()


class TestFetchCredentialsJson:
    _REF = 'op://p007-01 Welance/invoicer-credentials-json/credentials.json'

    def _patch_preflight(self):
        """Pretend `op` is installed and we're signed in."""
        return patch.multiple(
            "invoicer.secrets_vault",
            check_op_installed=lambda: None,
            check_op_authenticated=lambda: "enricoz@welance.com",
        )

    def test_success_writes_file(self, tmp_path):
        fake_json_bytes = b'{"installed": {"client_id": "xxx"}}'
        output_path = tmp_path / "credentials.json"

        mock_result = subprocess.CompletedProcess(
            args=["op", "read", self._REF],
            returncode=0,
            stdout=fake_json_bytes,
            stderr=b"",
        )

        with self._patch_preflight(), patch(
            "invoicer.secrets_vault.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            fetch_credentials_json(
                vault="p007-01 Welance",
                item="invoicer-credentials-json",
                file="credentials.json",
                output_path=output_path,
            )

        # File written with exact bytes from stdout — no re-encoding
        assert output_path.read_bytes() == fake_json_bytes
        # op was invoked with the right secret-reference URI
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "op"
        assert call_args[1] == "read"
        assert call_args[2] == self._REF

    def test_fetch_failure_raises_with_diagnostics(self, tmp_path):
        mock_result = subprocess.CompletedProcess(
            args=["op", "read", self._REF],
            returncode=1,
            stdout=b"",
            stderr=b"[ERROR] item not found: invoicer-credentials-json",
        )

        with self._patch_preflight(), patch(
            "invoicer.secrets_vault.subprocess.run",
            return_value=mock_result,
        ):
            try:
                fetch_credentials_json(
                    vault="p007-01 Welance",
                    item="invoicer-credentials-json",
                    file="credentials.json",
                    output_path=tmp_path / "credentials.json",
                )
                raise AssertionError("should have raised")
            except VaultError as e:
                msg = str(e)

        # User gets the vault name (for typo detection)
        assert "p007-01 Welance" in msg
        # The op error is surfaced
        assert "item not found" in msg
        # And the common-causes checklist
        assert "not a member of the vault" in msg
        assert "typo" in msg
        # Signed-in-as is shown for debugging
        assert "enricoz@welance.com" in msg

    def test_output_path_parent_created(self, tmp_path):
        nested = tmp_path / "nested" / "deeper" / "credentials.json"
        mock_result = subprocess.CompletedProcess(
            args=["op", "read", self._REF],
            returncode=0,
            stdout=b'{"x": 1}',
            stderr=b"",
        )
        with self._patch_preflight(), patch(
            "invoicer.secrets_vault.subprocess.run",
            return_value=mock_result,
        ):
            fetch_credentials_json(
                vault="p007-01 Welance",
                item="invoicer-credentials-json",
                file="credentials.json",
                output_path=nested,
            )
        assert nested.exists()
        assert nested.read_bytes() == b'{"x": 1}'

    def test_timeout_raises_clean(self, tmp_path):
        with self._patch_preflight(), patch(
            "invoicer.secrets_vault.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                cmd=["op", "read"], timeout=30
            ),
        ):
            with pytest.raises(VaultError, match="timed out"):
                fetch_credentials_json(
                    vault="p007-01 Welance",
                    item="invoicer-credentials-json",
                    file="credentials.json",
                    output_path=tmp_path / "credentials.json",
                )


class TestFetchCredentialsJsonFromConfig:
    def test_no_secrets_block_returns_false(self):
        with patch(
            "invoicer.secrets_vault.load_yaml_or_empty",
            return_value={"orgs": [], "projects": {}},
        ):
            fetched, msg = fetch_credentials_json_from_config()
        assert fetched is False
        assert "no `secrets.credentials_json` block" in msg

    def test_empty_secrets_block_returns_false(self):
        with patch(
            "invoicer.secrets_vault.load_yaml_or_empty",
            return_value={"secrets": {}},
        ):
            fetched, msg = fetch_credentials_json_from_config()
        assert fetched is False

    def test_unsupported_source_raises(self):
        with patch(
            "invoicer.secrets_vault.load_yaml_or_empty",
            return_value={
                "secrets": {
                    "credentials_json": {
                        "source": "bitwarden",
                        "vault": "foo",
                        "item": "bar",
                    }
                }
            },
        ):
            with pytest.raises(VaultError, match="Unsupported secrets source"):
                fetch_credentials_json_from_config()

    def test_missing_vault_or_item_raises(self):
        with patch(
            "invoicer.secrets_vault.load_yaml_or_empty",
            return_value={
                "secrets": {
                    "credentials_json": {"source": "1password", "vault": "x"}
                }
            },
        ):
            with pytest.raises(VaultError, match="`vault` and `item`"):
                fetch_credentials_json_from_config()

    def test_valid_config_invokes_fetcher_with_right_args(self, tmp_path):
        config = {
            "secrets": {
                "credentials_json": {
                    "source": "1password",
                    "vault": "p007-01 Welance",
                    "item": "invoicer-credentials-json",
                    "file": "credentials.json",
                }
            }
        }
        captured: dict = {}

        def _fake_fetch(*, vault, item, file, output_path):
            captured["vault"] = vault
            captured["item"] = item
            captured["file"] = file
            captured["output_path"] = output_path

        with patch(
            "invoicer.secrets_vault.load_yaml_or_empty", return_value=config
        ), patch(
            "invoicer.secrets_vault.get_project_root", return_value=tmp_path
        ), patch(
            "invoicer.secrets_vault.fetch_credentials_json",
            side_effect=_fake_fetch,
        ):
            fetched, msg = fetch_credentials_json_from_config()

        assert fetched is True
        assert captured["vault"] == "p007-01 Welance"
        assert captured["item"] == "invoicer-credentials-json"
        assert captured["file"] == "credentials.json"
        assert captured["output_path"] == tmp_path / "credentials.json"
        assert "p007-01 Welance" in msg

    def test_file_field_defaults_to_credentials_json(self, tmp_path):
        """When `file:` is omitted from invoicer.yaml, default to
        the conventional name."""
        config = {
            "secrets": {
                "credentials_json": {
                    "source": "1password",
                    "vault": "v",
                    "item": "i",
                    # no `file:` key
                }
            }
        }
        captured: dict = {}

        def _fake_fetch(*, vault, item, file, output_path):
            captured["file"] = file

        with patch(
            "invoicer.secrets_vault.load_yaml_or_empty", return_value=config
        ), patch(
            "invoicer.secrets_vault.get_project_root", return_value=tmp_path
        ), patch(
            "invoicer.secrets_vault.fetch_credentials_json",
            side_effect=_fake_fetch,
        ):
            fetch_credentials_json_from_config()
        assert captured["file"] == "credentials.json"


class TestNoSecretContentInErrorMessages:
    """Paranoid regression: the user-visible error path must never leak
    the contents of credentials.json into the terminal or any log line.
    """

    def test_stdout_bytes_never_formatted_into_error(self, tmp_path):
        """If `op` somehow returns non-zero AND puts real bytes on stdout
        (shouldn't happen, but let's be paranoid), those bytes must not
        make it into the VaultError message."""
        secret_bytes = b'{"installed":{"client_secret":"DO_NOT_LEAK_THIS"}}'
        mock_result = subprocess.CompletedProcess(
            args=["op", "read"],
            returncode=1,
            stdout=secret_bytes,  # unusual but possible
            stderr=b"[ERROR] something went wrong",
        )
        with patch(
            "invoicer.secrets_vault.check_op_installed", lambda: None
        ), patch(
            "invoicer.secrets_vault.check_op_authenticated",
            lambda: "a@b.c",
        ), patch(
            "invoicer.secrets_vault.subprocess.run",
            return_value=mock_result,
        ):
            try:
                fetch_credentials_json(
                    vault="v",
                    item="i",
                    file="credentials.json",
                    output_path=tmp_path / "credentials.json",
                )
                raise AssertionError("should have raised")
            except VaultError as e:
                msg = str(e)
        # The stderr IS in the message (that's useful diagnostics)
        assert "something went wrong" in msg
        # But stdout bytes are NEVER in the message
        assert "DO_NOT_LEAK_THIS" not in msg
        assert "client_secret" not in msg


class TestFetchCredentialsJsonPathFromProject:
    """The fetcher must land credentials.json at get_project_root() / 'credentials.json',
    not at a hardcoded path. This test guards the wiring between fetch_credentials_json_from_config
    and get_project_root — swapping one for INVOICER_DIR must Just Work."""

    def test_respects_invoicer_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INVOICER_DIR", str(tmp_path))
        (tmp_path / "invoicer.yaml").write_text(
            'secrets:\n'
            '  credentials_json:\n'
            '    source: 1password\n'
            '    vault: "p007-01 Welance"\n'
            '    item: invoicer-credentials-json\n'
            '    file: credentials.json\n'
        )
        mock_result = subprocess.CompletedProcess(
            args=["op", "read"],
            returncode=0,
            stdout=b'{"installed": {"client_id": "x"}}',
            stderr=b"",
        )
        with patch(
            "invoicer.secrets_vault.check_op_installed", lambda: None
        ), patch(
            "invoicer.secrets_vault.check_op_authenticated",
            lambda: "a@b.c",
        ), patch(
            "invoicer.secrets_vault.subprocess.run",
            return_value=mock_result,
        ):
            fetched, _msg = fetch_credentials_json_from_config()
        assert fetched is True
        assert (tmp_path / "credentials.json").exists()
        assert (
            Path(tmp_path / "credentials.json").read_bytes()
            == b'{"installed": {"client_id": "x"}}'
        )
