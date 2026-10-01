#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-mo", ROOT / "scripts" / "smoke"):
    sys.path.insert(0, str(path))

from nex_mo.mvp_oa_transition_handoff import (  # noqa: E402
    build_mo_mvp_oa_transition_candidate,
    verify_mo_mvp_oa_transition_handoff,
)
from run_mo_operations_live_acceptance import (  # noqa: E402
    ACTIVATION_ENV as OPERATIONS_ACTIVATION_ENV,
    assert_evidence_redacted,
    run_mo_operations_live_acceptance,
)


SCHEMA_VERSION = "mo_mvp_acceptance_postgres_live_smoke.v1"
ACTIVATION_ENV = "NEX_MO_MVP_ACCEPTANCE_POSTGRES_LIVE_SMOKE"
EXPECTED_DATABASE_IDENTITY = {
    "database_name": "nex_mo_test",
    "database_user": "nex_mo_user",
}
EXPECTED_MODELS = {
    "embedding": "Qwen3-Embedding-4B",
    "reranking": "Qwen3-Reranker-4B",
    "generation": "Qwen3.5-4B",
}

OperationsRunner = Callable[[Mapping[str, str]], Mapping[str, Any]]
Clock = Callable[[], datetime]


def run_mo_mvp_acceptance_postgres_live_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    operations_runner: OperationsRunner = run_mo_operations_live_acceptance,
    clock: Clock | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "1199",
            "requirement": "S120",
            "status": "SKIPPED",
            "skip_reason": f"{ACTIVATION_ENV} is not enabled.",
        }
    observed_at = (clock or (lambda: datetime.now(UTC)))()
    if observed_at.tzinfo is None:
        return _failure("clock_timezone_required")

    live_env = {**env, OPERATIONS_ACTIVATION_ENV: "1"}
    try:
        source = dict(operations_runner(live_env))
        if source.get("status") != "PASS":
            return _redacted_failure(
                "operations_live_acceptance_failed",
                source_failure_code=str(source.get("failure_code") or "unknown"),
                env=live_env,
            )
        candidate = build_mo_mvp_oa_transition_candidate(
            generated_at=observed_at,
            root=root,
        )
        handoff = verify_mo_mvp_oa_transition_handoff(candidate)
    except Exception as exc:
        return _redacted_failure(
            "mvp_live_smoke_execution_failed",
            source_failure_code=type(exc).__name__,
            env=live_env,
        )

    source_checks = _mapping(source.get("checks"))
    summary = _mapping(source.get("summary"))
    cleanup = _mapping(source.get("cleanup"))
    checks = {
        "source_acceptance_passed": source.get("status") == "PASS"
        and bool(source_checks)
        and all(source_checks.values()),
        "actual_test_database_identity": source.get("database_identity")
        == EXPECTED_DATABASE_IDENTITY,
        "actual_postgres_cleanup_complete": cleanup.get("residue") == 0,
        "three_provider_requests_succeeded": summary.get("provider_success_count")
        == 3,
        "exact_provider_models_returned": summary.get("model_match_count") == 3,
        "three_capabilities_ready": summary.get("ready_capability_count") == 3,
        "ssh_runtime_bfloat16_healthy": summary.get(
            "runtime_ready_capability_count"
        )
        == 3,
        "oa_transition_manifest_verified": handoff.get("status") == "VERIFIED"
        and candidate.get("manifest_status") == "SEALED",
    }
    postgres_passed = all(
        checks[name]
        for name in (
            "source_acceptance_passed",
            "actual_test_database_identity",
            "actual_postgres_cleanup_complete",
        )
    )
    live_passed = all(
        checks[name]
        for name in (
            "source_acceptance_passed",
            "three_provider_requests_succeeded",
            "exact_provider_models_returned",
            "three_capabilities_ready",
            "ssh_runtime_bfloat16_healthy",
        )
    )
    handoff_passed = checks["oa_transition_manifest_verified"]
    passed = all(checks.values())
    timestamp = _timestamp(observed_at)
    evidence = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1199",
        "requirement": "S120",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo.mvp_acceptance.live_smoke_failed",
        "checks": checks,
        "failed_checks": [name for name, value in checks.items() if not value],
        "summary": {
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
            "provider_success_count": _nonnegative_int(
                summary.get("provider_success_count")
            ),
            "model_match_count": _nonnegative_int(summary.get("model_match_count")),
            "ready_capability_count": _nonnegative_int(
                summary.get("ready_capability_count")
            ),
            "runtime_ready_capability_count": _nonnegative_int(
                summary.get("runtime_ready_capability_count")
            ),
            "cleanup_residue": _nonnegative_int(cleanup.get("residue")),
        },
        "database_identity": dict(EXPECTED_DATABASE_IDENTITY),
        "acceptance_gate_evidence": {
            "postgres_smoke": {
                "status": "PASS" if postgres_passed else "FAIL",
                "observed_at": timestamp,
                "backend": "postgresql",
                "database": "nex_mo_test",
                "zero_residue": cleanup.get("residue") == 0,
            },
            "live_provider_acceptance": {
                "status": "PASS" if live_passed else "FAIL",
                "observed_at": timestamp,
                "provider_models": dict(EXPECTED_MODELS),
                "ready_capabilities": _nonnegative_int(
                    summary.get("ready_capability_count")
                ),
                "failed_calls": 0 if summary.get("provider_success_count") == 3 else 1,
                "explicit_bfloat16": summary.get(
                    "runtime_ready_capability_count"
                )
                == 3,
            },
            "oa_transition_handoff": {
                "status": "PASS" if handoff_passed else "FAIL",
                "observed_at": timestamp,
                "target_service": "nex-oa",
                "manifest_status": candidate.get("manifest_status"),
            },
        },
        "redaction": {
            "raw_provider_payloads_included": False,
            "provider_endpoints_or_keys_included": False,
            "database_url_or_password_included": False,
            "ssh_target_or_process_commands_included": False,
        },
        "next_slice": "1200" if passed else "blocked",
    }
    assert_evidence_redacted(evidence, live_env)
    return evidence


def _redacted_failure(
    failure_code: str,
    *,
    source_failure_code: str,
    env: Mapping[str, str],
) -> dict[str, Any]:
    evidence = _failure(
        failure_code,
        source_failure_code=source_failure_code,
    )
    assert_evidence_redacted(evidence, env)
    return evidence


def _failure(
    failure_code: str,
    *,
    source_failure_code: str | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1199",
        "requirement": "S120",
        "status": "FAIL",
        "failure_code": failure_code,
        "checks": {},
        "failed_checks": [failure_code],
        "acceptance_gate_evidence": {},
        "next_slice": "blocked",
    }
    if source_failure_code:
        evidence["source_failure_code"] = source_failure_code
    return evidence


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"mo_mvp_acceptance_postgres_live_smoke=skipped reason={ACTIVATION_ENV}"
    summary = _mapping(evidence.get("summary"))
    return (
        "mo_mvp_acceptance_postgres_live_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"providers={summary.get('provider_success_count', 0)}/3 "
        f"models={summary.get('model_match_count', 0)}/3 "
        f"runtime={summary.get('runtime_ready_capability_count', 0)}/3 "
        f"cleanup={summary.get('cleanup_residue', 'not-run')} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_mvp_acceptance_postgres_live_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
