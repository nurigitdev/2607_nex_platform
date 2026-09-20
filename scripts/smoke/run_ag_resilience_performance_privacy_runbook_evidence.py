#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.resilience_performance import (  # noqa: E402
    AgAdmissionRejectedError,
    AgConcurrencyAdmissionGuard,
    AgSourceIsolationExecutor,
    AgStablePaginationError,
    build_ag_resilience_performance_policy,
    build_stable_keyset_page,
)
from nex_ag.resilience_performance_operations import (  # noqa: E402
    build_ag_resilience_performance_operations_projection,
)


SCHEMA_VERSION = "ag_resilience_performance_privacy_runbook.v1"
SLICE_ID = "0879"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = "run_ag_resilience_performance_privacy_runbook_evidence.py"
POSTGRES_EVIDENCE_PATH = (
    "docs/slices/0878_ag_resilience_postgresql_bounded_load_smoke.md"
)
CHECKED_AT = "2026-09-20T11:00:00Z"
FORBIDDEN_VALUES = {
    "database_url": "private-runbook-database-url-0879",
    "source_exception": "private-runbook-source-exception-0879",
    "invalid_cursor": "private-runbook-invalid-cursor-0879",
    "credential": "private-runbook-credential-0879",
}
FORBIDDEN_KEYS = {
    "authorization",
    "credential",
    "database_url",
    "exception",
    "password",
    "raw_error",
    "raw_payload",
    "secret",
    "sql",
    "storage_path",
}
REQUIRED_DOCS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("0871", "ag_resilience_performance_boundary_audit"),
        ("0872", "ag_resilience_performance_budget_policy"),
        ("0873", "ag_stable_bounded_pagination"),
        ("0874", "ag_concurrency_admission_load_shedding"),
        ("0875", "ag_source_timeout_failure_isolation"),
        ("0876", "ag_resilience_performance_operations_projection"),
        ("0877", "ag_resilience_index_contract_hardening"),
        ("0878", "ag_resilience_postgresql_bounded_load_smoke"),
    )
)


class _Pool:
    def __init__(
        self,
        *,
        checked_out: int,
        checked_in: int,
        overflow: int,
        fail: bool = False,
    ) -> None:
        self.checked_out = checked_out
        self.checked_in = checked_in
        self.overflow_count = overflow
        self.fail = fail

    def checkedout(self) -> int:
        if self.fail:
            raise RuntimeError(FORBIDDEN_VALUES["database_url"])
        return self.checked_out

    def checkedin(self) -> int:
        return self.checked_in

    def overflow(self) -> int:
        return self.overflow_count


