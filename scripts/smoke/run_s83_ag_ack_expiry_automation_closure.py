#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.liveness_ack_expiry_automation import (  # noqa: E402
    ACK_EXPIRY_AUTOMATION_ENABLED_ENV,
    build_liveness_ack_expiry_automation_policy,
)
from nex_ag.liveness_ack_expiry_automation_cli import (  # noqa: E402
    execute_liveness_ack_expiry_automation_cli,
)
from nex_ag.liveness_ack_expiry_automation_operations import (  # noqa: E402
    build_liveness_ack_expiry_automation_operations_projection,
)
from nex_ag.operator_review_liveness_ack import (  # noqa: E402
    OperatorReviewLivenessAckStateStore,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
)
from run_ag_ack_expiry_automation_privacy_runbook_evidence import (  # noqa: E402
    run_ag_ack_expiry_automation_privacy_runbook_evidence as run_privacy_runbook,
)
from run_ag_ack_expiry_automation_privacy_runbook_evidence import (  # noqa: E402
    summary_line as privacy_summary_line,
)


SCHEMA_VERSION = "s83_ag_ack_expiry_automation_closure.v1"
SLICE_RANGE = "0821-0830"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_SMOKE_DOC = "docs/slices/0828_ag_ack_expiry_automation_postgres_smoke.md"
PRIVACY_RUNBOOK_DOC = "docs/slices/0829_ag_ack_expiry_automation_privacy_runbook.md"
SOURCE_TABLE = "ag_op_review_ack_state"
EVENT_TABLE = "service_operational_events"
MAX_IDENTIFIER_LENGTH = 30
OBSERVED_AT = "2026-09-18T07:00:00Z"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/liveness_ack_expiry_automation.py",
    "services/nex-ag/nex_ag/liveness_ack_expiry_automation_cli.py",
    "services/nex-ag/nex_ag/liveness_ack_expiry_automation_operations.py",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_ack_expiry_automation_boundary_audit.py",
    "scripts/smoke/run_ag_ack_expiry_automation_postgres_smoke.py",
    "scripts/smoke/run_ag_ack_expiry_automation_privacy_runbook_evidence.py",
    "scripts/smoke/run_s83_ag_ack_expiry_automation_closure.py",
    "tests/test_ag_ack_expiry_automation_boundary_audit.py",
    "tests/test_nex_ag_liveness_ack_expiry_automation_policy.py",
    "tests/test_nex_ag_liveness_ack_expiry_automation_tick_plan.py",
    "tests/test_nex_ag_liveness_ack_expiry_automation_tick_execution.py",
    "tests/test_nex_ag_liveness_ack_expiry_automation_cli.py",
    "tests/test_nex_ag_liveness_ack_expiry_automation_events.py",
    "tests/test_nex_ag_liveness_ack_expiry_automation_operations.py",
    "tests/test_ag_ack_expiry_automation_postgres_smoke.py",
    "tests/test_ag_ack_expiry_automation_privacy_runbook_evidence.py",
    "tests/test_s83_ag_ack_expiry_automation_closure.py",
    "docs/README.md",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0821", "ag_ack_expiry_automation_boundary_audit"),
            ("0822", "ag_ack_expiry_automation_policy"),
            ("0823", "ag_ack_expiry_automation_tick_plan"),
            ("0824", "ag_ack_expiry_automation_tick_execution"),
            ("0825", "ag_ack_expiry_automation_cli"),
            ("0826", "ag_ack_expiry_automation_lifecycle_events"),
            ("0827", "ag_ack_expiry_automation_operations_projection"),
            ("0828", "ag_ack_expiry_automation_postgres_smoke"),
            ("0829", "ag_ack_expiry_automation_privacy_runbook"),
            ("0830", "s83_ag_ack_expiry_automation_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "quality_gate_boundary",
        QUALITY_GATE_PATH,
        "run_ag_ack_expiry_automation_boundary_audit.py",
    ),
    (
        "quality_gate_postgres",
        QUALITY_GATE_PATH,
        "run_ag_ack_expiry_automation_postgres_smoke.py",
    ),
    (
        "quality_gate_privacy",
        QUALITY_GATE_PATH,
        "run_ag_ack_expiry_automation_privacy_runbook_evidence.py",
    ),
    (
        "quality_gate_closure",
        QUALITY_GATE_PATH,
        "run_s83_ag_ack_expiry_automation_closure.py",
    ),
    (
        "disabled_by_default",
        "services/nex-ag/nex_ag/liveness_ack_expiry_automation.py",
        "disabled_by_default",
    ),
    (
        "external_scheduler_mode",
        "services/nex-ag/nex_ag/liveness_ack_expiry_automation.py",
        "externally_scheduled_bounded_run_once",
    ),
    (
        "confirmation_guard",
        "services/nex-ag/nex_ag/liveness_ack_expiry_automation.py",
        "confirm_tick_required",
    ),
    (
        "database_env_allowlist",
        "services/nex-ag/nex_ag/liveness_ack_expiry_automation_cli.py",
        "ACK_EXPIRY_AUTOMATION_DATABASE_ENVS",
    ),
    (
        "worker_pool",
        "services/nex-ag/nex_ag/liveness_ack_expiry_automation_cli.py",
        'workload="worker"',
    ),
    (
        "engine_cleanup",
        "services/nex-ag/nex_ag/liveness_ack_expiry_automation_cli.py",
        "engine.dispose()",
    ),
    (
        "external_scheduler_owner",
        "services/nex-ag/nex_ag/liveness_ack_expiry_automation_operations.py",
        '"owner": "external_scheduler"',
    ),
    (
        "operations_schema",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "dashboard_ack_expiry_automation",
    ),
    (
        "operations_fixture",
        "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json",
        '"ack_expiry_automation"',
    ),
    (
        "postgres_pass",
        POSTGRES_SMOKE_DOC,
        "ag_ack_expiry_automation_postgres_smoke=pass",
    ),
    (
        "postgres_non_skip",
        POSTGRES_SMOKE_DOC,
        "The result was not skipped",
    ),
    (
        "privacy_pass",
        PRIVACY_RUNBOOK_DOC,
        "ag_ack_expiry_automation_privacy_runbook=pass",
    ),
    (
        "docs_index_0830",
        "docs/README.md",
        "0830_s83_ag_ack_expiry_automation_closure.md",
    ),
)


