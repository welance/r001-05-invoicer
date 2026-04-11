"""Unit tests for Qonto payload builders.

These are pure functions — no HTTP, no I/O. They're the last line of defense
against malformed invoice JSON reaching Qonto's API.
"""

import pytest

from invoicer.qonto import (
    build_client_payload,
    build_invoice_item,
    build_invoice_payload,
)


class TestBuildClientPayload:
    def _base_fields(self, **overrides):
        fields = {
            "name": "ACME GmbH",
            "country_code": "DE",
            "vat_number": "DE123456789",
            "street_address": "Hauptstraße 1",
            "city": "Berlin",
            "zip_code": "10115",
        }
        fields.update(overrides)
        return fields

    def test_minimum_required_fields(self):
        payload = build_client_payload(self._base_fields())
        assert payload["kind"] == "company"
        assert payload["name"] == "ACME GmbH"
        assert payload["currency"] == "EUR"
        assert payload["billing_address"]["country_code"] == "DE"

    def test_german_client_no_sdi_fields(self):
        payload = build_client_payload(
            self._base_fields(
                province_code="MI",  # should be ignored for non-IT
                recipient_code="1234567",  # should be ignored for non-IT
            )
        )
        assert "recipient_code" not in payload
        assert "province_code" not in payload["billing_address"]

    def test_italian_client_with_recipient_code(self):
        payload = build_client_payload(
            self._base_fields(
                country_code="IT",
                vat_number="IT12345678901",
                street_address="Via Roma 10",
                city="Milano",
                zip_code="20100",
                province_code="MI",
                recipient_code="ABCDEFG",
            )
        )
        assert payload["recipient_code"] == "ABCDEFG"
        assert payload["billing_address"]["province_code"] == "MI"

    def test_italian_pec_fallback_to_zeros(self):
        """PEC-only Italian clients use recipient_code '0000000' convention."""
        payload = build_client_payload(
            self._base_fields(
                country_code="IT",
                zip_code="20100",
                pec_email="pec@example.it",
                recipient_code="",
            )
        )
        assert payload["recipient_code"] == "0000000"

    def test_country_code_uppercased(self):
        payload = build_client_payload(self._base_fields(country_code="de"))
        assert payload["billing_address"]["country_code"] == "DE"

    def test_custom_locale(self):
        payload = build_client_payload(self._base_fields(), locale="it")
        assert payload["locale"] == "it"

    def test_email_included_when_present(self):
        payload = build_client_payload(
            self._base_fields(email="contact@acme.de")
        )
        assert payload["email"] == "contact@acme.de"

    def test_empty_email_excluded(self):
        payload = build_client_payload(self._base_fields(email=""))
        assert "email" not in payload

    def test_missing_vat_number_not_included(self):
        payload = build_client_payload(self._base_fields(vat_number=""))
        assert "vat_number" not in payload


class TestBuildInvoiceItem:
    def test_basic_item(self):
        item = build_invoice_item(
            title="Consulting",
            description="March 2026 — 10h",
            quantity=10,
            unit_price_eur=85,
            vat_rate_pct=22,
            vat_exemption_reason=None,
        )
        assert item["title"] == "Consulting"
        assert item["quantity"] == "10.00"
        assert item["unit"] == "hour"
        assert item["unit_price"] == {"value": "85.00", "currency": "EUR"}
        assert item["vat_rate"] == "22.00"
        assert "vat_exemption_reason" not in item

    def test_zero_vat_requires_exemption_reason(self):
        item = build_invoice_item(
            title="Consulting",
            description="reverse charge",
            quantity=1,
            unit_price_eur=100,
            vat_rate_pct=0,
            vat_exemption_reason="N3.2",
        )
        assert item["vat_exemption_reason"] == "N3.2"

    def test_zero_vat_without_reason_still_builds(self):
        # The CLI won't normally do this, but the builder shouldn't crash.
        item = build_invoice_item(
            title="Consulting",
            description="x",
            quantity=1,
            unit_price_eur=100,
            vat_rate_pct=0,
            vat_exemption_reason=None,
        )
        assert "vat_exemption_reason" not in item

    def test_title_truncated_to_250(self):
        long = "x" * 500
        item = build_invoice_item(
            title=long,
            description="y",
            quantity=1,
            unit_price_eur=10,
            vat_rate_pct=0,
            vat_exemption_reason="N3.2",
        )
        assert len(item["title"]) == 250

    def test_fractional_quantity(self):
        item = build_invoice_item(
            title="Consulting",
            description="x",
            quantity=23.25,
            unit_price_eur=85,
            vat_rate_pct=0,
            vat_exemption_reason="N3.2",
        )
        assert item["quantity"] == "23.25"