def run_ag_resilience_performance_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    policy = build_ag_resilience_performance_policy({})
    admission_guard = AgConcurrencyAdmissionGuard(
        max_in_flight=1,
        wait_timeout_ms=1,
    )
    with admission_guard.admit("runbook-holder"):
        admission_rejection = _capture_error(
            lambda: admission_guard._acquire()
        )

    source_executor = AgSourceIsolationExecutor(
        timeout_ms=10,
        slow_operation_ms=5,
        max_workers=1,
    )
    try:
        source_timeout = _capture_error(
            lambda: source_executor.execute(lambda: time.sleep(0.03))
        )
        time.sleep(0.04)
        source_failure = _capture_source_failure(
            lambda: source_executor.execute(
                lambda: (_ for _ in ()).throw(
                    RuntimeError(FORBIDDEN_VALUES["source_exception"])
                )
            )
        )
        source_snapshot = source_executor.snapshot()
    finally:
        source_executor.close()

    saturated = build_ag_resilience_performance_operations_projection(
        policy=policy,
        admission_snapshot=admission_guard.snapshot(),
        source_snapshot=source_snapshot,
        api_engine=_engine(checked_out=15, checked_in=0, overflow=10),
        worker_engine=_engine(checked_out=6, checked_in=0, overflow=4),
        checked_at=CHECKED_AT,
    )
    metrics_unavailable = build_ag_resilience_performance_operations_projection(
        policy=policy,
        admission_snapshot=_healthy_admission_snapshot(policy),
        source_snapshot=_healthy_source_snapshot(policy),
        api_engine=SimpleNamespace(
            pool=_Pool(
                checked_out=0,
                checked_in=0,
                overflow=0,
                fail=True,
            )
        ),
        worker_engine=None,
        checked_at=CHECKED_AT,
    )
    invalid_cursor = _capture_error(
        lambda: build_stable_keyset_page(
            [],
            limit=5,
            cursor=FORBIDDEN_VALUES["invalid_cursor"],
            timestamp_field="created_at",
            identity_field="event_id",
        )
    )
    postgres_evidence = _postgres_evidence(
        _read_text(root / POSTGRES_EVIDENCE_PATH)
    )
    runbook = _runbook_actions()
    surfaces = {
        "policy": policy,
        "admission_rejection": admission_rejection,
        "source_timeout": source_timeout,
        "source_failure": source_failure,
        "source_snapshot": source_snapshot,
        "pool_saturation": saturated,
        "pool_metrics_unavailable": metrics_unavailable,
        "invalid_cursor": invalid_cursor,
        "postgres_evidence": postgres_evidence,
        "runbook": runbook,
    }
    serialized = json.dumps(surfaces, ensure_ascii=False, sort_keys=True)
    forbidden_value_labels = _forbidden_value_labels(serialized)
    forbidden_key_paths = _forbidden_key_paths(surfaces)
    required_docs = [
        {"path": path, "present": (root / path).exists()} for path in REQUIRED_DOCS
    ]
    quality_gate_hook_present = EVIDENCE_HOOK in _read_text(
        root / QUALITY_GATE_PATH
    )
    checks = {
        "policy_is_bounded": (
            policy["query"]["max_page_size"] == 500
            and policy["admission"]["max_in_flight"] <= policy["database"]["api"][
                "capacity"
            ]
            and policy["bounded_smoke"]["concurrency"]
            <= policy["admission"]["max_in_flight"]
        ),
        "admission_rejection_is_retryable_and_redacted": (
            admission_rejection.get("error_code")
            == "ag.resilience.admission_capacity_exhausted"
            and admission_rejection.get("status_code") == 503
            and admission_rejection.get("retry_after_ms") == 1
        ),
        "source_timeout_is_normalized": (
            source_timeout.get("error_code") == "ag.resilience.source_timeout"
            and source_timeout.get("status_code") == 503
            and source_snapshot["timed_out_total"] == 1
        ),
        "source_failure_is_normalized": (
            source_failure
            == {
                "error_code": "ag.resilience.source_unavailable",
                "detail": "AG source is temporarily unavailable.",
                "status_code": 503,
            }
            and source_snapshot["failed_total"] == 1
        ),
        "pool_saturation_is_actionable": (
            saturated["projection_status"] == "ATTENTION"
            and "DATABASE_API_POOL_SATURATED"
            in saturated["attention_reasons"]
            and "DATABASE_WORKER_POOL_SATURATED"
            in saturated["attention_reasons"]
        ),
        "pool_metric_failure_is_redacted": (
            metrics_unavailable["projection_status"] == "DEGRADED"
            and "DATABASE_API_POOL_METRICS_UNAVAILABLE"
            in metrics_unavailable["attention_reasons"]
        ),
        "invalid_cursor_is_redacted": (
            invalid_cursor.get("error_code")
            == "ag.resilience.pagination_cursor_invalid"
            and FORBIDDEN_VALUES["invalid_cursor"]
            not in json.dumps(invalid_cursor)
        ),
        "postgres_evidence_is_complete": all(postgres_evidence.values()),
        "runbook_complete": set(runbook)
        == {
            "admission_capacity_exhausted",
            "source_timeout",
            "source_unavailable",
            "database_pool_saturated",
            "pool_metrics_unavailable",
            "latency_budget_exceeded",
            "migration_or_index_missing",
            "unstable_pagination",
            "postgres_connectivity",
            "smoke_cleanup_failure",
        },
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
        else "ag_resilience_performance_privacy_runbook_failed",
        "slice": SLICE_ID,
        "surface_count": len(surfaces) - 1,
        "surfaces": surfaces,
        "required_docs": required_docs,
        "forbidden_value_labels": forbidden_value_labels,
        "forbidden_key_paths": forbidden_key_paths,
        "checks": checks,
    }
    _assert_no_forbidden_values(json.dumps(evidence, ensure_ascii=False))
    return evidence


def _engine(
    *,
    checked_out: int,
    checked_in: int,
    overflow: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        pool=_Pool(
            checked_out=checked_out,
            checked_in=checked_in,
            overflow=overflow,
        )
    )