def run_s83_ag_ack_expiry_automation_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = _required_file_results(root)
    token_checks = _token_results(root)
    postgres = _postgres_smoke_doc_evidence(root)
    privacy = _privacy_evidence(root)
    runtime = _runtime_evidence()
    identifiers = _identifier_evidence()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "identifier_lengths_safe": identifiers["within_limit"],
        "disabled_by_default": runtime["disabled_policy"]["enabled"] is False,
        "external_scheduler_bounded_run_once": runtime["execution_mode"]
        == "externally_scheduled_bounded_run_once",
        "idle_tick_completed": runtime["idle_tick"]["tick_status"] == "COMPLETED",
        "idle_tick_did_not_mutate": runtime["idle_tick"]["mutation_performed"]
        is False,
        "lifecycle_events_recorded": runtime["lifecycle_event_count"] == 2,
        "waiting_projection_verified": runtime["waiting_status"]
        == "WAITING_FIRST_RUN",
        "healthy_projection_verified": runtime["healthy_status"] == "HEALTHY",
        "continuous_loop_not_started": runtime["continuous_loop_started"] is False,
        "subprocess_not_started": runtime["subprocess_started"] is False,
        "postgres_smoke_used_test_db": postgres["uses_test_db"],
        "postgres_smoke_passed": postgres["summary_pass"],
        "postgres_smoke_not_skipped": postgres["not_skipped"],
        "postgres_cleanup_verified": postgres["cleanup_verified"],
        "privacy_runbook_passed": privacy["status"] == "PASS",
        "privacy_checks_passed": all(privacy["checks"].values()),
    }
    passed = all(checks.values())
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s83_ag_ack_expiry_automation_closure_failed",
        "slice_range": SLICE_RANGE,
        "boundary": "ag_ack_expiry_externally_scheduled_bounded_run_once",
        "source_tables": [SOURCE_TABLE, EVENT_TABLE],
        "new_tables": [],
        "new_indexes": [],
        "scheduler_owner": "external_scheduler",
        "closure_surfaces": [
            "boundary_audit",
            "policy_contract",
            "read_only_tick_plan",
            "confirmed_tick_execution",
            "executable_cli",
            "lifecycle_operational_events",
            "operations_projection",
            "test_db_postgres_smoke",
            "privacy_operator_runbook",
        ],
        "runtime": runtime,
        "postgres_smoke": postgres,
        "privacy_runbook": privacy,
        "identifiers": identifiers,
        "required_files": required_files,
        "token_checks": token_checks,
        "checks": checks,
        "summary": {
            "required_file_count": len(required_files),
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "token_check_count": len(token_checks),
            "missing_token_count": sum(not item["present"] for item in token_checks),
        },
    }


def _required_file_results(root: Path) -> list[dict[str, Any]]:
    return [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]


