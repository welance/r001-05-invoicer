"""Unit tests for SDI code glosses — pure table lookup + invoice field extraction."""

from invoicer.sdi_glosses import (
    GLOSSES,
    extract_client_country,
    extract_sdi_code,
    get_gloss,
)


class TestGetGloss:
    def test_exact_match_de(self):
        result = get_gloss("N3.2", "DE")
        assert result is not None
        assert "Steuerfreie" in result
        assert "N3.2" in result

    def test_exact_match_it(self):
        result = get_gloss("N3.2", "IT")
        assert result is not None
        assert "non imponibili" in result

    def test_fallback_to_english_on_unknown_country(self):
        result = get_gloss("N3.2", "NL")
        assert result is not None
        assert "intra-Community" in result

    def test_fallback_to_english_on_none_country(self):
        result = get_gloss("N3.2", None)
        assert result is not None
        assert "intra-Community" in result

    def test_fallback_to_english_on_empty_country(self):
        result = get_gloss("N3.2", "")
        assert result is not None

    def test_country_case_insensitive(self):
        result = get_gloss("N3.2", "de")
        assert result is not None
        assert "Steuerfreie" in result

    def test_none_code_returns_none(self):
        assert get_gloss(None, "DE") is None

    def test_empty_code_returns_none(self):
        assert get_gloss("", "DE") is None
        assert get_gloss("   ", "DE") is None

    def test_unknown_code_returns_none(self):
        assert get_gloss("N99.99", "DE") is None

    def test_n31_has_english_fallback(self):
        result = get_gloss("N3.1", "US")
        assert result is not None
        assert "non-taxable export" in result

    def test_n67_has_english_fallback(self):
        result = get_gloss("N6.7", "DE")
        assert result is not None
        assert "reverse-charge" in result

    def test_code_is_trimmed(self):
        assert get_gloss("  N3.2  ", "DE") is not None


class TestGlossTableConsistency:
    def test_every_code_has_english_fallback(self):
        """Every distinct code in the table must have an 'EN' entry so
        unknown-country lookups always resolve."""
        codes = {code for code, _ in GLOSSES}
        for code in codes:
            assert (code, "EN") in GLOSSES, (
                f"Code {code!r} has localized entries but no EN fallback"
            )

    def test_every_gloss_mentions_its_code(self):
        """Sanity: the gloss should reference the code it explains so
        the reader can tie the paragraph to the invoice line."""
        for (code, _country), text in GLOSSES.items():
            assert code in text, (
                f"Gloss for {code!r} does not mention the code in its text"
            )


class TestExtractSdiCode:
    def test_returns_first_non_empty(self):
        inv = {
            "items": [
                {"vat_exemption_reason": ""},
                {"vat_exemption_reason": "N3.2"},
                {"vat_exemption_reason": "N3.1"},
            ]
        }
        assert extract_sdi_code(inv) == "N3.2"

    def test_no_items(self):
        assert extract_sdi_code({}) is None
        assert extract_sdi_code({"items": []}) is None
        assert extract_sdi_code({"items": None}) is None

    def test_all_items_exempt_empty(self):
        inv = {"items": [{"vat_exemption_reason": ""}, {"vat_exemption_reason": None}]}
        assert extract_sdi_code(inv) is None

    def test_missing_key_on_item(self):
        inv = {"items": [{"title": "consulting"}]}
        assert extract_sdi_code(inv) is None


class TestExtractClientCountry:
    def test_direct_country_code(self):
        inv = {"client": {"country_code": "DE"}}
        assert extract_client_country(inv) == "DE"

    def test_nested_in_billing_address(self):
        inv = {"client": {"billing_address": {"country_code": "DE"}}}
        assert extract_client_country(inv) == "DE"

    def test_direct_takes_priority(self):
        inv = {
            "client": {
                "country_code": "IT",
                "billing_address": {"country_code": "DE"},
            }
        }
        assert extract_client_country(inv) == "IT"

    def test_uppercased(self):
        inv = {"client": {"country_code": "de"}}
        assert extract_client_country(inv) == "DE"

    def test_missing_client(self):
        assert extract_client_country({}) is None

    def test_empty_client(self):
        assert extract_client_country({"client": {}}) is None

    def test_empty_strings_return_none(self):
        inv = {"client": {"country_code": "", "billing_address": {"country_code": ""}}}
        assert extract_client_country(inv) is None