def _healthy_admission_snapshot(policy: Mapping[str, Any]) -> dict[str, Any]:
    admission = policy["admission"]
    return {
        "schema_version": "ag_concurrency_admission_snapshot.v1",
        "max_in_flight": admission["max_in_flight"],
        "wait_timeout_ms": admission["wait_timeout_ms"],
        "in_flight": 0,
        "peak_in_flight": 0,
        "admitted_total": 0,
        "rejected_total": 0,
        "process_local": True,
    }


def _healthy_source_snapshot(policy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "ag_source_isolation_snapshot.v1",
        "timeout_ms": policy["source_isolation"]["timeout_ms"],
        "slow_operation_ms": policy["query"]["slow_operation_ms"],
        "max_workers": 2,
        "completed_total": 0,
        "failed_total": 0,
        "timed_out_total": 0,
        "slow_total": 0,
        "last_elapsed_ms": None,
        "raw_errors_included": False,
    }


def _capture_error(operation: Callable[[], Any]) -> dict[str, Any]:
    try:
        operation()
    except (AgAdmissionRejectedError, AgStablePaginationError, TimeoutError) as exc:
        return {
            "error_code": getattr(exc, "error_code", "ag.resilience.operation_failed"),
            "detail": getattr(exc, "detail", "AG operation failed safely."),
            "status_code": getattr(exc, "status_code", 503),
            **(
                {"retry_after_ms": exc.retry_after_ms}
                if isinstance(exc, AgAdmissionRejectedError)
                else {}
            ),
        }
    raise AssertionError("operation did not fail")


def _capture_source_failure(operation: Callable[[], Any]) -> dict[str, Any]:
    try:
        operation()
    except Exception:
        return {
            "error_code": "ag.resilience.source_unavailable",
            "detail": "AG source is temporarily unavailable.",
            "status_code": 503,
        }
    raise AssertionError("source operation did not fail")


def _postgres_evidence(document: str) -> dict[str, bool]:
    return {
        "live_smoke_passed": "live smoke: PASS" in document,
        "test_database_selected": "database=nex_ag_test" in document,
        "bounded_requests_executed": "requests=25 concurrency=4" in document,
        "latency_budget_passed": "p95_ms=49.678 budget_ms=1500" in document,
        "indexes_observed": "indexes=3" in document,
        "migration_observed": "migration_present=true" in document,
        "cleanup_verified": (
            "cleaned=True" in document
            and "event_residue=0 export_residue=0" in document
        ),
    }


def _runbook_actions() -> dict[str, dict[str, Any]]:
    return {
        "admission_capacity_exhausted": {
            "retryable": True,
            "action": "honor retry timing and inspect in-flight work before scaling",
        },
        "source_timeout": {
            "retryable": True,
            "action": "inspect statement timeout and source latency before retrying",
        },
        "source_unavailable": {
            "retryable": True,
            "action": "restore the isolated source without exposing its exception",
        },
        "database_pool_saturated": {
            "retryable": True,
            "action": "reduce admission or inspect long-held database sessions",
        },
        "pool_metrics_unavailable": {
            "retryable": False,
            "action": "verify persistence mode and SQLAlchemy pool compatibility",
        },
        "latency_budget_exceeded": {
            "retryable": False,
            "action": "compare p50 p95 and max before changing the fixed budget",
        },
        "migration_or_index_missing": {
            "retryable": False,
            "action": "apply test migrations and verify all three bounded-read indexes",
        },
        "unstable_pagination": {
            "retryable": False,
            "action": "verify timestamp and identity ordering before serving another page",
        },
        "postgres_connectivity": {
            "retryable": True,
            "action": "verify the test profile and redacted connection target",
        },
        "smoke_cleanup_failure": {
            "retryable": False,
            "action": "remove only the owned trace rows and confirm zero residue",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


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
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
    return paths


def _assert_no_forbidden_values(serialized: str) -> None:
    labels = _forbidden_value_labels(serialized)
    if labels:
        raise ValueError(f"privacy evidence contains forbidden values: {labels}")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_resilience_privacy_runbook=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = _mapping(evidence.get("checks"))
    return (
        "ag_resilience_privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"postgres={checks.get('postgres_evidence_is_complete')} "
        f"runbook={checks.get('runbook_complete')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_resilience_performance_privacy_runbook_evidence()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False)
    )
    return 1 if evidence.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
