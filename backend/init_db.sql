-- FulfillSentry database schema
-- Run once on startup; docker-compose entrypoint handles this automatically

CREATE TABLE IF NOT EXISTS merchants (
    merchant_id   VARCHAR(50)  PRIMARY KEY,
    name          VARCHAR(255) NOT NULL,
    created_at    TIMESTAMPTZ  DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inventory (
    sku                  VARCHAR(100) PRIMARY KEY,
    merchant_id          VARCHAR(50)  REFERENCES merchants(merchant_id),
    product_name         VARCHAR(255) NOT NULL,
    quantity_on_hand     INT          NOT NULL DEFAULT 0,
    quantity_reserved    INT          NOT NULL DEFAULT 0,
    weight_lbs           NUMERIC(8,2) NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ  DEFAULT now(),
    CONSTRAINT chk_non_negative_on_hand     CHECK (quantity_on_hand >= 0),
    CONSTRAINT chk_non_negative_reserved    CHECK (quantity_reserved >= 0)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id      VARCHAR(50)  REFERENCES merchants(merchant_id),
    idempotency_key  VARCHAR(255) UNIQUE,
    status           VARCHAR(50)  NOT NULL DEFAULT 'PENDING',
    shipping_address JSONB        NOT NULL,
    created_at       TIMESTAMPTZ  DEFAULT now(),
    updated_at       TIMESTAMPTZ  DEFAULT now(),
    CONSTRAINT chk_order_status CHECK (status IN ('PENDING','ALLOCATED','PICKING','PACKED','SHIPPED','FULFILLED','CANCELLED'))
);

CREATE TABLE IF NOT EXISTS order_line_items (
    line_item_id  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id      UUID         REFERENCES orders(order_id) ON DELETE CASCADE,
    sku           VARCHAR(100) REFERENCES inventory(sku),
    quantity      INT          NOT NULL,
    CONSTRAINT chk_positive_quantity CHECK (quantity > 0)
);

CREATE TABLE IF NOT EXISTS inventory_transactions (
    transaction_id  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID         REFERENCES orders(order_id),
    sku             VARCHAR(100) REFERENCES inventory(sku),
    type            VARCHAR(20)  NOT NULL,
    quantity        INT          NOT NULL,
    created_at      TIMESTAMPTZ  DEFAULT now(),
    CONSTRAINT chk_txn_type CHECK (type IN ('RESERVE','DECREMENT','RELEASE','ADJUSTMENT'))
);

CREATE TABLE IF NOT EXISTS shipments (
    shipment_id      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id         UUID         REFERENCES orders(order_id),
    carrier          VARCHAR(100),
    tracking_number  VARCHAR(255),
    label_url        TEXT,
    created_at       TIMESTAMPTZ  DEFAULT now()
);

-- Seed data
INSERT INTO merchants (merchant_id, name) VALUES
    ('M001', 'TechGear Direct'),
    ('M002', 'HomeGoods Co'),
    ('M003', 'AppareLoop')
ON CONFLICT DO NOTHING;

INSERT INTO inventory (sku, merchant_id, product_name, quantity_on_hand, weight_lbs) VALUES
    ('SKU-LAPTOP-001', 'M001', 'Laptop 15"',          50, 4.5),
    ('SKU-MOUSE-002',  'M001', 'Wireless Mouse',      200, 0.4),
    ('SKU-CHAIR-001',  'M002', 'Ergonomic Chair',     15, 32.0),
    ('SKU-MUG-001',    'M002', 'Ceramic Mug Set',     300, 2.2),
    ('SKU-SHIRT-S',    'M003', 'Classic Tee - Small', 100, 0.5),
    ('SKU-SHIRT-M',    'M003', 'Classic Tee - Medium',120, 0.5),
    ('SKU-HEAVY-001',  'M001', 'Server Rack Unit',    5,  72.0)
ON CONFLICT DO NOTHING;
