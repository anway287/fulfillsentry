"""
SQL data integrity tests — the most important test module in FulfillSentry.

These tests validate cross-service consistency: they go directly to the database
and assert that invariants which span multiple microservices are always true.
APIs can return 200 while the database is in an inconsistent state; SQL doesn't lie.
"""
import pytest


class TestFulfillmentIntegrity:
    def test_no_fulfilled_order_without_inventory_decrement(self, db_conn):
        """
        Core invariant: every FULFILLED order must have a matching DECREMENT
        transaction for each of its SKUs.

        Bug this catches: fulfillment status updated to FULFILLED but the inventory
        decrement step was skipped due to an exception or async failure — leading to
        ghost inventory that shows available but has already shipped.
        """
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT o.order_id, li.sku, li.quantity
                FROM orders o
                JOIN order_line_items li ON li.order_id = o.order_id
                LEFT JOIN inventory_transactions t
                  ON t.order_id = o.order_id
                 AND t.sku = li.sku
                 AND t.type = 'DECREMENT'
                WHERE o.status = 'FULFILLED'
                  AND t.transaction_id IS NULL
            """)
            violations = cur.fetchall()

        assert violations == [], (
            f"Found {len(violations)} fulfilled orders with no inventory decrement record.\n"
            f"Violated rows (order_id, sku, quantity): {violations}"
        )

    def test_inventory_on_hand_never_negative(self, db_conn):
        """
        Invariant: quantity_on_hand must always be >= 0.

        Bug this catches: concurrent orders processed simultaneously against the same
        SKU without proper locking, allowing stock to go negative (overselling).
        """
        with db_conn.cursor() as cur:
            cur.execute("SELECT sku, quantity_on_hand FROM inventory WHERE quantity_on_hand < 0")
            negatives = cur.fetchall()

        assert negatives == [], f"Negative inventory detected: {negatives}"

    def test_inventory_reserved_never_exceeds_on_hand(self, db_conn):
        """
        Invariant: quantity_reserved <= quantity_on_hand at all times.

        Bug this catches: double-reservation race condition where two concurrent
        reserve calls both read the same available quantity before either commits.
        """
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT sku, quantity_on_hand, quantity_reserved
                FROM inventory
                WHERE quantity_reserved > quantity_on_hand
            """)
            violations = cur.fetchall()

        assert violations == [], (
            f"Reserved quantity exceeds on-hand for SKUs: {violations}"
        )

    def test_no_orphaned_shipments(self, db_conn):
        """
        Invariant: every shipment record must reference an existing order.

        Bug this catches: manual database operations or failed cascades that leave
        shipment records pointing to deleted/non-existent orders.
        """
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT s.shipment_id, s.order_id
                FROM shipments s
                LEFT JOIN orders o ON o.order_id = s.order_id
                WHERE o.order_id IS NULL
            """)
            orphans = cur.fetchall()

        assert orphans == [], f"Orphaned shipment records found: {orphans}"

    def test_cancelled_orders_have_no_shipments(self, db_conn):
        """
        Invariant: a CANCELLED order must never have a shipment record.

        Bug this catches: race condition where an order is cancelled just as a
        label is being generated, resulting in a shipment for a cancelled order.
        """
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT o.order_id, s.shipment_id
                FROM orders o
                JOIN shipments s ON s.order_id = o.order_id
                WHERE o.status = 'CANCELLED'
            """)
            violations = cur.fetchall()

        assert violations == [], f"Cancelled orders have shipment records: {violations}"

    def test_line_items_reference_valid_skus(self, db_conn):
        """
        Invariant: all order line items must reference SKUs that exist in inventory.

        Bug this catches: SKU was deleted from inventory after orders were already
        placed against it — data integrity constraint missing at application layer.
        """
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT li.order_id, li.sku
                FROM order_line_items li
                LEFT JOIN inventory i ON i.sku = li.sku
                WHERE i.sku IS NULL
            """)
            orphans = cur.fetchall()

        assert orphans == [], f"Line items reference non-existent SKUs: {orphans}"


class TestTransactionAccounting:
    def test_decrement_transaction_quantities_match_order(self, db_conn):
        """
        For fulfilled orders, the sum of DECREMENT transactions per SKU
        must equal the ordered quantity. Not more, not less.
        """
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT li.order_id, li.sku, li.quantity as ordered,
                       COALESCE(SUM(t.quantity), 0) as decremented
                FROM order_line_items li
                JOIN orders o ON o.order_id = li.order_id AND o.status = 'FULFILLED'
                LEFT JOIN inventory_transactions t
                  ON t.order_id = li.order_id AND t.sku = li.sku AND t.type = 'DECREMENT'
                GROUP BY li.order_id, li.sku, li.quantity
                HAVING li.quantity != COALESCE(SUM(t.quantity), 0)
            """)
            mismatches = cur.fetchall()

        assert mismatches == [], (
            f"Decrement quantity mismatch for fulfilled orders: {mismatches}"
        )

    def test_idempotency_keys_are_unique(self, db_conn):
        """No two distinct orders should share the same non-null idempotency_key."""
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT idempotency_key, COUNT(*) as cnt
                FROM orders
                WHERE idempotency_key IS NOT NULL
                GROUP BY idempotency_key
                HAVING COUNT(*) > 1
            """)
            dupes = cur.fetchall()

        assert dupes == [], f"Duplicate idempotency keys found: {dupes}"
