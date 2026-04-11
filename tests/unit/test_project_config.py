"""Unit tests for the invoicer.yaml loader and fuzzy project matcher."""

import os
from unittest.mock import patch

import pytest

from invoicer.project_config import (
    _normalize,
    activate_org,
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
        with patch("invoicer.project_config.load_yaml", return_value=_MULTI_ORG_FIXTURE):
            orgs = list_orgs()
        assert len(orgs) == 2
        assert orgs[0]["id"] == "welance-srl"

    def test_empty_when_no_orgs_block(self):
        with patch("invoicer.project_config.load_yaml", return_value={"projects": {}}):
            assert list_orgs() == []


class TestGetOrg:
    def test_found(self):
        with patch("invoicer.project_config.load_yaml", return_value=_MULTI_ORG_FIXTURE):
            org = get_org("welance-gmbh")
        assert org["country"] == "DE"

    def test_missing_raises(self):
        with patch("invoicer.project_config.load_yaml", return_value=_MULTI_ORG_FIXTURE):
            with pytest.raises(RuntimeError, match="not found"):
                get_org("welance-nope")


class TestActivateOrg:
    def test_sets_qonto_env_vars(self, monkeypatch):
        monkeypatch.setenv("QONTO_LOGIN_GMBH", "welance-gmbh-9999")
        monkeypatch.setenv("QONTO_SECRET_KEY_GMBH", "secret-gmbh")
        monkeypatch.delenv("QONTO_LOGIN", raising=False)
        monkeypatch.delenv("QONTO_SECRET_KEY", raising=False)

        with patch("invoicer.project_config.load_yaml", return_value=_MULTI_ORG_FIXTURE):
            activate_org("welance-gmbh")

        assert os.environ["QONTO_LOGIN"] == "welance-gmbh-9999"
        assert os.environ["QONTO_SECRET_KEY"] == "secret-gmbh"

    def test_missing_env_var_raises(self, monkeypatch):
        monkeypatch.delenv("QONTO_LOGIN_SRL", raising=False)
        monkeypatch.delenv("QONTO_SECRET_KEY_SRL", raising=False)
        with patch("invoicer.project_config.load_yaml", return_value=_MULTI_ORG_FIXTURE):
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
        with patch("invoicer.project_config.load_yaml", return_value=_MULTI_ORG_FIXTURE):
            d = get_defaults()
        assert d == {"org": "welance-srl", "locale": "it"}

    def test_empty_when_no_defaults(self):
        with patch("invoicer.project_config.load_yaml", return_value={"projects": {}}):
            assert get_defaults() == {}
