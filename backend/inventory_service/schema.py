import strawberry
from typing import Optional
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:test@localhost:5432/fulfillsentry")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)


@strawberry.type
class InventoryItem:
    sku: str
    merchant_id: str
    product_name: str
    quantity_on_hand: int
    quantity_reserved: int
    quantity_available: int


@strawberry.type
class ReserveResult:
    success: bool
    message: str
    sku: str
    quantity_reserved: int


@strawberry.type
class Query:
    @strawberry.field
    def inventory(self, sku: str) -> Optional[InventoryItem]:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM inventory WHERE sku = :sku"),
                {"sku": sku}
            ).fetchone()
        if not row:
            return None
        return InventoryItem(
            sku=row.sku,
            merchant_id=row.merchant_id,
            product_name=row.product_name,
            quantity_on_hand=row.quantity_on_hand,
            quantity_reserved=row.quantity_reserved,
            quantity_available=row.quantity_on_hand - row.quantity_reserved,
        )

    @strawberry.field
    def inventory_by_merchant(self, merchant_id: str) -> list[InventoryItem]:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM inventory WHERE merchant_id = :mid ORDER BY sku"),
                {"merchant_id": merchant_id}
            ).fetchall()
        return [
            InventoryItem(
                sku=r.sku,
                merchant_id=r.merchant_id,
                product_name=r.product_name,
                quantity_on_hand=r.quantity_on_hand,
                quantity_reserved=r.quantity_reserved,
                quantity_available=r.quantity_on_hand - r.quantity_reserved,
            )
            for r in rows
        ]


@strawberry.type
class Mutation:
    @strawberry.mutation
    def reserve_stock(self, sku: str, quantity: int) -> ReserveResult:
        if quantity <= 0:
            return ReserveResult(success=False, message="Quantity must be > 0", sku=sku, quantity_reserved=0)

        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT quantity_on_hand, quantity_reserved FROM inventory WHERE sku = :sku FOR UPDATE"),
                {"sku": sku}
            ).fetchone()

            if not row:
                return ReserveResult(success=False, message=f"SKU {sku} not found", sku=sku, quantity_reserved=0)

            available = row.quantity_on_hand - row.quantity_reserved
            if available < quantity:
                return ReserveResult(
                    success=False,
                    message=f"Insufficient stock: requested {quantity}, available {available}",
                    sku=sku,
                    quantity_reserved=row.quantity_reserved,
                )

            conn.execute(
                text("UPDATE inventory SET quantity_reserved = quantity_reserved + :qty WHERE sku = :sku"),
                {"qty": quantity, "sku": sku}
            )
            new_reserved = row.quantity_reserved + quantity

        return ReserveResult(success=True, message="Stock reserved", sku=sku, quantity_reserved=new_reserved)

    @strawberry.mutation
    def adjust_stock(self, sku: str, delta: int) -> Optional[InventoryItem]:
        """Adjust quantity_on_hand by delta (positive = add, negative = remove)."""
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE inventory
                    SET quantity_on_hand = GREATEST(0, quantity_on_hand + :delta)
                    WHERE sku = :sku
                """),
                {"delta": delta, "sku": sku}
            )
            row = conn.execute(text("SELECT * FROM inventory WHERE sku = :sku"), {"sku": sku}).fetchone()

        if not row:
            return None
        return InventoryItem(
            sku=row.sku,
            merchant_id=row.merchant_id,
            product_name=row.product_name,
            quantity_on_hand=row.quantity_on_hand,
            quantity_reserved=row.quantity_reserved,
            quantity_available=row.quantity_on_hand - row.quantity_reserved,
        )


schema = strawberry.Schema(query=Query, mutation=Mutation)
