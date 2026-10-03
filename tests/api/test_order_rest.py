"""
REST API tests for the Order Service.
Covers: happy path, validation, negative cases, boundary values, idempotency.
"""
import pytest
import uuid


class TestOrderCreation:
    def test_create_order_happy_path(self, api_client, valid_order_payload):
        """201 response with correct schema and PENDING status."""
        resp = api_client.post("/orders", json=valid_order_payload)
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "PENDING"
        assert "order_id" in body
        assert body["merchant_id"] == valid_order_payload["merchant_id"]
        assert len(body["line_items"]) == 1
        assert body["line_items"][0]["sku"] == "SKU-LAPTOP-001"

    def test_create_order_missing_line_items_returns_422(self, api_client):
        payload = {
            "merchant_id": "M001",
            "shipping_address": {
                "name": "Test User", "line1": "1 Main St",
                "city": "SF", "state": "CA", "zip_code": "94105",
            },
        }
        resp = api_client.post("/orders", json=payload)
        assert resp.status_code == 422

    def test_create_order_missing_merchant_id_returns_422(self, api_client, valid_order_payload):
        payload = {**valid_order_payload}
        del payload["merchant_id"]
        assert api_client.post("/orders", json=payload).status_code == 422

    def test_create_order_unknown_merchant_returns_404(self, api_client, valid_order_payload):
        payload = {**valid_order_payload, "merchant_id": "GHOST-MERCHANT"}
        assert api_client.post("/orders", json=payload).status_code == 404

    def test_create_order_unknown_sku_returns_422(self, api_client, valid_order_payload):
        payload = {**valid_order_payload, "line_items": [{"sku": "DOES-NOT-EXIST", "quantity": 1}]}
        assert api_client.post("/orders", json=payload).status_code == 422

    def test_create_order_quantity_zero_rejected(self, api_client, valid_order_payload):
        """Boundary: quantity 0 must be rejected — not silently accepted."""
        payload = {**valid_order_payload, "line_items": [{"sku": "SKU-LAPTOP-001", "quantity": 0}]}
        assert api_client.post("/orders", json=payload).status_code == 422

    def test_create_order_quantity_negative_rejected(self, api_client, valid_order_payload):
        """Boundary: negative quantity must never create an order."""
        payload = {**valid_order_payload, "line_items": [{"sku": "SKU-LAPTOP-001", "quantity": -5}]}
        assert api_client.post("/orders", json=payload).status_code == 422

    def test_create_order_quantity_one_accepted(self, api_client, valid_order_payload):
        """Boundary: quantity exactly 1 is valid."""
        payload = {**valid_order_payload, "line_items": [{"sku": "SKU-MOUSE-002", "quantity": 1}]}
        assert api_client.post("/orders", json=payload).status_code == 201

    def test_create_order_invalid_zip_code_rejected(self, api_client, valid_order_payload):
        addr = {**valid_order_payload["shipping_address"], "zip_code": "BADZIP"}
        payload = {**valid_order_payload, "shipping_address": addr}
        assert api_client.post("/orders", json=payload).status_code == 422

    def test_create_order_invalid_state_too_long_rejected(self, api_client, valid_order_payload):
        addr = {**valid_order_payload["shipping_address"], "state": "California"}
        payload = {**valid_order_payload, "shipping_address": addr}
        assert api_client.post("/orders", json=payload).status_code == 422

    def test_create_order_duplicate_skus_rejected(self, api_client, valid_order_payload):
        """A single order cannot contain the same SKU twice — use quantity instead."""
        payload = {
            **valid_order_payload,
            "line_items": [
                {"sku": "SKU-LAPTOP-001", "quantity": 1},
                {"sku": "SKU-LAPTOP-001", "quantity": 2},
            ],
        }
        assert api_client.post("/orders", json=payload).status_code == 422

    def test_create_order_multi_line_items(self, api_client, valid_order_payload):
        payload = {
            **valid_order_payload,
            "line_items": [
                {"sku": "SKU-LAPTOP-001", "quantity": 1},
                {"sku": "SKU-MOUSE-002",  "quantity": 2},
            ],
        }
        resp = api_client.post("/orders", json=payload)
        assert resp.status_code == 201
        assert len(resp.json()["line_items"]) == 2


class TestIdempotency:
    def test_idempotency_key_returns_same_order(self, api_client, valid_order_payload):
        """Submitting the same order twice with an idempotency key must return the same order_id."""
        ikey = f"TEST-IDEM-{uuid.uuid4().hex[:8]}"
        payload = {**valid_order_payload, "idempotency_key": ikey}
        r1 = api_client.post("/orders", json=payload)
        r2 = api_client.post("/orders", json=payload)
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["order_id"] == r2.json()["order_id"], (
            "Idempotency violated: two calls with same key created two different orders"
        )

    def test_no_idempotency_key_creates_two_orders(self, api_client, valid_order_payload):
        """Without a key, two calls create two separate orders."""
        r1 = api_client.post("/orders", json=valid_order_payload)
        r2 = api_client.post("/orders", json=valid_order_payload)
        assert r1.json()["order_id"] != r2.json()["order_id"]


class TestOrderRetrieval:
    def test_get_order_returns_correct_data(self, api_client, valid_order_payload):
        created = api_client.post("/orders", json=valid_order_payload).json()
        fetched = api_client.get(f"/orders/{created['order_id']}").json()
        assert fetched["order_id"] == created["order_id"]
        assert fetched["status"] == "PENDING"

    def test_get_nonexistent_order_returns_404(self, api_client):
        assert api_client.get(f"/orders/{uuid.uuid4()}").status_code == 404

    def test_get_order_invalid_uuid_returns_404(self, api_client):
        assert api_client.get("/orders/not-a-real-id").status_code in (404, 422)


class TestOrderStatusTransitions:
    def test_update_status_to_allocated(self, api_client, valid_order_payload):
        order_id = api_client.post("/orders", json=valid_order_payload).json()["order_id"]
        resp = api_client.patch(f"/orders/{order_id}/status", json={"status": "ALLOCATED"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ALLOCATED"

    def test_cancel_pending_order(self, api_client, valid_order_payload):
        order_id = api_client.post("/orders", json=valid_order_payload).json()["order_id"]
        resp = api_client.delete(f"/orders/{order_id}")
        assert resp.status_code == 204

    def test_cannot_cancel_fulfilled_order(self, api_client, valid_order_payload):
        order_id = api_client.post("/orders", json=valid_order_payload).json()["order_id"]
        api_client.patch(f"/orders/{order_id}/status", json={"status": "FULFILLED"})
        resp = api_client.delete(f"/orders/{order_id}")
        assert resp.status_code == 409

    def test_invalid_status_value_rejected(self, api_client, valid_order_payload):
        order_id = api_client.post("/orders", json=valid_order_payload).json()["order_id"]
        resp = api_client.patch(f"/orders/{order_id}/status", json={"status": "FLYING"})
        assert resp.status_code == 422
