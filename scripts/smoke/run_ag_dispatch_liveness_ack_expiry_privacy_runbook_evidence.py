#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.liveness_ack_expiry_reconciliation import (  # noqa: E402
    run_operator_review_liveness_ack_expiry_reconciliation,
)
from nex_ag.operations import (  # noqa: E402
    _operator_review_liveness_ack_expiry_reconciliation_overlay,
    register_unified_operation_routes,
)
from nex_ag.operator_review_liveness_ack import (  # noqa: E402
    OperatorReviewLivenessAckStateError,
    OperatorReviewLivenessAckStateStore,
    build_operator_review_liveness_ack_state_record,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


SCHEMA_VERSION = "ag_dispatch_liveness_ack_expiry_privacy_runbook.v1"
SLICE_ID = "0819"
ROUTE = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/"
    "ack-states/reconcile-expired"
)
OPERATION_ID = "postAgOperatorReviewDispatchDaemonLivenessAckExpiryReconcile"
MIGRATION_PATH = "database/nex-ag/migrations/0813_ag_ack_expiry_index.sql"
OPENAPI_PATH = "contracts/openapi/nex-ag.openapi.yaml"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = "run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence.py"
TABLE_NAME = "ag_op_review_ack_state"
INDEX_NAME = "idx_ag_ack_state_expiry"
MAX_IDENTIFIER_LENGTH = 30
FORBIDDEN_VALUES = {
    "database_password": "nuri1004",
    "database_url": (
        "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test"
    ),
    "authorization": "Bearer expiry-secret-token-0819",
    "raw_comment": "raw-expiry-comment-secret-0819",
    "raw_idempotency_key": "raw-expiry-idempotency-secret-0819",
    "provider_api_key": "provider-api-key-secret-0819",
}
FORBIDDEN_KEYS = {
    "authorization",
    "database_url",
    "idempotency_key",
    "provider_api_key",
    "raw_comment",
    "raw_idempotency_key",
    "raw_payload",
    "secret",
}
REQUIRED_DOCS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("0811", "ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit"),
        ("0812", "ag_dispatch_liveness_ack_expiry_reconciliation_contract"),
        ("0813", "ag_dispatch_liveness_ack_expiry_persistence_adapter"),
        ("0814", "ag_dispatch_liveness_ack_expiry_reconciliation_worker"),
        ("0815", "ag_dispatch_liveness_ack_expiry_reconciliation_api_audit"),
        ("0816", "ag_dispatch_liveness_ack_expiry_operations_overlay"),
        ("0817", "ag_dispatch_liveness_ack_expiry_contract_hardening"),
        ("0818", "ag_dispatch_liveness_ack_expiry_postgres_smoke"),
    )
)


class _BrokenStore:
    def list_expiry_candidates(self, **_kwargs: Any) -> list[dict[str, Any]]:
        raise OperatorReviewLivenessAckStateError(
            "state store unavailable",
            error_code="ag.operator_review_liveness_ack_state_store_unavailable",
            status_code=503,
        )


