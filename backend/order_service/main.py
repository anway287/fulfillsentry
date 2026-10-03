from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone
import uuid

from .models import (
    CreateOrderRequest, OrderResponse, UpdateOrderStatusRequest,
    FulfillOrderRequest, OrderStatus
)
from .database import get_db

app = FastAPI(title="Order Service", version="1.0.0", description="FulfillSentry Order Management REST API")


@app.get("/health")
def health():
    return {"status": "ok", "service": "order-service"}


@app.post("/orders", status_code=201, response_model=OrderResponse)
def create_order(payload: CreateOrderRequest, db: Session = Depends(get_db)):
    # Idempotency: return existing order if key already used
    if payload.idempotency_key:
        existing = db.execute(
            text("SELECT * FROM orders WHERE idempotency_key = :key"),
            {"key": payload.idempotency_key}
        ).fetchone()
        if existing:
            line_items = db.execute(
                text("SELECT sku, quantity FROM order_line_items WHERE order_id = :oid"),
                {"oid": str(existing.order_id)}
            ).fetchall()
            return _build_response(existing, line_items)

    # Validate merchant exists
    merchant = db.execute(
        text("SELECT merchant_id FROM merchants WHERE merchant_id = :mid"),
        {"mid": payload.merchant_id}
    ).fetchone()
    if not merchant:
        raise HTTPException(status_code=404, detail=f"Merchant '{payload.merchant_id}' not found")

    # Validate all SKUs exist
    for item in payload.line_items:
        sku_row = db.execute(
            text("SELECT sku FROM inventory WHERE sku = :sku"),
            {"sku": item.sku}
        ).fetchone()
        if not sku_row:
            raise HTTPException(status_code=422, detail=f"SKU '{item.sku}' does not exist in inventory")

    order_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    db.execute(text("""
        INSERT INTO orders (order_id, merchant_id, idempotency_key, status, shipping_address, created_at, updated_at)
        VALUES (:oid, :mid, :ikey, 'PENDING', CAST(:addr AS jsonb), :now, :now)
    """), {
        "oid": order_id,
        "mid": payload.merchant_id,
        "ikey": payload.idempotency_key,
        "addr": payload.shipping_address.model_dump_json(),
        "now": now,
    })

    for item in payload.line_items:
        db.execute(text("""
            INSERT INTO order_line_items (line_item_id, order_id, sku, quantity)
            VALUES (:lid, :oid, :sku, :qty)
        """), {"lid": str(uuid.uuid4()), "oid": order_id, "sku": item.sku, "qty": item.quantity})

    db.commit()

    order = db.execute(text("SELECT * FROM orders WHERE order_id = :oid"), {"oid": order_id}).fetchone()
    line_items = db.execute(
        text("SELECT sku, quantity FROM order_line_items WHERE order_id = :oid"),
        {"oid": order_id}
    ).fetchall()
    return _build_response(order, line_items)


@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str, db: Session = Depends(get_db)):
    order = db.execute(text("SELECT * FROM orders WHERE order_id = :oid"), {"oid": order_id}).fetchone()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    line_items = db.execute(
        text("SELECT sku, quantity FROM order_line_items WHERE order_id = :oid"),
        {"oid": order_id}
    ).fetchall()
    return _build_response(order, line_items)


@app.patch("/orders/{order_id}/status", response_model=OrderResponse)
def update_order_status(order_id: str, payload: UpdateOrderStatusRequest, db: Session = Depends(get_db)):
    order = db.execute(text("SELECT * FROM orders WHERE order_id = :oid"), {"oid": order_id}).fetchone()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    now = datetime.now(timezone.utc).isoformat()
    db.execute(text("""
        UPDATE orders SET status = :status, updated_at = :now WHERE order_id = :oid
    """), {"status": payload.status.value, "now": now, "oid": order_id})

    # When fulfilling: record inventory decrement
    if payload.status == OrderStatus.FULFILLED:
        line_items = db.execute(
            text("SELECT sku, quantity FROM order_line_items WHERE order_id = :oid"),
            {"oid": order_id}
        ).fetchall()
        for item in line_items:
            db.execute(text("""
                UPDATE inventory
                SET quantity_on_hand = quantity_on_hand - :qty,
                    quantity_reserved = GREATEST(0, quantity_reserved - :qty),
                    updated_at = :now
                WHERE sku = :sku
            """), {"qty": item.quantity, "now": now, "sku": item.sku})

            db.execute(text("""
                INSERT INTO inventory_transactions (transaction_id, order_id, sku, type, quantity, created_at)
                VALUES (:tid, :oid, :sku, 'DECREMENT', :qty, :now)
            """), {"tid": str(uuid.uuid4()), "oid": order_id, "sku": item.sku, "qty": item.quantity, "now": now})

    db.commit()

    order = db.execute(text("SELECT * FROM orders WHERE order_id = :oid"), {"oid": order_id}).fetchone()
    line_items = db.execute(
        text("SELECT sku, quantity FROM order_line_items WHERE order_id = :oid"),
        {"oid": order_id}
    ).fetchall()
    return _build_response(order, line_items)


@app.delete("/orders/{order_id}", status_code=204)
def cancel_order(order_id: str, db: Session = Depends(get_db)):
    order = db.execute(text("SELECT status FROM orders WHERE order_id = :oid"), {"oid": order_id}).fetchone()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status in ("SHIPPED", "FULFILLED"):
        raise HTTPException(status_code=409, detail="Cannot cancel an order that has already shipped or been fulfilled")

    db.execute(text("UPDATE orders SET status = 'CANCELLED' WHERE order_id = :oid"), {"oid": order_id})
    db.commit()


def _build_response(order, line_items):
    import json
    addr_data = order.shipping_address if isinstance(order.shipping_address, dict) else json.loads(order.shipping_address)
    return {
        "order_id": str(order.order_id),
        "merchant_id": order.merchant_id,
        "status": order.status,
        "line_items": [{"sku": r.sku, "quantity": r.quantity} for r in line_items],
        "shipping_address": addr_data,
        "idempotency_key": order.idempotency_key,
        "created_at": str(order.created_at),
    }
