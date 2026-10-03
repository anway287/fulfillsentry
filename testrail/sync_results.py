"""
TestRail sync script — pushes pytest JUnit XML results to TestRail.

Usage:
    python testrail/sync_results.py reports/results.xml
    python testrail/sync_results.py reports/results.xml --run-name "Release v1.4.2"

Environment variables required:
    TESTRAIL_URL        e.g. https://yourcompany.testrail.io
    TESTRAIL_USER       your TestRail email
    TESTRAIL_API_KEY    TestRail API key (not your password)
    TESTRAIL_PROJECT_ID TestRail project ID
    TESTRAIL_SUITE_ID   TestRail suite ID (optional)
"""
import argparse
import base64
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime

import requests


class TestRailClient:
    def __init__(self, url: str, user: str, api_key: str):
        self.base = url.rstrip("/") + "/index.php?/api/v2"
        credentials = base64.b64encode(f"{user}:{api_key}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> dict:
        resp = requests.get(f"{self.base}/{path}", headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict) -> dict:
        resp = requests.post(f"{self.base}/{path}", headers=self.headers, json=data)
        resp.raise_for_status()
        return resp.json()

    def get_cases(self, project_id: int, suite_id: int = None) -> list:
        path = f"get_cases/{project_id}"
        if suite_id:
            path += f"&suite_id={suite_id}"
        return self._get(path).get("cases", [])

    def create_run(self, project_id: int, name: str, suite_id: int = None, case_ids: list = None) -> dict:
        data = {"name": name, "include_all": not bool(case_ids)}
        if suite_id:
            data["suite_id"] = suite_id
        if case_ids:
            data["case_ids"] = case_ids
        return self._post(f"add_run/{project_id}", data)

    def add_results_for_cases(self, run_id: int, results: list) -> dict:
        return self._post(f"add_results_for_cases/{run_id}", {"results": results})

    def close_run(self, run_id: int) -> dict:
        return self._post(f"close_run/{run_id}", {})


def parse_junit_xml(xml_path: str) -> list:
    """Parse a JUnit XML file and return a list of test result dicts."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    results = []

    for suite in root.iter("testsuite"):
        for case in suite.iter("testcase"):
            name = f"{case.get('classname', '')}.{case.get('name', '')}".strip(".")
            duration = float(case.get("time", 0))

            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")

            if failure is not None:
                status = "failed"
                comment = failure.get("message", "") + "\n" + (failure.text or "")
            elif error is not None:
                status = "failed"
                comment = error.get("message", "") + "\n" + (error.text or "")
            elif skipped is not None:
                status = "skipped"
                comment = skipped.get("message", "")
            else:
                status = "passed"
                comment = ""

            results.append({
                "name": name,
                "status": status,
                "duration": duration,
                "comment": comment.strip(),
            })

    return results


# TestRail status IDs
STATUS_MAP = {
    "passed":  1,  # Passed
    "failed":  5,  # Failed
    "skipped": 4,  # Retest (closest to skipped)
}


def sync_to_testrail(xml_path: str, run_name: str):
    url      = os.getenv("TESTRAIL_URL")
    user     = os.getenv("TESTRAIL_USER")
    api_key  = os.getenv("TESTRAIL_API_KEY")
    proj_id  = int(os.getenv("TESTRAIL_PROJECT_ID", "1"))
    suite_id = os.getenv("TESTRAIL_SUITE_ID")

    if not all([url, user, api_key]):
        print("TESTRAIL_URL, TESTRAIL_USER, and TESTRAIL_API_KEY must be set.", file=sys.stderr)
        sys.exit(1)

    client = TestRailClient(url, user, api_key)
    results = parse_junit_xml(xml_path)

    print(f"Parsed {len(results)} test results from {xml_path}")
    passed  = sum(1 for r in results if r["status"] == "passed")
    failed  = sum(1 for r in results if r["status"] == "failed")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    print(f"  Passed: {passed}  Failed: {failed}  Skipped: {skipped}")

    # Fetch existing cases and build name→id map
    cases = client.get_cases(proj_id, int(suite_id) if suite_id else None)
    case_map = {c["title"]: c["id"] for c in cases}

    # Only sync results for cases that exist in TestRail
    tr_results = []
    unmatched = []
    for r in results:
        case_id = case_map.get(r["name"])
        if case_id:
            tr_results.append({
                "case_id": case_id,
                "status_id": STATUS_MAP.get(r["status"], 4),
                "elapsed": f"{max(1, int(r['duration']))}s",
                "comment": r["comment"] or f"Automated run: {run_name}",
            })
        else:
            unmatched.append(r["name"])

    if unmatched:
        print(f"\n{len(unmatched)} tests not found in TestRail (will be skipped):")
        for name in unmatched[:10]:
            print(f"  - {name}")
        if len(unmatched) > 10:
            print(f"  ... and {len(unmatched) - 10} more")

    if not tr_results:
        print("No matching TestRail cases found. Push results manually or create cases first.")
        return

    run = client.create_run(
        proj_id,
        run_name,
        suite_id=int(suite_id) if suite_id else None,
        case_ids=[r["case_id"] for r in tr_results],
    )
    print(f"\nCreated TestRail run: {run['id']} — {run['name']}")

    client.add_results_for_cases(run["id"], tr_results)
    print(f"Pushed {len(tr_results)} results.")

    client.close_run(run["id"])
    print(f"Run closed. View at: {url}/index.php?/runs/view/{run['id']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("xml_path", help="Path to JUnit XML file")
    parser.add_argument("--run-name", default=f"FulfillSentry — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    args = parser.parse_args()
    sync_to_testrail(args.xml_path, args.run_name)
