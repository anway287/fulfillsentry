"""
Shared fixtures for the FulfillSentry test suite.
All services must be running (docker compose up -d) before running tests.
"""
import os
import pytest
import requests
import psycopg2
from gql import Client
from gql.transport.requests import RequestsHTTPTransport
from dotenv import load_dotenv

load_dotenv()

ORDER_SERVICE_URL    = os.getenv("ORDER_SERVICE_URL",    "http://localhost:8001")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8002")
DATABASE_URL          = os.getenv("DATABASE_URL",          "postgresql://postgres:test@localhost:5432/fulfillsentry")
CARRIER_HOST          = os.getenv("CARRIER_SERVICE_HOST",  "localhost:50051")


# ─── HTTP clients ────────────────────────────────────────────────────────────

class APIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def get(self, path, **kwargs):
        return self.session.get(f"{self.base_url}{path}", **kwargs)

    def post(self, path, **kwargs):
        return self.session.post(f"{self.base_url}{path}", **kwargs)

    def patch(self, path, **kwargs):
        return self.session.patch(f"{self.base_url}{path}", **kwargs)

    def delete(self, path, **kwargs):
        return self.session.delete(f"{self.base_url}{path}", **kwargs)


@pytest.fixture(scope="session")
def api_client():
    return APIClient(ORDER_SERVICE_URL)


@pytest.fixture(scope="session")
def gql_client():
    transport = RequestsHTTPTransport(
        url=f"{INVENTORY_SERVICE_URL}/graphql",
        verify=True,
        retries=3,
    )
    return Client(transport=transport, fetch_schema_from_transport=True)


# ─── Database ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def db_conn():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(autouse=False)
def clean_test_orders(db_conn):
    """Delete orders created during a test (those with 'TEST-' in idempotency_key)."""
    yield
    with db_conn.cursor() as cur:
        cur.execute("""
            DELETE FROM orders WHERE idempotency_key LIKE 'TEST-%'
               OR merchant_id = 'TEST-MERCHANT'
        """)


# ─── Common payloads ─────────────────────────────────────────────────────────

@pytest.fixture
def valid_order_payload():
    return {
        "merchant_id": "M001",
        "line_items": [{"sku": "SKU-LAPTOP-001", "quantity": 1}],
        "shipping_address": {
            "name": "Jane Smith",
            "line1": "123 Test Ave",
            "city": "San Francisco",
            "state": "CA",
            "zip_code": "94105",
            "country": "US",
        },
    }


@pytest.fixture
def seeded_sku():
    return "SKU-MOUSE-002"


# ─── gRPC stub ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def grpc_stub():
    import sys
    import grpc
    stub_path = os.path.join(os.path.dirname(__file__), "..", "backend", "carrier_service", "generated")
    sys.path.insert(0, stub_path)
    import carrier_pb2_grpc
    channel = grpc.insecure_channel(CARRIER_HOST)
    return carrier_pb2_grpc.CarrierServiceStub(channel)
