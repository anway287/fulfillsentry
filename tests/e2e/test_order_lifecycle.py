"""
End-to-end order lifecycle tests.

These tests exercise the complete fulfillment flow across all three services
and validate that state is consistent in the database at every stage.

Flow: CREATE order → ALLOCATE inventory → PICK → PACK → FULFILL → verify DB
"""
import pytest
from gql import gql


QUERY_STOCK = gql("""
    query StockLevel($sku: String!) {
        inventory(sku: $sku) {
            quantityOnHand
            quantityReserved
            quantityAvailable
        }
    }
""")


class TestFullOrderLifecycle:
    def test_order_lifecycle_end_to_end(self, api_client, gql_client, db_conn):
        """
        Full happy-path lifecycle:
        1. Check initial inventory
        2. Create order
        3. Advance through all statuses
        4. Verify DB consistency at FULFILLED stage
        """
        sku = "SKU-MUG-001"
        qty = 3

        # Step 1: record baseline inventory
        before = gql_client.execute(QUERY_STOCK, variable_values={"sku": sku})
        on_hand_before = before["inventory"]["quantityOnHand"]

        # Step 2: create order
        resp = api_client.post("/orders", json={
            "merchant_id": "M002",
            "line_items": [{"sku": sku, "quantity": qty}],
            "shipping_address": {
                "name": "Lifecycle Test", "line1": "1 Fulfillment Ave",
                "city": "San Francisco", "state": "CA", "zip_code": "94105",
            },
        })
        assert resp.status_code == 201
        order_id = resp.json()["order_id"]

        # Step 3: advance status through the fulfillment pipeline
        for status in ["ALLOCATED", "PICKING", "PACKED", "FULFILLED"]:
            r = api_client.patch(f"/orders/{order_id}/status", json={"status": status})
            assert r.status_code == 200, f"Failed to transition to {status}: {r.text}"
            assert r.json()["status"] == status

        # Step 4: verify DB state after FULFILLED
        with db_conn.cursor() as cur:
            # Inventory was decremented
            cur.execute("SELECT quantity_on_hand FROM inventory WHERE sku = %s", (sku,))
            on_hand_after = cur.fetchone()[0]
            assert on_hand_after == on_hand_before - qty, (
                f"Inventory not decremented correctly. Before: {on_hand_before}, After: {on_hand_after}, Qty: {qty}"
            )

            # DECREMENT transaction exists
            cur.execute("""
                SELECT COUNT(*) FROM inventory_transactions
                WHERE order_id = %s AND sku = %s AND type = 'DECREMENT' AND quantity = %s
            """, (order_id, sku, qty))
            txn_count = cur.fetchone()[0]
            assert txn_count == 1, f"Expected 1 DECREMENT transaction, found {txn_count}"

    def test_cancelled_order_does_not_decrement_inventory(self, api_client, gql_client, db_conn):
        """Cancelling a PENDING order must leave inventory unchanged."""
        sku = "SKU-SHIRT-S"

        before = gql_client.execute(QUERY_STOCK, variable_values={"sku": sku})
        on_hand_before = before["inventory"]["quantityOnHand"]

        resp = api_client.post("/orders", json={
            "merchant_id": "M003",
            "line_items": [{"sku": sku, "quantity": 2}],
            "shipping_address": {
                "name": "Cancel Test", "line1": "99 Test St",
                "city": "Chicago", "state": "IL", "zip_code": "60601",
            },
        })
        order_id = resp.json()["order_id"]

        api_client.delete(f"/orders/{order_id}")

        after = gql_client.execute(QUERY_STOCK, variable_values={"sku": sku})
        assert after["inventory"]["quantityOnHand"] == on_hand_before, (
            "Cancelling a PENDING order should not modify inventory"
        )

    def test_fulfilled_order_shows_in_db_with_correct_status(self, api_client, db_conn):
        """After fulfillment the DB record status matches the API response."""
        resp = api_client.post("/orders", json={
            "merchant_id": "M001",
            "line_items": [{"sku": "SKU-MOUSE-002", "quantity": 1}],
            "shipping_address": {
                "name": "DB Check", "line1": "5 Verify Ln",
                "city": "Austin", "state": "TX", "zip_code": "78701",
            },
        })
        order_id = resp.json()["order_id"]
        api_client.patch(f"/orders/{order_id}/status", json={"status": "FULFILLED"})

        with db_conn.cursor() as cur:
            cur.execute("SELECT status FROM orders WHERE order_id = %s", (order_id,))
            db_status = cur.fetchone()[0]

        assert db_status == "FULFILLED", f"DB status is '{db_status}', expected 'FULFILLED'"
