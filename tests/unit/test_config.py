"""Regression tests for project-root resolution.

In v0.1.0 the project root was resolved from `Path(__file__).parents[2]`, which
meant an editable install leaked config between clones — running `invoicer init`
from a fresh clone would read/write the .env of the ORIGINAL install directory.

v0.1.1 fixes this: the root resolves to `$INVOICER_DIR` if set, otherwise CWD.
"""

from pathlib import Path

from invoicer.config import get_project_root


class TestGetProjectRoot:
    def test_uses_cwd_by_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("INVOICER_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        assert get_project_root() == tmp_path

    def test_invoicer_dir_env_var_overrides_cwd(self, tmp_path, monkeypatch):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.setenv("INVOICER_DIR", str(elsewhere))
        monkeypatch.chdir(tmp_path)  # deliberately NOT the override dir
        assert get_project_root() == elsewhere.resolve()

    def test_invoicer_dir_expands_tilde(self, monkeypatch):
        monkeypatch.setenv("INVOICER_DIR", "~/")
        result = get_project_root()
        assert str(result).startswith(str(Path.home()))

    def test_does_not_use_module_file_path(self, tmp_path, monkeypatch):
        """The critical regression: root must NOT come from __file__.parents[2].

        If we ever revert to __file__-based resolution, this test fails because
        the tmp_path CWD doesn't match the (fixed) module install location.
        """
        monkeypatch.delenv("INVOICER_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        root = get_project_root()
        # Should be the tmp dir, not wherever the invoicer package is installed
        assert root == tmp_path
        assert "invoicer" not in str(root).split("/")[-1].lower() or str(
            root
        ) == str(tmp_path)
