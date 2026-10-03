"""
gRPC Carrier Service — rate shopping and label generation.
Run: python -m backend.carrier_service.server
"""
import sys
import os
import grpc
import uuid
import random
from concurrent import futures

# Add project root to path so generated stubs are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "generated"))

import carrier_pb2
import carrier_pb2_grpc


CARRIER_RULES = {
    # (min_lbs, max_lbs, carrier, service, base_rate, days)
    "FEDEX_GROUND":       (0,   70,  "FedEx",  "GROUND",    8.50,  3),
    "FEDEX_EXPRESS":      (0,   70,  "FedEx",  "EXPRESS",   18.00, 1),
    "UPS_GROUND":         (0,   70,  "UPS",    "GROUND",    9.20,  4),
    "UPS_2DAY":           (0,   70,  "UPS",    "2DAY",      22.00, 2),
    "USPS_PRIORITY":      (0,   70,  "USPS",   "PRIORITY",  7.80,  2),
    "FEDEX_FREIGHT":      (70, 999,  "FedEx",  "FREIGHT",   85.00, 5),
    "UPS_FREIGHT":        (70, 999,  "UPS",    "FREIGHT",   90.00, 6),
}


class CarrierServicer(carrier_pb2_grpc.CarrierServiceServicer):
    def GetRates(self, request, context):
        weight = request.weight_lbs
        eligible = []
        for key, (min_w, max_w, carrier, service, base, days) in CARRIER_RULES.items():
            if min_w < weight <= max_w:
                # Weight surcharge above 50 lbs
                surcharge = max(0, (weight - 50) * 0.30) if weight > 50 else 0
                rate = round(base + surcharge + weight * 0.12, 2)
                eligible.append(carrier_pb2.CarrierRate(
                    carrier=carrier,
                    service=service,
                    rate_usd=rate,
                    estimated_days=days,
                ))

        if not eligible:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f"No carriers available for {weight} lbs")
            return carrier_pb2.RateResponse()

        cheapest = min(eligible, key=lambda r: r.rate_usd).carrier + " " + min(eligible, key=lambda r: r.rate_usd).service
        fastest = min(eligible, key=lambda r: r.estimated_days).carrier + " " + min(eligible, key=lambda r: r.estimated_days).service

        return carrier_pb2.RateResponse(rates=eligible, cheapest=cheapest, fastest=fastest)

    def GenerateLabel(self, request, context):
        if not request.order_id:
            return carrier_pb2.LabelResponse(success=False, error_message="order_id is required")
        if request.weight_lbs <= 0:
            return carrier_pb2.LabelResponse(success=False, error_message="weight_lbs must be > 0")

        tracking = f"FS{uuid.uuid4().hex[:12].upper()}"
        label_url = f"https://labels.fulfillsentry.local/{tracking}.pdf"
        return carrier_pb2.LabelResponse(
            success=True,
            tracking_number=tracking,
            label_url=label_url,
            carrier=request.carrier,
        )

    def ValidateAddress(self, request, context):
        if not request.zip_code or len(request.zip_code) < 5:
            return carrier_pb2.AddressResponse(valid=False, error_message="Invalid ZIP code")
        return carrier_pb2.AddressResponse(valid=True, normalized_zip=request.zip_code[:5])


def serve(port: int = 50051):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    carrier_pb2_grpc.add_CarrierServiceServicer_to_server(CarrierServicer(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"Carrier gRPC service listening on port {port}")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
