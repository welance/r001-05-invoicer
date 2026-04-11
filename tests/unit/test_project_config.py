"""Unit tests for the invoicer.yaml loader and fuzzy project matcher."""

from unittest.mock import patch

from invoicer.project_config import _normalize, find_projects

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

    def test_exact_alias_preferred_over_substring(self):
        """If query exactly matches one alias, don't return substring matches from others."""
        # 'r005-01' exactly matches pid_aaa's alias — should return ONLY that one
        # even though 'r005' is a substring of both r005-01 and r005-02 aliases.
        result = self._find("r005-01")
        assert len(result) == 1
        assert result[0][0] == "pid_aaa"
