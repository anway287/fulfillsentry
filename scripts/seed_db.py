"""
Seed the database with fresh test data.
Useful for resetting state between manual test runs.

Usage:
    python -m scripts.seed_db
    python -m scripts.seed_db --reset   # drops and recreates all data
"""
import argparse
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:test@localhost:5432/fulfillsentry")


def reset_data(conn):
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE shipments, inventory_transactions, order_line_items, orders RESTART IDENTITY CASCADE")
        cur.execute("UPDATE inventory SET quantity_on_hand = CASE sku "
                    "WHEN 'SKU-LAPTOP-001' THEN 50 "
                    "WHEN 'SKU-MOUSE-002'  THEN 200 "
                    "WHEN 'SKU-CHAIR-001'  THEN 15 "
                    "WHEN 'SKU-MUG-001'    THEN 300 "
                    "WHEN 'SKU-SHIRT-S'    THEN 100 "
                    "WHEN 'SKU-SHIRT-M'    THEN 120 "
                    "WHEN 'SKU-HEAVY-001'  THEN 5 "
                    "ELSE quantity_on_hand END, quantity_reserved = 0")
    conn.commit()
    print("Database reset to seed state.")


def show_summary(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM orders")
        print(f"Orders: {cur.fetchone()[0]}")
        cur.execute("SELECT sku, quantity_on_hand, quantity_reserved FROM inventory ORDER BY sku")
        print("\nInventory:")
        for row in cur.fetchall():
            print(f"  {row[0]:<20} on_hand={row[1]:>4}  reserved={row[2]:>4}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Reset all transactional data to seed state")
    args = parser.parse_args()

    conn = psycopg2.connect(DATABASE_URL)
    try:
        if args.reset:
            reset_data(conn)
        show_summary(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
