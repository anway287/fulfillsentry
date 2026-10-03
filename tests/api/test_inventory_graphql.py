"""
GraphQL tests for the Inventory Service.
Covers: queries, mutations, schema validation, edge cases.
"""
import pytest
from gql import gql

QUERY_STOCK = gql("""
    query StockLevel($sku: String!) {
        inventory(sku: $sku) {
            sku
            quantityOnHand
            quantityReserved
            quantityAvailable
        }
    }
""")

QUERY_BY_MERCHANT = gql("""
    query MerchantInventory($merchantId: String!) {
        inventoryByMerchant(merchantId: $merchantId) {
            sku
            productName
            quantityOnHand
            quantityAvailable
        }
    }
""")

MUTATE_RESERVE = gql("""
    mutation ReserveStock($sku: String!, $qty: Int!) {
        reserveStock(sku: $sku, quantity: $qty) {
            success
            message
            sku
            quantityReserved
        }
    }
""")

MUTATE_ADJUST = gql("""
    mutation AdjustStock($sku: String!, $delta: Int!) {
        adjustStock(sku: $sku, delta: $delta) {
            sku
            quantityOnHand
            quantityAvailable
        }
    }
""")


class TestInventoryQuery:
    def test_query_known_sku_returns_all_fields(self, gql_client, seeded_sku):
        result = gql_client.execute(QUERY_STOCK, variable_values={"sku": seeded_sku})
        inv = result["inventory"]
        assert inv is not None
        assert inv["sku"] == seeded_sku
        assert inv["quantityOnHand"] >= 0
        assert inv["quantityReserved"] >= 0
        assert inv["quantityAvailable"] >= 0

    def test_quantity_available_equals_on_hand_minus_reserved(self, gql_client, seeded_sku):
        """Core invariant: available = on_hand - reserved."""
        result = gql_client.execute(QUERY_STOCK, variable_values={"sku": seeded_sku})
        inv = result["inventory"]
        assert inv["quantityAvailable"] == inv["quantityOnHand"] - inv["quantityReserved"]

    def test_query_nonexistent_sku_returns_none(self, gql_client):
        """Ghost SKU must return null — not a 500 or empty object."""
        result = gql_client.execute(QUERY_STOCK, variable_values={"sku": "GHOST-SKU-DOES-NOT-EXIST"})
        assert result["inventory"] is None

    def test_query_by_merchant_returns_list(self, gql_client):
        result = gql_client.execute(QUERY_BY_MERCHANT, variable_values={"merchantId": "M001"})
        items = result["inventoryByMerchant"]
        assert isinstance(items, list)
        assert len(items) > 0
        for item in items:
            assert "sku" in item
            assert "quantityOnHand" in item

    def test_query_unknown_merchant_returns_empty_list(self, gql_client):
        result = gql_client.execute(QUERY_BY_MERCHANT, variable_values={"merchantId": "NO-SUCH-MERCHANT"})
        assert result["inventoryByMerchant"] == []


class TestInventoryMutation:
    def test_reserve_stock_decrements_available(self, gql_client, seeded_sku):
        before = gql_client.execute(QUERY_STOCK, variable_values={"sku": seeded_sku})
        avail_before = before["inventory"]["quantityAvailable"]

        result = gql_client.execute(MUTATE_RESERVE, variable_values={"sku": seeded_sku, "qty": 5})
        assert result["reserveStock"]["success"] is True

        after = gql_client.execute(QUERY_STOCK, variable_values={"sku": seeded_sku})
        assert after["inventory"]["quantityAvailable"] == avail_before - 5

    def test_reserve_more_than_available_fails_gracefully(self, gql_client, seeded_sku):
        """Over-reservation must fail with a clear message, not cause negative available."""
        result = gql_client.execute(MUTATE_RESERVE, variable_values={"sku": seeded_sku, "qty": 999999})
        assert result["reserveStock"]["success"] is False
        assert "Insufficient" in result["reserveStock"]["message"]

        # Verify available is still non-negative
        stock = gql_client.execute(QUERY_STOCK, variable_values={"sku": seeded_sku})
        assert stock["inventory"]["quantityAvailable"] >= 0

    def test_reserve_zero_quantity_fails(self, gql_client, seeded_sku):
        """Boundary: reserving 0 units must be rejected."""
        result = gql_client.execute(MUTATE_RESERVE, variable_values={"sku": seeded_sku, "qty": 0})
        assert result["reserveStock"]["success"] is False

    def test_reserve_nonexistent_sku_fails_gracefully(self, gql_client):
        result = gql_client.execute(MUTATE_RESERVE, variable_values={"sku": "PHANTOM-001", "qty": 1})
        assert result["reserveStock"]["success"] is False
        assert "not found" in result["reserveStock"]["message"].lower()

    def test_adjust_stock_increases_on_hand(self, gql_client, seeded_sku):
        before = gql_client.execute(QUERY_STOCK, variable_values={"sku": seeded_sku})
        on_hand_before = before["inventory"]["quantityOnHand"]

        gql_client.execute(MUTATE_ADJUST, variable_values={"sku": seeded_sku, "delta": 10})

        after = gql_client.execute(QUERY_STOCK, variable_values={"sku": seeded_sku})
        assert after["inventory"]["quantityOnHand"] == on_hand_before + 10

        # Restore
        gql_client.execute(MUTATE_ADJUST, variable_values={"sku": seeded_sku, "delta": -10})

    def test_adjust_stock_cannot_go_below_zero(self, gql_client, seeded_sku):
        """Decrement beyond available stock should floor at 0, never go negative."""
        gql_client.execute(MUTATE_ADJUST, variable_values={"sku": seeded_sku, "delta": -999999})
        stock = gql_client.execute(QUERY_STOCK, variable_values={"sku": seeded_sku})
        assert stock["inventory"]["quantityOnHand"] >= 0
