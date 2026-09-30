#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.contract_api_drift_audit import (  # noqa: E402
    build_mo_contract_api_drift_audit,
)
from nex_mo.provider_resilience_contract import (  # noqa: E402
    build_mo_provider_resilience_contract,
)
from run_mo_contract_http_smoke import (  # noqa: E402
    _auth_headers,
    _build_isolated_app,
    _temporary_environment,
)


def run_mo_provider_resilience_contract() -> dict[str, Any]:
    env = {
        "NEX_PROFILE": "local_mock",
        "NEX_MO_PROVIDER_MODE": "mock",
        "NEX_MO_REMOTE_EMBEDDING_URL": "",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "",
        "NEX_MO_REMOTE_RERANKER_URL": "",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "",
        "NEX_MO_VLLM_BASE_URL": "",
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": "",
        "NEX_MO_VLLM_API_KEY": "",
    }
    with _temporary_environment(env):
        app, _ = _build_isolated_app()
        response = TestClient(app).get(
            "/api/v1/provider-telemetry",
            headers=_auth_headers(),
        )
    contract = build_mo_provider_resilience_contract(
        telemetry_payload=response.json() if response.status_code == 200 else {},
    )
    drift = build_mo_contract_api_drift_audit()
    checks = {
        "authenticated_api_responded": response.status_code == 200,
        "runtime_contract_hardened": contract["status"] == "PASS",
        "runtime_openapi_drift_zero": drift["summary"]["drift_count"] == 0,
        "operation_count_preserved": drift["summary"]["runtime_operation_count"]
        >= 20,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_provider_resilience_contract_evidence.v1",
        "slice": "1150",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_resilience_contract_failed",
        "checks": checks,
        "contract": contract,
        "summary": {
            "runtime_item_count": contract["summary"]["runtime_item_count"],
            "retry_field_count": contract["summary"]["retry_field_count"],
            "drift_count": drift["summary"]["drift_count"],
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
        },
        "next_slice": "1151" if passed else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_resilience_contract="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"items={summary.get('runtime_item_count', 0)} "
        f"retry_fields={summary.get('retry_field_count', 0)} "
        f"drift={summary.get('drift_count', -1)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_resilience_contract()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
