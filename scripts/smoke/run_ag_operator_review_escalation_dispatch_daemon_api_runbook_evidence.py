#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.operations import register_unified_operation_routes  # noqa: E402
from nex_ag.operator_review_cases import (  # noqa: E402
    OperatorReviewEscalationDispatchStore,
)
from nex_runtime import SERVICE_SPECS, build_service_app  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_escalation_dispatch_daemon_api_runbook.v1"
SLICE_ID = "0758"
SERVICE_ID = "nex-ag"
OPENAPI_PATH = "contracts/openapi/nex-ag.openapi.yaml"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"

ROUTES = {
    ("/admin/v1/operator-review/dispatch-daemon/tick-plan", "get"): {
        "operation_id": "getAgOperatorReviewDispatchDaemonTickPlan",
        "mutation": False,
        "requires_confirm_tick": False,
        "runbook_action": "preview pending dispatch execution without mutation",
    },
    ("/admin/v1/operator-review/dispatch-daemon/tick-plan", "post"): {
        "operation_id": "postAgOperatorReviewDispatchDaemonTickPlan",
        "mutation": False,
        "requires_confirm_tick": False,
        "runbook_action": "preview pending dispatch execution with request body",
    },
    ("/admin/v1/operator-review/dispatch-daemon/tick-once", "post"): {
        "operation_id": "postAgOperatorReviewDispatchDaemonTickOnce",
        "mutation": True,
        "requires_confirm_tick": True,
        "runbook_action": "execute one bounded confirmed daemon tick",
    },
}

REQUIRED_DOCS = (
    "docs/slices/0751_ag_escalation_dispatch_daemon_api_boundary_audit.md",
    "docs/slices/0752_ag_escalation_dispatch_daemon_tick_plan_api_route.md",
    "docs/slices/0753_ag_escalation_dispatch_daemon_tick_once_api_route.md",
    "docs/slices/0754_ag_escalation_dispatch_daemon_api_postgres_smoke.md",
    "docs/slices/0755_ag_escalation_dispatch_daemon_api_privacy_regression.md",
    "docs/slices/0756_ag_escalation_dispatch_daemon_api_contract_hardening.md",
    "docs/slices/0757_ag_escalation_dispatch_daemon_api_runtime_openapi_parity.md",
)

REQUIRED_EVIDENCE_HOOKS = (
    "run_ag_operator_review_escalation_dispatch_daemon_api_boundary_audit.py",
    "run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke.py",
    "run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression.py",
)

FORBIDDEN_CONTROL_REQUEST_FIELDS = {
    "authorization",
    "database_url",
    "idempotency_key",
    "provider_api_key",
    "provider_payload",
    "raw_action_comment",
    "raw_provider_payload",
    "secret",
    "storage_path",
}


def run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    static_paths = _load_static_openapi_paths(root)
    runtime_paths = _runtime_openapi_paths()
    route_evidence = [
        _route_evidence(path, method, expectation, static_paths, runtime_paths)
        for (path, method), expectation in ROUTES.items()
    ]
    control_request_properties = _control_request_properties(root)
    forbidden_present = sorted(
        FORBIDDEN_CONTROL_REQUEST_FIELDS.intersection(control_request_properties)
    )
    required_docs = [
        {"path": path, "present": (root / path).exists()} for path in REQUIRED_DOCS
    ]
    quality_gate_text = (root / QUALITY_GATE_PATH).read_text(encoding="utf-8")
    evidence_hooks = [
        {"hook": hook, "present": hook in quality_gate_text}
        for hook in REQUIRED_EVIDENCE_HOOKS
    ]
    checks = {
        "static_routes_ready": all(item["static_ready"] for item in route_evidence),
        "runtime_routes_ready": all(item["runtime_ready"] for item in route_evidence),
        "operation_ids_match": all(
            item["static_operation_id"] == item["runtime_operation_id"]
            for item in route_evidence
        ),
        "tick_plan_is_non_mutating": all(
            not item["mutation"]
            for item in route_evidence
            if item["path"].endswith("/tick-plan")
        ),
        "tick_once_requires_confirm": all(
            item["requires_confirm_tick"]
            for item in route_evidence
            if item["path"].endswith("/tick-once")
        ),
        "sensitive_control_fields_absent": not forbidden_present,
        "docs_present": all(item["present"] for item in required_docs),
        "evidence_hooks_present": all(item["present"] for item in evidence_hooks),
    }
    return {
        "runbook_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else "ag_operator_review_escalation_dispatch_daemon_api_runbook_failed",
        "slice": SLICE_ID,
        "service": SERVICE_ID,
        "route_count": len(route_evidence),
        "routes": route_evidence,
        "control_request_contract": {
            "allowed_fields": sorted(control_request_properties),
            "forbidden_present": forbidden_present,
        },
        "required_docs": required_docs,
        "evidence_hooks": evidence_hooks,
        "checks": checks,
    }


def _load_static_openapi_paths(root: Path) -> Mapping[str, Any]:
    payload = yaml.safe_load((root / OPENAPI_PATH).read_text(encoding="utf-8"))
    return payload["paths"]


def _runtime_openapi_paths() -> Mapping[str, Any]:
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_unified_operation_routes(
        app,
        operator_review_escalation_dispatch_store=OperatorReviewEscalationDispatchStore(),
    )
    return app.openapi()["paths"]


def _control_request_properties(root: Path) -> set[str]:
    payload = yaml.safe_load((root / OPENAPI_PATH).read_text(encoding="utf-8"))
    properties = payload["components"]["schemas"][
        "AgOperatorReviewDispatchDaemonControlRequest"
    ]["properties"]
    return set(properties)


def _route_evidence(
    path: str,
    method: str,
    expectation: Mapping[str, Any],
    static_paths: Mapping[str, Any],
    runtime_paths: Mapping[str, Any],
) -> dict[str, Any]:
    static_operation = static_paths.get(path, {}).get(method, {})
    runtime_operation = runtime_paths.get(path, {}).get(method, {})
    operation_id = str(expectation["operation_id"])
    return {
        "path": path,
        "method": method.upper(),
        "operation_id": operation_id,
        "static_operation_id": static_operation.get("operationId"),
        "runtime_operation_id": runtime_operation.get("operationId"),
        "static_ready": static_operation.get("operationId") == operation_id,
        "runtime_ready": runtime_operation.get("operationId") == operation_id,
        "tags": runtime_operation.get("tags") or static_operation.get("tags") or [],
        "mutation": bool(expectation["mutation"]),
        "requires_confirm_tick": bool(expectation["requires_confirm_tick"]),
        "runbook_action": expectation["runbook_action"],
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_api_runbook=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = evidence.get("checks", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_api_runbook=pass "
        f"routes={evidence.get('route_count')} "
        f"runtime_routes_ready={checks.get('runtime_routes_ready')} "
        f"sensitive_fields_absent={checks.get('sensitive_control_fields_absent')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