class _ConflictStore:
    def __init__(self, candidate: dict[str, Any]) -> None:
        self.candidate = candidate

    def list_expiry_candidates(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [self.candidate]

    def apply_expiry_reconciliation(self, *_args: Any, **_kwargs: Any) -> bool:
        return False


def run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    state = _expired_state()
    store = OperatorReviewLivenessAckStateStore()
    store.save(state)
    client, events = _client(store)
    applied = client.post(
        ROUTE,
        headers=_headers(),
        json={"observed_at": "2026-09-17T02:00:00Z", "limit": 10},
    )
    rerun = client.post(
        ROUTE,
        headers=_headers(),
        json={"observed_at": "2026-09-17T02:00:01Z", "limit": 10},
    )
    invalid = client.post(
        ROUTE,
        headers=_headers(),
        json={"observed_at": "not-a-time"},
    )
    unavailable, _unused_events = _client(_BrokenStore())
    failed = unavailable.post(ROUTE, headers=_headers(), json={})
    conflict = run_operator_review_liveness_ack_expiry_reconciliation(
        _ConflictStore(state),
        observed_at="2026-09-17T02:00:00Z",
        limit=10,
    )
    persisted = store.get(state["ack_state_id"])
    overlay = _operator_review_liveness_ack_expiry_reconciliation_overlay(
        persisted,
        effective_status={"effective_state_status": "EXPIRED"},
    )
    audit_records = events.list_events()
    route = _route_evidence(root)
    migration = _migration_evidence(root)
    runbook = _runbook_actions()
    required_docs = [
        {"path": path, "present": (root / path).exists()} for path in REQUIRED_DOCS
    ]
    quality_gate_hook_present = EVIDENCE_HOOK in (
        root / QUALITY_GATE_PATH
    ).read_text(encoding="utf-8")
    surfaces = {
        "applied": _response_surface(applied),
        "idempotent_rerun": _response_surface(rerun),
        "invalid_request": _response_surface(invalid),
        "store_unavailable": _response_surface(failed),
        "conflict": _run_surface(conflict),
        "audit": _audit_surface(audit_records),
        "overlay": overlay,
        "route": route,
        "migration": migration,
        "runbook": runbook,
    }
    serialized = json.dumps(surfaces, ensure_ascii=False, sort_keys=True)
    forbidden_value_labels = _forbidden_value_labels(serialized)
    forbidden_key_paths = _forbidden_key_paths(surfaces)
    checks = {
        "protected_apply_succeeded": (
            applied.status_code == 200
            and applied.json().get("applied_count") == 1
        ),
        "idempotent_rerun_empty": (
            rerun.status_code == 200
            and rerun.json().get("candidate_count") == 0
            and rerun.json().get("applied_count") == 0
        ),
        "cas_conflict_reported": (
            conflict.get("run_status") == "COMPLETED_WITH_CONFLICTS"
            and conflict.get("conflict_count") == 1
        ),
        "invalid_request_is_400": invalid.status_code == 400,
        "store_unavailable_is_503": failed.status_code == 503,
        "audit_summary_redacted": _audit_is_safe(audit_records),
        "overlay_reconciled": (
            overlay.get("reconciliation_status") == "RECONCILED"
            and overlay.get("state_mutated") is False
        ),
        "static_route_ready": route["static_ready"],
        "runtime_route_ready": route["runtime_ready"],
        "migration_ready": migration["ready"],
        "identifier_lengths_safe": migration["identifier_lengths_safe"],
        "runbook_complete": set(runbook)
        == {"400", "401", "503", "conflict", "idempotent_rerun"},
        "forbidden_values_absent": not forbidden_value_labels,
        "forbidden_keys_absent": not forbidden_key_paths,
        "docs_present": all(item["present"] for item in required_docs),
        "quality_gate_hook_present": quality_gate_hook_present,
    }
    passed = all(checks.values())
    evidence = {
        "runbook_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "ag_dispatch_liveness_ack_expiry_privacy_runbook_failed",
        "slice": SLICE_ID,
        "surface_count": len(surfaces),
        "surfaces": surfaces,
        "required_docs": required_docs,
        "forbidden_value_labels": forbidden_value_labels,
        "forbidden_key_paths": forbidden_key_paths,
        "checks": checks,
    }
    _assert_no_forbidden_values(json.dumps(evidence, ensure_ascii=False))
    return evidence


def _expired_state() -> dict[str, Any]:
    return build_operator_review_liveness_ack_state_record(
        ack_state_id="ack-expiry-privacy-0819",
        acknowledgement_key="nex-ag:dispatch-daemon:stale",
        service_id="nex-ag",
        worker_id="ag-dispatch-execution-daemon",
        worker_type="operator_review_dispatch_daemon",
        liveness_status="STALE",
        action="suppress_for_ttl",
        state_status="SUPPRESSED",
        operator_ref={"operator_type": "service", "operator_id": "evidence-0819"},
        reason_codes=["privacy_runbook_0819"],
        comment=FORBIDDEN_VALUES["raw_comment"],
        idempotency_key=FORBIDDEN_VALUES["raw_idempotency_key"],
        requested_ttl_seconds=300,
        suppressed_until="2026-09-17T01:30:00Z",
        metadata={"source": "privacy_runbook", "slice": SLICE_ID},
        created_at="2026-09-17T01:00:00Z",
        updated_at="2026-09-17T01:00:00Z",
    )


def _client(store: Any) -> tuple[TestClient, InMemoryOperationalEventStore]:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    events = InMemoryOperationalEventStore()
    register_unified_operation_routes(
        app,
        event_store=events,
        operator_review_liveness_ack_state_store=store,
    )
    return TestClient(app), events


def _headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "req-expiry-privacy-0819",
    }