def _token_results(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for check_id, relative_path, token in TOKEN_CHECKS:
        path = root / relative_path
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        results.append(
            {
                "check_id": check_id,
                "path": relative_path,
                "present": token in content,
            }
        )
    return results


def _postgres_smoke_doc_evidence(root: Path) -> dict[str, Any]:
    path = root / POSTGRES_SMOKE_DOC
    content = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "doc": POSTGRES_SMOKE_DOC,
        "doc_present": path.is_file(),
        "uses_test_db": "nex_ag_test" in content,
        "summary_pass": "ag_ack_expiry_automation_postgres_smoke=pass" in content,
        "not_skipped": "The result was not skipped" in content,
        "migration_verified": "runs all NeX-AG test-profile migrations" in content,
        "state_transition_verified": "applied=1" in content,
        "lifecycle_events_verified": "events=2" in content,
        "cleanup_verified": "cleaned=1" in content,
    }


def _privacy_evidence(root: Path) -> dict[str, Any]:
    try:
        result = run_privacy_runbook(root)
    except Exception as exc:  # pragma: no cover - exercised by direct tests
        return {
            "status": "FAIL",
            "failure_code": "privacy_runbook_execution_failed",
            "error_type": type(exc).__name__,
            "summary_line": (
                "ag_ack_expiry_automation_privacy_runbook=fail "
                "failure=privacy_runbook_execution_failed"
            ),
            "checks": {
                "forbidden_values_absent": False,
                "forbidden_keys_absent": False,
                "external_scheduler_guardrails": False,
                "runbook_complete": False,
            },
        }
    selected_checks = {
        key: bool(result.get("checks", {}).get(key))
        for key in (
            "forbidden_values_absent",
            "forbidden_keys_absent",
            "external_scheduler_guardrails",
            "runbook_complete",
        )
    }
    return {
        "status": result.get("status"),
        "failure_code": result.get("failure_code"),
        "summary_line": privacy_summary_line(result),
        "surface_count": result.get("surface_count", 0),
        "checks": selected_checks,
    }


def _runtime_evidence() -> dict[str, Any]:
    disabled_policy = build_liveness_ack_expiry_automation_policy({})
    enabled_env = {ACK_EXPIRY_AUTOMATION_ENABLED_ENV: "1"}
    enabled_policy = build_liveness_ack_expiry_automation_policy(enabled_env)
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    result = execute_liveness_ack_expiry_automation_cli(
        OperatorReviewLivenessAckStateStore(),
        action="run_once",
        environ=enabled_env,
        request_id="req-s83-closure-idle",
        confirm_tick=True,
        observed_at=OBSERVED_AT,
        lifecycle_emitter=emitter,
    )
    waiting = build_liveness_ack_expiry_automation_operations_projection(
        InMemoryOperationalEventStore(),
        environ=enabled_env,
    )
    healthy = build_liveness_ack_expiry_automation_operations_projection(
        event_store,
        environ=enabled_env,
    )
    tick = result["tick_result"]
    return {
        "disabled_policy": disabled_policy,
        "execution_mode": enabled_policy["execution_mode"],
        "idle_tick": {
            "tick_status": tick["tick_status"],
            "candidate_count": tick["candidate_count"],
            "applied_count": tick["applied_count"],
            "mutation_performed": tick["mutation_performed"],
        },
        "lifecycle_event_count": len(event_store.list_events(limit=10)),
        "waiting_status": waiting["automation_status"],
        "healthy_status": healthy["automation_status"],
        "continuous_loop_started": healthy["scheduler"]["continuous_loop_started"],
        "subprocess_started": healthy["scheduler"]["subprocess_started"],
    }


def _identifier_evidence() -> dict[str, Any]:
    identifiers = {"source_table": SOURCE_TABLE, "event_table": EVENT_TABLE}
    lengths = {name: len(value) for name, value in identifiers.items()}
    return {
        "identifiers": identifiers,
        "lengths": lengths,
        "max_length": MAX_IDENTIFIER_LENGTH,
        "within_limit": all(
            length <= MAX_IDENTIFIER_LENGTH for length in lengths.values()
        ),
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        summary = evidence.get("summary", {})
        return (
            "s83_ag_ack_expiry_automation_closure=fail "
            f"missing_files={summary.get('missing_file_count')} "
            f"missing_tokens={summary.get('missing_token_count')}"
        )
    checks = evidence.get("checks", {})
    return (
        "s83_ag_ack_expiry_automation_closure=pass "
        f"slice_range={evidence.get('slice_range')} "
        f"scheduler={evidence.get('scheduler_owner')} "
        f"postgres={checks.get('postgres_smoke_passed')} "
        f"privacy={checks.get('privacy_runbook_passed')} "
        f"loop={evidence.get('runtime', {}).get('continuous_loop_started')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s83_ag_ack_expiry_automation_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