class TestBuildInvoicePayload:
    def _minimal_item(self):
        return build_invoice_item(
            title="t",
            description="d",
            quantity=1,
            unit_price_eur=100,
            vat_rate_pct=0,
            vat_exemption_reason="N3.2",
        )

    def test_contains_required_top_level_fields(self):
        payload = build_invoice_payload(
            client_id="cli_xyz",
            issue_date="2026-04-01",
            due_date="2026-05-01",
            items=[self._minimal_item()],
            iban="IT60X0542811101000000123456",
            bic="BANKIT22",
            beneficiary_name="ACME SRL",
        )
        assert payload["client_id"] == "cli_xyz"
        assert payload["issue_date"] == "2026-04-01"
        assert payload["due_date"] == "2026-05-01"
        assert payload["currency"] == "EUR"
        assert payload["status"] == "draft"
        assert len(payload["items"]) == 1

    def test_payment_methods_is_single_object_not_array(self):
        """Qonto's POST accepts a single object for payment_methods, not an array."""
        payload = build_invoice_payload(
            client_id="c",
            issue_date="2026-04-01",
            due_date="2026-05-01",
            items=[self._minimal_item()],
            iban="IT60X0542811101000000123456",
            bic="BANKIT22",
            beneficiary_name="ACME SRL",
        )
        pm = payload["payment_methods"]
        assert isinstance(pm, dict)
        assert pm["type"] == "transfer"
        assert pm["iban"] == "IT60X0542811101000000123456"
        assert pm["bic"] == "BANKIT22"
        assert pm["beneficiary_name"] == "ACME SRL"

    def test_payment_reporting_for_italy(self):
        payload = build_invoice_payload(
            client_id="c",
            issue_date="2026-04-01",
            due_date="2026-05-01",
            items=[self._minimal_item()],
            iban="IT60X0542811101000000123456",
        )
        assert payload["payment_reporting"] == {
            "conditions": "TP02",
            "method": "MP05",
        }

    def test_purchase_order_optional(self):
        payload = build_invoice_payload(
            client_id="c",
            issue_date="2026-04-01",
            due_date="2026-05-01",
            items=[self._minimal_item()],
            iban="IT60X0542811101000000123456",
            purchase_order="Attn: Jane",
        )
        assert payload["purchase_order"] == "Attn: Jane"

    def test_purchase_order_omitted_when_none(self):
        payload = build_invoice_payload(
            client_id="c",
            issue_date="2026-04-01",
            due_date="2026-05-01",
            items=[self._minimal_item()],
            iban="IT60X0542811101000000123456",
        )
        assert "purchase_order" not in payload

    def test_status_defaults_to_draft(self):
        payload = build_invoice_payload(
            client_id="c",
            issue_date="2026-04-01",
            due_date="2026-05-01",
            items=[self._minimal_item()],
            iban="IT60X0542811101000000123456",
        )
        assert payload["status"] == "draft"


class TestBuildInvoicePayloadRegressions:
    """Regression tests for bugs we actually hit during development."""

    def test_payment_field_is_named_payment_methods_not_payment(self):
        """We initially wrote 'payment' which Qonto rejected. Must be 'payment_methods'."""
        payload = build_invoice_payload(
            client_id="c",
            issue_date="2026-04-01",
            due_date="2026-05-01",
            items=[
                build_invoice_item(
                    title="t",
                    description="d",
                    quantity=1,
                    unit_price_eur=100,
                    vat_rate_pct=0,
                    vat_exemption_reason="N3.2",
                )
            ],
            iban="IT60X0542811101000000123456",
        )
        assert "payment_methods" in payload
        assert "payment" not in payload  # 'payment' was the wrong name

    def test_zero_vat_item_must_have_exemption_reason(self):
        """Qonto 422s Italian orgs when a 0% VAT line has no exemption_reason."""
        item = build_invoice_item(
            title="t",
            description="d",
            quantity=1,
            unit_price_eur=100,
            vat_rate_pct=0,
            vat_exemption_reason="N3.2",
        )
        # The item must declare vat_rate=0 AND vat_exemption_reason
        assert item["vat_rate"] == "0.00"
        assert item["vat_exemption_reason"] == "N3.2"

    @pytest.mark.parametrize(
        "exemption",
        ["N2.1", "N3.2", "N6.7"],
    )
    def test_common_italian_sdi_exemption_codes_accepted(self, exemption):
        """The builder doesn't validate the code itself — it just passes it through."""
        item = build_invoice_item(
            title="t",
            description="d",
            quantity=1,
            unit_price_eur=100,
            vat_rate_pct=0,
            vat_exemption_reason=exemption,
        )
        assert item["vat_exemption_reason"] == exemption
