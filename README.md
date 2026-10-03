# FulfillSentry 🧪

A comprehensive QA automation framework for e-commerce fulfillment microservices — covering REST, GraphQL, gRPC, SQL data integrity, CI/CD, and AI-assisted test generation.

[![CI](https://github.com/anway287/fulfillsentry/actions/workflows/ci.yml/badge.svg)](https://github.com/anway287/fulfillsentry/actions/workflows/ci.yml)

---

## The Problem

E-commerce fulfillment platforms are hard to test well. An order doesn't live in one service — it's ingested through a REST API, inventory is queried through GraphQL, the carrier is selected through a gRPC service, and the final state must be consistent across all of them in the database.

The most dangerous bugs aren't in individual services. They're in the **data flowing between services**: a fulfilled order with no inventory decrement, a carrier returning wrong rates for heavy packages, an idempotency key that doesn't prevent duplicate orders.

FulfillSentry tests all of that.

---

## Architecture

```
┌─ MERCHANTS / SHOPIFY ────────────────────────────────────────────┐
│  (order events come in here)                                      │
└────────────────────────────┬─────────────────────────────────────┘
                             │
        ┌────────────────────▼──────────────────────┐
        │       ORDER SERVICE  (REST / FastAPI)      │
        │  POST /orders   GET /orders/{id}   PATCH   │
        └──────────────┬────────────────┬────────────┘
                       │                │
        ┌──────────────▼──┐    ┌────────▼────────────────┐
        │  INVENTORY SVC   │    │   CARRIER SERVICE        │
        │   (GraphQL)      │    │   (gRPC / Protobuf)      │
        │  query stock     │    │  RateShop / GenLabel     │
        └──────┬───────────┘    └────────┬────────────────┘
               │                         │
        ───────▼─────────────────────────▼──────────
        │          PostgreSQL (shared data store)    │
        │   orders · inventory · shipments · txns    │
        ──────────────────────────────────────────
```

---

## Test Suite Overview

| Module | What It Tests |
|--------|--------------|
| `tests/api/test_order_rest.py` | REST API: happy path, negative, boundary, idempotency |
| `tests/api/test_inventory_graphql.py` | GraphQL queries, mutations, schema validation |
| `tests/api/test_carrier_grpc.py` | gRPC rate shopping, label generation, weight boundaries |
| `tests/data_validation/test_sql_integrity.py` | Cross-service DB invariants — the safety net |
| `tests/e2e/test_order_lifecycle.py` | Full order flow: create → allocate → fulfill → verify DB |
| `tests/edge_cases/test_boundaries.py` | AI-generated + manual boundary/negative cases |

---

## Bugs Caught

| Bug | Severity | Test |
|-----|----------|------|
| Idempotency key not enforced — duplicate orders created | High | `test_idempotency_key_returns_same_order` |
| 72 lb package matched to ground carrier (70 lb limit) | High | `test_heavy_package_routes_to_freight_only` |
| Fulfilled order with no inventory decrement transaction | Critical | `test_no_fulfilled_order_without_inventory_decrement` |
| `quantity: -1` accepted with 201 | Medium | `test_create_order_quantity_negative_rejected` |
| Reserved > on_hand after concurrent reserve calls | Critical | `test_inventory_reserved_never_exceeds_on_hand` |

---

## Quick Start

### 1. Prerequisites

- Docker + Docker Compose
- Python 3.11+

### 2. Start all services

```bash
docker compose up -d
```

Wait ~15 seconds for all health checks to pass.

### 3. Install test dependencies

```bash
pip install -r requirements.txt
```

### 4. Generate gRPC stubs (required for carrier tests)

```bash
bash scripts/generate_protos.sh
```

### 5. Copy env config

```bash
cp .env.example .env
```

### 6. Run the tests

```bash
# Full suite
pytest tests/ -v

# SQL integrity tests only
pytest tests/data_validation/ -v

# E2E lifecycle tests only
pytest tests/e2e/ -v

# REST API tests only
pytest tests/api/test_order_rest.py -v

# Skip gRPC tests (if stubs not generated)
pytest tests/ -v --ignore=tests/api/test_carrier_grpc.py
```

### 7. View Grafana dashboard

Open [http://localhost:3000](http://localhost:3000) — no login required (anonymous mode enabled).

---

## AI Edge Case Generator

Reads the live OpenAPI schema and uses Claude to suggest boundary/negative test cases:

```bash
export ANTHROPIC_API_KEY=your_key_here
python -m ai_tools.edge_case_generator
python -m ai_tools.edge_case_generator --endpoint /orders --method POST --output json
```

---

## TestRail Integration

After running tests, sync results to TestRail:

```bash
pytest tests/ --junitxml=reports/results.xml
python testrail/sync_results.py reports/results.xml --run-name "Sprint 12 Regression"
```

---

## Project Structure

```
fulfillsentry/
├── backend/
│   ├── order_service/          # FastAPI REST — order lifecycle
│   ├── inventory_service/      # Strawberry GraphQL — stock management
│   └── carrier_service/        # gRPC — rate shopping + label generation
├── tests/
│   ├── api/                    # REST, GraphQL, gRPC tests
│   ├── data_validation/        # SQL integrity tests
│   ├── e2e/                    # End-to-end lifecycle tests
│   └── edge_cases/             # Boundary + security tests
├── ai_tools/
│   └── edge_case_generator.py  # Claude API → test case suggestions
├── testrail/
│   └── sync_results.py         # Push results to TestRail
├── observability/              # Prometheus + Grafana config
├── scripts/                    # Proto generation, seed scripts
└── .github/workflows/          # CI + nightly regression
```

---

## Tech Stack

| Category | Tools |
|----------|-------|
| Test framework | pytest, pytest-xdist, pytest-cov, pytest-html |
| REST testing | requests, httpx |
| GraphQL testing | gql |
| gRPC testing | grpcio, grpcio-tools, protobuf |
| Database | PostgreSQL, psycopg2, SQLAlchemy |
| Backend (SUT) | FastAPI, Strawberry GraphQL, gRPC |
| CI/CD | GitHub Actions |
| Observability | Prometheus, Grafana |
| AI test generation | Anthropic Claude API |
| Test management | TestRail API integration |
| Infrastructure | Docker Compose |
