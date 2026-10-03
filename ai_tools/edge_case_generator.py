"""
AI-powered edge case generator for FulfillSentry.

Reads the OpenAPI schema for the Order Service and uses the Claude API to
generate boundary and negative test cases that a human might miss.

Output is printed as pytest.param() blocks you can paste into test_boundaries.py.

Usage:
    python -m ai_tools.edge_case_generator
    python -m ai_tools.edge_case_generator --schema backend/order_service/openapi.json
    python -m ai_tools.edge_case_generator --endpoint /orders --method POST
"""
import argparse
import json
import os
import sys
import requests

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


SYSTEM_PROMPT = """You are a senior QA engineer specializing in API testing for
e-commerce fulfillment platforms. You think methodically about edge cases,
boundary values, and adversarial inputs that typical developers miss.

Your output must be a valid JSON array — nothing else, no markdown fences."""

USER_PROMPT_TEMPLATE = """Given this OpenAPI schema for a fulfillment order service,
generate 15 specific boundary and negative test cases.

For each case return a JSON object with:
- "test_name": snake_case descriptive name
- "input_payload": the JSON payload to send
- "expected_status_code": integer (200, 201, 400, 404, 409, 422, etc.)
- "test_rationale": one sentence explaining what bug this would catch
- "category": one of [boundary, negative, security, idempotency, validation]

Focus on:
1. Numeric boundaries: zero, -1, max int, very large values
2. String boundaries: empty string, max-length + 1, unicode, whitespace-only
3. Missing required fields (one at a time)
4. Invalid enum values
5. Type coercion attacks (string "1" where int 1 expected)
6. SQL injection patterns in string fields
7. Duplicate keys that should be idempotent
8. Malformed dates and ZIPs

Schema:
{schema}

Return only the JSON array."""


def fetch_schema_from_service(base_url: str) -> dict:
    """Fetch live OpenAPI schema from the running Order Service."""
    resp = requests.get(f"{base_url}/openapi.json", timeout=5)
    resp.raise_for_status()
    return resp.json()


def generate_edge_cases(schema: dict, endpoint: str = None, method: str = None) -> list:
    if not ANTHROPIC_AVAILABLE:
        print("ERROR: anthropic package not installed. Run: pip install anthropic", file=sys.stderr)
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    # Optionally narrow to a specific endpoint
    if endpoint and method:
        schema_snippet = {
            "paths": {
                endpoint: {
                    method.lower(): schema.get("paths", {}).get(endpoint, {}).get(method.lower(), {})
                }
            },
            "components": schema.get("components", {}),
        }
    else:
        schema_snippet = schema

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(schema=json.dumps(schema_snippet, indent=2))
        }],
    )

    raw = message.content[0].text.strip()
    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw)


def format_as_pytest_params(cases: list) -> str:
    lines = ["# AI-generated edge cases — paste into test_boundaries.py\n",
             "@pytest.mark.parametrize('payload,expected_status', ["]
    for case in cases:
        lines.append(f"    # [{case['category']}] {case['test_rationale']}")
        lines.append(f"    pytest.param(")
        lines.append(f"        {json.dumps(case['input_payload'])},")
        lines.append(f"        {case['expected_status_code']},")
        lines.append(f"        id={json.dumps(case['test_name'])},")
        lines.append(f"    ),")
    lines.append("])")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate AI-powered edge cases for the Order Service API")
    parser.add_argument("--schema", help="Path to openapi.json file (default: fetch from running service)")
    parser.add_argument("--url", default="http://localhost:8001", help="Order Service base URL")
    parser.add_argument("--endpoint", default="/orders", help="Narrow to a specific endpoint path")
    parser.add_argument("--method", default="POST", help="HTTP method to focus on")
    parser.add_argument("--output", choices=["json", "pytest"], default="pytest",
                        help="Output format: raw JSON or pytest.param blocks")
    args = parser.parse_args()

    print(f"Loading schema...", file=sys.stderr)
    if args.schema:
        with open(args.schema) as f:
            schema = json.load(f)
    else:
        try:
            schema = fetch_schema_from_service(args.url)
            print(f"Fetched live schema from {args.url}", file=sys.stderr)
        except Exception as e:
            print(f"Could not fetch schema from {args.url}: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"Generating edge cases via Claude API...", file=sys.stderr)
    cases = generate_edge_cases(schema, endpoint=args.endpoint, method=args.method)
    print(f"Generated {len(cases)} test cases.\n", file=sys.stderr)

    if args.output == "json":
        print(json.dumps(cases, indent=2))
    else:
        print(format_as_pytest_params(cases))


if __name__ == "__main__":
    main()
