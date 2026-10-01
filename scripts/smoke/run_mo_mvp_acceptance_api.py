#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from nex_mo.mvp_acceptance_api import (  # noqa: E402
    MO_MVP_ACCEPTANCE_OPERATIONS_PATH,
    register_mo_mvp_acceptance_routes,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
from run_mo_mvp_acceptance_evaluator import (  # noqa: E402
    build_passing_evidence,
)


SCHEMA_VERSION = "mo_mvp_acceptance_api_evidence.v1"
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


class StaticEvidenceProvider:
    def collect(self, *, observed_at: datetime) -> dict[str, Any]:
        if observed_at != NOW:
            raise ValueError("unexpected observation time")
        return build_passing_evidence()


def run_mo_mvp_acceptance_api() -> dict[str, Any]:
    app = build_service_app(SERVICE_SPECS["nex-mo"])
    register_mo_mvp_acceptance_routes(
        app,
        evidence_provider=StaticEvidenceProvider(),
        clock=lambda: NOW,
    )
    client = TestClient(app)
    unauthorized = client.get(MO_MVP_ACCEPTANCE_OPERATIONS_PATH)
    token = issue_mock_service_token(
        service_id="nex-oa", audience="nex-mo"
    ).access_token
    accepted = client.get(
        MO_MVP_ACCEPTANCE_OPERATIONS_PATH,
        headers={"Authorization": f"Bearer {token}"},
    )
    payload = accepted.json()
    checks = {
        "unauthorized_rejected": unauthorized.status_code == 401,
        "service_claim_accepted": accepted.status_code == 200,
        "accepted_projection": payload.get("status") == "ACCEPTED",
        "oa_transition_ready": payload.get("transition_status") == "READY_FOR_OA",
        "server_selected": payload.get("server_selected") is True,
        "all_gates_passed": payload.get("summary")
        == {"gate_count": 9, "passed_gate_count": 9, "blocked_gate_count": 0},
        "private_evidence_absent": all(
            token not in json.dumps(payload, ensure_ascii=False).lower()
            for token in ("api_key", "database_url", "provider_url", "passed_tests")
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1196",
        "requirement": "S120",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_mvp_acceptance_api_failed",
        "summary": {
            "unauthorized_status": unauthorized.status_code,
            "accepted_status": accepted.status_code,
            "gate_count": payload.get("summary", {}).get("gate_count", 0),
            "passed_gate_count": payload.get("summary", {}).get(
                "passed_gate_count", 0
            ),
            "failed_check_count": sum(not value for value in checks.values()),
        },
        "checks": checks,
        "next_slice": "1197" if passed else "blocked",
    }


def summary_line(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    return (
        "mo_mvp_acceptance_api="
        f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"auth={summary.get('unauthorized_status', 0)}/"
        f"{summary.get('accepted_status', 0)} "
        f"gates={summary.get('passed_gate_count', 0)}/"
        f"{summary.get('gate_count', 0)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_mo_mvp_acceptance_api()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
