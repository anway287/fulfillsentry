"""
Boundary and negative test cases.
Many of these were generated with the AI edge case generator (ai_tools/edge_case_generator.py)
and then validated manually. Shows the value of AI-assisted QA coverage.
"""
import pytest
import string


VALID_ADDRESS = {
    "name": "Test User", "line1": "1 Main St",
    "city": "San Francisco", "state": "CA", "zip_code": "94105",
}


class TestOrderPayloadBoundaries:
    @pytest.mark.parametrize("merchant_id,expected_status", [
        ("",        422),   # empty string
        ("M001",    201),   # valid
        ("M" * 51, 422),   # too long (max 50 chars)
    ])
    def test_merchant_id_boundaries(self, api_client, merchant_id, expected_status):
        payload = {
            "merchant_id": merchant_id,
            "line_items": [{"sku": "SKU-MOUSE-002", "quantity": 1}],
            "shipping_address": VALID_ADDRESS,
        }
        assert api_client.post("/orders", json=payload).status_code == expected_status

    @pytest.mark.parametrize("quantity,expected_status", [
        (-100,  422),  # very negative
        (-1,    422),  # negative
        (0,     422),  # zero — boundary
        (1,     201),  # minimum valid — boundary
        (100,   201),  # large valid quantity
    ])
    def test_line_item_quantity_boundaries(self, api_client, quantity, expected_status):
        payload = {
            "merchant_id": "M001",
            "line_items": [{"sku": "SKU-MOUSE-002", "quantity": quantity}],
            "shipping_address": VALID_ADDRESS,
        }
        assert api_client.post("/orders", json=payload).status_code == expected_status

    @pytest.mark.parametrize("zip_code,expected_status", [
        ("94105",      201),   # valid 5-digit
        ("94105-1234", 201),   # valid 9-digit (ZIP+4)
        ("9410",       422),   # too short
        ("941055",     422),   # 6 digits — invalid
        ("BADZIP",     422),   # non-numeric
        ("",           422),   # empty
        ("00000",      201),   # valid format — service decides if serviceable
    ])
    def test_zip_code_format_boundaries(self, api_client, zip_code, expected_status):
        addr = {**VALID_ADDRESS, "zip_code": zip_code}
        payload = {
            "merchant_id": "M001",
            "line_items": [{"sku": "SKU-MOUSE-002", "quantity": 1}],
            "shipping_address": addr,
        }
        assert api_client.post("/orders", json=payload).status_code == expected_status

    @pytest.mark.parametrize("state,expected_status", [
        ("CA",          201),   # valid 2-char
        ("C",           422),   # too short
        ("California",  422),   # too long — full state name
        ("",            422),   # empty
        ("ca",          201),   # lowercase — service may normalize
    ])
    def test_state_code_boundaries(self, api_client, state, expected_status):
        addr = {**VALID_ADDRESS, "state": state}
        payload = {
            "merchant_id": "M001",
            "line_items": [{"sku": "SKU-MOUSE-002", "quantity": 1}],
            "shipping_address": addr,
        }
        resp = api_client.post("/orders", json=payload)
        assert resp.status_code == expected_status


class TestSecurityBoundaries:
    def test_sql_injection_in_merchant_id_rejected(self, api_client):
        """SQL injection attempt must not crash the service or leak data."""
        payload = {
            "merchant_id": "'; DROP TABLE orders; --",
            "line_items": [{"sku": "SKU-MOUSE-002", "quantity": 1}],
            "shipping_address": VALID_ADDRESS,
        }
        resp = api_client.post("/orders", json=payload)
        # Must return 4xx, not 500 (which would indicate unhandled query injection)
        assert resp.status_code in (404, 422), (
            f"SQL injection payload returned unexpected status {resp.status_code}"
        )

    def test_xss_payload_in_address_name_is_stored_safely(self, api_client):
        """XSS payload must be stored as-is (escaped), not executed."""
        addr = {**VALID_ADDRESS, "name": "<script>alert('xss')</script>"}
        payload = {
            "merchant_id": "M001",
            "line_items": [{"sku": "SKU-MOUSE-002", "quantity": 1}],
            "shipping_address": addr,
        }
        resp = api_client.post("/orders", json=payload)
        # Either accepted and stored safely, or rejected by validation
        assert resp.status_code in (201, 422)
        if resp.status_code == 201:
            # Verify the raw string is stored, not evaluated
            assert "<script>" in resp.json()["shipping_address"]["name"]

    def test_oversized_payload_does_not_crash_service(self, api_client):
        """Sending a very large payload should return 4xx, not 500."""
        payload = {
            "merchant_id": "M001",
            "line_items": [{"sku": "SKU-MOUSE-002", "quantity": 1}],
            "shipping_address": {**VALID_ADDRESS, "line1": "A" * 10000},
        }
        resp = api_client.post("/orders", json=payload)
        assert resp.status_code in (422, 413), f"Oversized payload returned {resp.status_code}"


class TestEmptyAndNullCases:
    def test_empty_line_items_array_rejected(self, api_client):
        payload = {
            "merchant_id": "M001",
            "line_items": [],
            "shipping_address": VALID_ADDRESS,
        }
        assert api_client.post("/orders", json=payload).status_code == 422

    def test_null_body_returns_422(self, api_client):
        resp = api_client.post("/orders", json=None)
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, api_client):
        resp = api_client.post("/orders", json={})
        assert resp.status_code == 422

    def test_completely_missing_shipping_address_rejected(self, api_client):
        payload = {
            "merchant_id": "M001",
            "line_items": [{"sku": "SKU-MOUSE-002", "quantity": 1}],
        }
        assert api_client.post("/orders", json=payload).status_code == 422
