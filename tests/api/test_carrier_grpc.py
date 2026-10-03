"""
gRPC tests for the Carrier Service.
Covers: rate shopping, label generation, address validation, boundary weights.
"""
import pytest
import sys
import os

# Ensure generated stubs are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend/carrier_service/generated"))

try:
    import carrier_pb2
    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False

pytestmark = pytest.mark.skipif(not GRPC_AVAILABLE, reason="gRPC stubs not generated — run scripts/generate_protos.sh first")


class TestRateShopping:
    def test_standard_weight_returns_multiple_rates(self, grpc_stub):
        """A typical 5 lb package should get rates from at least 3 carriers."""
        req = carrier_pb2.RateRequest(
            origin_zip="94105", destination_zip="10001", weight_lbs=5.0, service_level="GROUND"
        )
        resp = grpc_stub.GetRates(req)
        assert len(resp.rates) >= 3
        assert resp.cheapest != ""
        assert resp.fastest != ""

    def test_all_rates_have_positive_cost(self, grpc_stub):
        req = carrier_pb2.RateRequest(origin_zip="94105", destination_zip="10001", weight_lbs=10.0)
        resp = grpc_stub.GetRates(req)
        for rate in resp.rates:
            assert rate.rate_usd > 0, f"Carrier {rate.carrier} returned $0 rate"
            assert rate.estimated_days > 0

    def test_heavy_package_routes_to_freight_only(self, grpc_stub):
        """
        Boundary test: a 72 lb package must route to FREIGHT carriers only.
        Bug history: packages at exactly 70.1 lbs were matched to GROUND carriers
        that have a 70 lb weight limit, causing failed pickups.
        """
        req = carrier_pb2.RateRequest(origin_zip="94105", destination_zip="10001", weight_lbs=72.0)
        resp = grpc_stub.GetRates(req)
        for rate in resp.rates:
            assert rate.service == "FREIGHT", (
                f"Non-freight carrier {rate.carrier}/{rate.service} returned for 72 lb package — "
                f"this carrier cannot accept packages this heavy"
            )

    def test_weight_at_70lb_limit_boundary(self, grpc_stub):
        """Boundary: exactly 70 lbs is the max for ground carriers."""
        req = carrier_pb2.RateRequest(origin_zip="94105", destination_zip="10001", weight_lbs=70.0)
        resp = grpc_stub.GetRates(req)
        assert len(resp.rates) >= 1

    def test_weight_just_above_70lb_uses_freight(self, grpc_stub):
        """Boundary: 70.1 lbs must NOT get ground rates."""
        req = carrier_pb2.RateRequest(origin_zip="94105", destination_zip="10001", weight_lbs=70.1)
        resp = grpc_stub.GetRates(req)
        for rate in resp.rates:
            assert "FREIGHT" in rate.service or rate.service == "FREIGHT"

    def test_heavier_package_costs_more(self, grpc_stub):
        """Rate for 30 lb package must be higher than for 5 lb package with same carrier."""
        light = grpc_stub.GetRates(carrier_pb2.RateRequest(origin_zip="94105", destination_zip="10001", weight_lbs=5.0))
        heavy = grpc_stub.GetRates(carrier_pb2.RateRequest(origin_zip="94105", destination_zip="10001", weight_lbs=30.0))
        light_rates = {f"{r.carrier}-{r.service}": r.rate_usd for r in light.rates}
        for rate in heavy.rates:
            key = f"{rate.carrier}-{rate.service}"
            if key in light_rates:
                assert rate.rate_usd > light_rates[key], f"{key}: heavier package should cost more"


class TestLabelGeneration:
    def test_generate_label_returns_tracking_number(self, grpc_stub):
        req = carrier_pb2.LabelRequest(
            order_id="ORD-TEST-001",
            carrier="FedEx",
            service="GROUND",
            origin_zip="94105",
            destination_zip="10001",
            weight_lbs=3.5,
            recipient_name="Test Customer",
            recipient_addr="123 Main St, New York, NY 10001",
        )
        resp = grpc_stub.GenerateLabel(req)
        assert resp.success is True
        assert len(resp.tracking_number) > 0
        assert resp.label_url.startswith("https://")

    def test_generate_label_missing_order_id_fails(self, grpc_stub):
        req = carrier_pb2.LabelRequest(
            order_id="", carrier="FedEx", weight_lbs=3.5,
            origin_zip="94105", destination_zip="10001",
        )
        resp = grpc_stub.GenerateLabel(req)
        assert resp.success is False
        assert resp.error_message != ""

    def test_generate_label_zero_weight_fails(self, grpc_stub):
        """Boundary: zero-weight label must be rejected — carrier APIs reject these."""
        req = carrier_pb2.LabelRequest(order_id="ORD-001", carrier="UPS", weight_lbs=0.0)
        resp = grpc_stub.GenerateLabel(req)
        assert resp.success is False

    def test_each_label_has_unique_tracking(self, grpc_stub):
        base = carrier_pb2.LabelRequest(
            carrier="FedEx", service="GROUND", weight_lbs=2.0,
            origin_zip="94105", destination_zip="10001",
            recipient_name="User", recipient_addr="1 Main",
        )
        r1 = grpc_stub.GenerateLabel(carrier_pb2.LabelRequest(**{**base.__class__.DESCRIPTOR.fields_by_name, "order_id": "ORD-A"}))
        r2 = grpc_stub.GenerateLabel(carrier_pb2.LabelRequest(**{**base.__class__.DESCRIPTOR.fields_by_name, "order_id": "ORD-B"}))
        # Both should succeed and have different tracking numbers
        assert r1.tracking_number != r2.tracking_number


class TestAddressValidation:
    def test_valid_address_passes(self, grpc_stub):
        req = carrier_pb2.AddressRequest(line1="123 Main St", city="San Francisco", state="CA", zip_code="94105")
        resp = grpc_stub.ValidateAddress(req)
        assert resp.valid is True

    def test_short_zip_code_fails(self, grpc_stub):
        req = carrier_pb2.AddressRequest(line1="1 Main", city="SF", state="CA", zip_code="941")
        resp = grpc_stub.ValidateAddress(req)
        assert resp.valid is False
        assert resp.error_message != ""
