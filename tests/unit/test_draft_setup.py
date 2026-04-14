"""Unit tests for the draft auto-onboarding pure helpers.

No I/O, no mocks — just the pure functions that the wizard calls internally.
"""

from invoicer.draft_setup import (
    check_client_completeness,
    derive_alias_from_name,
    looks_like_clockify_id,
    synthesize_project_entry,
    vat_defaults_for_country_pair,
)


class TestVatDefaults:
    def test_it_to_it(self):
        d = vat_defaults_for_country_pair("IT", "IT")
        assert d["vat_rate"] == 22
        assert d["vat_exemption_reason"] is None

    def test_it_to_eu(self):
        d = vat_defaults_for_country_pair("IT", "DE")
        assert d["vat_rate"] == 0
        assert d["vat_exemption_reason"] == "N3.2"

    def test_it_to_non_eu(self):
        d = vat_defaults_for_country_pair("IT", "US")
        assert d["vat_rate"] == 0
        assert d["vat_exemption_reason"] == "N3.1"

    def test_de_to_de(self):
        d = vat_defaults_for_country_pair("DE", "DE")
        assert d["vat_rate"] == 19
        assert d["vat_exemption_reason"] is None

    def test_de_to_eu(self):
        d = vat_defaults_for_country_pair("DE", "FR")
        assert d["vat_rate"] == 0
        assert d["vat_exemption_reason"] is None

    def test_de_to_non_eu(self):
        d = vat_defaults_for_country_pair("DE", "US")
        assert d["vat_rate"] == 0

    def test_unknown_pair(self):
        d = vat_defaults_for_country_pair(None, None)
        assert d["vat_rate"] == 0

    def test_case_insensitive(self):
        d = vat_defaults_for_country_pair("it", "de")
        assert d["vat_rate"] == 0
        assert d["vat_exemption_reason"] == "N3.2"


class TestDeriveAlias:
    def test_rXXX_prefix(self):
        assert derive_alias_from_name("r001-03 - ommi.shop") == "r001-03"

    def test_rXXX_prefix_uppercase(self):
        assert derive_alias_from_name("R005-01 - All-Safe Group Support") == "r005-01"

    def test_no_hyphen_uses_first_word(self):
        assert derive_alias_from_name("OptionFactory Recruitment SaaS") == "optionfactory"

    def test_empty_string(self):
        assert derive_alias_from_name("") == ""

    def test_none(self):
        assert derive_alias_from_name(None) == ""

    def test_single_word(self):
        assert derive_alias_from_name("Acme") == "acme"


class TestCheckClientCompleteness:
    def _base_client(self, **overrides):
        c = {
            "name": "ACME GmbH",
            "email": "acme@example.de",
            "vat_number": "DE123456789",
            "billing_address": {
                "street_address": "Hauptstraße 1",
                "city": "Berlin",
                "zip_code": "10115",
                "country_code": "DE",
            },
        }
        c.update(overrides)
        return c

    def test_complete_de_client(self):
        assert check_client_completeness(self._base_client(), "IT") == []

    def test_missing_email(self):
        c = self._base_client(email="")
        missing = check_client_completeness(c, "IT")
        assert "email" in missing

    def test_missing_vat_for_eu(self):
        c = self._base_client(vat_number="")
        missing = check_client_completeness(c, "IT")
        assert "vat_number" in missing

    def test_non_eu_client_no_vat_required(self):
        c = self._base_client(vat_number="")
        c["billing_address"]["country_code"] = "US"
        missing = check_client_completeness(c, "IT")
        assert "vat_number" not in missing

    def test_it_client_needs_sdi_fields(self):
        c = self._base_client()
        c["billing_address"]["country_code"] = "IT"
        c["tax_identification_number"] = "RSSMRA80A01H501U"
        c["billing_address"]["province_code"] = "MI"
        c["recipient_code"] = "ABCDEFG"
        assert check_client_completeness(c, "IT") == []

    def test_it_client_missing_recipient_code(self):
        c = self._base_client()
        c["billing_address"]["country_code"] = "IT"
        c["tax_identification_number"] = "RSSMRA80A01H501U"
        c["billing_address"]["province_code"] = "MI"
        missing = check_client_completeness(c, "IT")
        assert "recipient_code or pec_email" in missing

    def test_it_client_pec_satisfies_sdi(self):
        c = self._base_client()
        c["billing_address"]["country_code"] = "IT"
        c["tax_identification_number"] = "RSSMRA80A01H501U"
        c["billing_address"]["province_code"] = "MI"
        c["pec_email"] = "pec@example.it"
        assert "recipient_code or pec_email" not in check_client_completeness(c, "IT")

    def test_missing_name(self):
        c = self._base_client(name="")
        missing = check_client_completeness(c, None)
        assert "name" in missing


class TestLooksLikeClockifyId:
    def test_real_clockify_ids(self):
        assert looks_like_clockify_id("69b195c52916ebf43251c648")
        assert looks_like_clockify_id("68d429bf97cd1377182aed4d")

    def test_uppercase_hex_not_matched_lowercases(self):
        # Clockify ids are always lowercase in practice; we lowercase before matching.
        assert looks_like_clockify_id("69B195C52916EBF43251C648")

    def test_whitespace_trimmed(self):
        assert looks_like_clockify_id("  69b195c52916ebf43251c648  ")

    def test_aliases_not_matched(self):
        assert not looks_like_clockify_id("r005-01")
        assert not looks_like_clockify_id("allsafe")
        assert not looks_like_clockify_id("r001-03")

    def test_wrong_length_not_matched(self):
        assert not looks_like_clockify_id("69b195c5")
        assert not looks_like_clockify_id("69b195c52916ebf43251c6481")

    def test_non_hex_chars_not_matched(self):
        assert not looks_like_clockify_id("69b195c52916ebf43251c64g")
        assert not looks_like_clockify_id("xxxxxxxxxxxxxxxxxxxxxxxx")

    def test_empty_and_none(self):
        assert not looks_like_clockify_id("")
        assert not looks_like_clockify_id(None)


class TestSynthesizeProjectEntry:
    def test_basic_synthesis(self):
        cp = {"name": "r001-03 - ommi.shop", "hourlyRate": {"amount": 8500}}
        entry = synthesize_project_entry(
            clockify_project=cp, org_country="IT", client_country="DE",
        )
        assert entry["alias"] == "r001-03"
        assert entry["name"] == "r001-03 - ommi.shop"
        assert entry["rate_eur_per_hour"] == 85
        assert entry["vat_rate"] == 0
        assert entry["vat_exemption_reason"] == "N3.2"
        assert entry["payment_terms_days"] == 30
        assert entry["rounding_minutes"] == 15

    def test_no_hourly_rate(self):
        cp = {"name": "Test", "hourlyRate": None}
        entry = synthesize_project_entry(
            clockify_project=cp, org_country="IT", client_country="IT",
        )
        assert entry["rate_eur_per_hour"] == 0
        assert entry["vat_rate"] == 22

    def test_rate_already_in_euros(self):
        cp = {"name": "Test", "hourlyRate": {"amount": 85}}
        entry = synthesize_project_entry(
            clockify_project=cp, org_country="DE", client_country="DE",
        )
        assert entry["rate_eur_per_hour"] == 85
        assert entry["vat_rate"] == 19