def _response_surface(response: Any) -> dict[str, Any]:
    payload = response.json()
    return {
        "status_code": response.status_code,
        "run_status": payload.get("run_status"),
        "candidate_count": payload.get("candidate_count"),
        "applied_count": payload.get("applied_count"),
        "conflict_count": payload.get("conflict_count"),
        "error_code": payload.get("error_code"),
        "outcome_statuses": [
            item.get("status")
            for item in payload.get("outcomes", [])
            if isinstance(item, Mapping)
        ],
    }


def _run_surface(run: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "run_status": run.get("run_status"),
        "candidate_count": run.get("candidate_count"),
        "applied_count": run.get("applied_count"),
        "conflict_count": run.get("conflict_count"),
        "outcome_statuses": [
            item.get("status")
            for item in run.get("outcomes", [])
            if isinstance(item, Mapping)
        ],
    }


def _audit_surface(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "event_count": len(records),
        "event_types": sorted(str(record.get("event_type") or "") for record in records),
        "details": [record.get("details", {}) for record in records],
    }


def _audit_is_safe(records: list[dict[str, Any]]) -> bool:
    return bool(records) and all(
        record.get("details", {}).get("redaction", {}).get("outcomes_included")
        is False
        for record in records
    )


def _route_evidence(root: Path) -> dict[str, bool]:
    static = yaml.safe_load((root / OPENAPI_PATH).read_text(encoding="utf-8"))
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app)
    runtime = app.openapi()
    return {
        "static_ready": static["paths"][ROUTE]["post"]["operationId"]
        == OPERATION_ID,
        "runtime_ready": runtime["paths"][ROUTE]["post"]["operationId"]
        == OPERATION_ID,
    }


def _migration_evidence(root: Path) -> dict[str, Any]:
    migration = (root / MIGRATION_PATH).read_text(encoding="utf-8").lower()
    return {
        "table_name": TABLE_NAME,
        "index_name": INDEX_NAME,
        "ready": (
            f"on {TABLE_NAME}" in migration
            and f"index if not exists {INDEX_NAME}" in migration
            and "state_status, suppressed_until, ack_state_id" in migration
        ),
        "identifier_lengths_safe": (
            len(TABLE_NAME) <= MAX_IDENTIFIER_LENGTH
            and len(INDEX_NAME) <= MAX_IDENTIFIER_LENGTH
        ),
    }


def _runbook_actions() -> dict[str, dict[str, Any]]:
    return {
        "400": {
            "retryable": True,
            "action": "correct observed_at or limit and retry once",
        },
        "401": {
            "retryable": True,
            "action": "refresh the nex-oa service claim before retry",
        },
        "503": {
            "retryable": False,
            "action": "inspect database health, migration, and pool before retry",
        },
        "conflict": {
            "retryable": True,
            "action": "reload state and preserve a concurrent renewal",
        },
        "idempotent_rerun": {
            "retryable": False,
            "action": "treat zero candidates as a successful no-op",
        },
    }


def _forbidden_value_labels(serialized: str) -> list[str]:
    return sorted(
        label for label, value in FORBIDDEN_VALUES.items() if value in serialized
    )


def _forbidden_key_paths(value: object, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_KEYS:
                paths.append(path)
            paths.extend(_forbidden_key_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            path = f"{prefix}[{index}]"
            paths.extend(_forbidden_key_paths(child, path))
    return paths


def _assert_no_forbidden_values(serialized: str) -> None:
    labels = _forbidden_value_labels(serialized)
    if labels:
        raise ValueError(f"privacy evidence contains forbidden values: {labels}")


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_dispatch_liveness_ack_expiry_privacy_runbook=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = evidence.get("checks", {})
    return (
        "ag_dispatch_liveness_ack_expiry_privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"conflict={checks.get('cas_conflict_reported')} "
        f"runbook={checks.get('runbook_complete')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
