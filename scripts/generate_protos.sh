#!/usr/bin/env bash
# Compile carrier.proto into Python gRPC stubs.
# Run this once before running gRPC tests.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PROTO_FILE="$PROJECT_ROOT/backend/carrier_service/carrier.proto"
OUT_DIR="$PROJECT_ROOT/backend/carrier_service/generated"

echo "Generating gRPC stubs from $PROTO_FILE..."
python -m grpc_tools.protoc \
    --proto_path="$(dirname "$PROTO_FILE")" \
    --python_out="$OUT_DIR" \
    --grpc_python_out="$OUT_DIR" \
    "$PROTO_FILE"

# Fix import in generated grpc file (grpc_tools generates absolute imports)
sed -i '' 's/^import carrier_pb2/from . import carrier_pb2/' "$OUT_DIR/carrier_pb2_grpc.py" 2>/dev/null || true

touch "$OUT_DIR/__init__.py"
echo "Done. Stubs written to $OUT_DIR"
