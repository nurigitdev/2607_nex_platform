#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p5_s6_postgres_smoke as p5_s6
import run_p5_s8_postgres_smoke as p5_s8

SCHEMA_VERSION = "p5_planning_execution_foundation_closure.v1"
SMOKE_ENV = "NEX_AE_P5_CLOSURE"
DATABASE_ENV = p5_s8.DATABASE_ENV
P5_MIGRATIONS = tuple(
    Path(f"database/nex-ae-api/migrations/210{number}_{name}.sql")
    for number, name in (
        (0, "ae_prompt_registry_hardening"),
        (1, "ae_work_intent"),
        (2, "ae_agent_context"),
        (3, "ae_capability_plan_validation"),
        (4, "ae_executable_plan"),
        (5, "ae_executable_step_generalization"),
        (6, "ae_step_result"),
    )
)
P5_RUNTIME_SOURCES = tuple(
    Path(f"services/nex-ae-api/nex_ae_api/{name}.py")
    for name in (
        "work_intent",
        "agent_context",
        "planning_capabilities",
        "agent_plans",
        "plan_validation",
        "executable_plans",
        "step_results",
        "multi_step_engine",
        "step_executors",
        "plan_finalization",
    )
)
P5_AS_BUILT_RECORDS = tuple(
    Path(f"docs/slices/{name}.md")
    for name in (
        "p5_s1_work_intent_prompt_registry_hardening",
        "p5_s2_agent_context",
        "p5_s3_capability_snapshot_deterministic_plans",
        "p5_s4_plan_validator",
        "p5_s1_s4_hash_utility_consolidation",
        "p5_s5_deterministic_compiler_executable_plan",
        "p5_s6_multi_step_engine_step_result",
        "p5_s7_step_executors",
        "p5_s8_plan_finalization",
        "p5_s9_planning_execution_foundation_closure",
    )
)
P5_CANONICAL_DOCS = (
    Path("docs/transition/P5/README.md"),
    Path("docs/transition/P5/P5_Agent_Planning_and_Execution_Foundation_SRS_v1.1.md"),
    Path("docs/transition/P5/P5_Source_Audit_and_Implementation_Plan_v1.1.md"),
)
FORBIDDEN_NSL_WC_TOKENS = (
    "import nex_nsl",
    "from nex_nsl",
    "NSLExecutionId",
    "nsl_execution_id",
    "import nex_wc",
    "from nex_wc",
    "WorkItemRepository",
    "create_work_item(",
    "wc_client",
)
FORBIDDEN_DIRECT_PROVIDER_IMPORTS = (
    "import httpx",
    "from httpx",
    "import requests",
    "from requests",
    "import urllib.request",
    "from urllib.request",
)

EvidenceRunner = Callable[[Mapping[str, str]], dict[str, Any]]


def run_p5_planning_execution_foundation_closure(
    environ: Mapping[str, str] | None = None,
    *,
    root: Path = ROOT,
    restart_runner: EvidenceRunner = p5_s6.run_p5_s6_postgres_smoke,
    journey_runner: EvidenceRunner = p5_s8.run_p5_s8_postgres_smoke,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "closure_schema_version": SCHEMA_VERSION,
            "slice": "P5-S9",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    static = _static_evidence(root)
    restart = restart_runner({**env, p5_s6.SMOKE_ENV: "1"})
    journey = journey_runner({**env, p5_s8.SMOKE_ENV: "1"})
    restart_checks = dict(restart.get("checks") or {})
    journey_checks = dict(journey.get("checks") or {})

    checks = {
        **static["checks"],
        "actual_restart_postgresql_smoke_passed": _actual_postgres_passed(restart),
        "restart_and_dedup_guards_passed": _required_checks_passed(
            restart_checks,
            (
                "runtime_job_deduplicated",
                "immutable_result_replay",
                "restart_does_not_reexecute",
                "write_identity_null",
            ),
        ),
        "restart_smoke_zero_residue": _cleanup_remaining(restart) == 0,
        "actual_complete_journey_postgresql_smoke_passed": (
            _actual_postgres_passed(journey)
            and (journey.get("migration") or {}).get("latest_version")
            == p5_s8.REQUIRED_MIGRATION
        ),
        "complete_journey_lineage_and_finalization_passed": _required_checks_passed(
            journey_checks,
            (
                "s_e_uuid_lineage",
                "atomic_idempotent_restart",
                "chat_invoked_once",
                "terminal_results_persisted",
                "required_step_results_verified",
                "agent_result_immutable_replay",
                "workspace_delivery_pending",
            ),
        ),
        "publication_ack_barrier_preserved": journey_checks.get(
            "execution_waits_for_ack"
        )
        is True,
        "complete_journey_zero_nsl_write_identity": journey_checks.get(
            "zero_nsl_write_identity"
        )
        is True,
        "complete_journey_zero_residue": _cleanup_remaining(journey) == 0,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "P5-S9",
        "requirement": "P5 Agent Planning and Execution Foundation",
        "status": "PASS" if not failed_checks else "FAIL",
        "checks": checks,
        "failed_checks": failed_checks,
        "excluded_scope_hits": static["excluded_scope_hits"],
        "restart": _postgres_projection(restart),
        "journey": _postgres_projection(journey),
        "deferred": [
            "P6 NSL v0.2 READ integration",
            "LOCAL_SKILL execution",
            "WC delegation and DELEGATE_WORK execution",
            "required delivery publication, ACK, and terminal success transition",
        ],
    }


def _static_evidence(root: Path) -> dict[str, Any]:
    sources = _read_sources(root, P5_RUNTIME_SOURCES)
    nsl_wc_hits = _token_hits(sources, FORBIDDEN_NSL_WC_TOKENS)
    provider_hits = _token_hits(sources, FORBIDDEN_DIRECT_PROVIDER_IMPORTS)
    readme = _read_text(root / P5_CANONICAL_DOCS[0])
    implementation = _read_text(root / P5_CANONICAL_DOCS[2])
    step_result = sources.get(str(P5_RUNTIME_SOURCES[6]), "")
    return {
        "checks": {
            "p5_migration_chain_present": all(
                (root / path).is_file() for path in P5_MIGRATIONS
            ),
            "p5_runtime_modules_present": all(
                (root / path).is_file() for path in P5_RUNTIME_SOURCES
            ),
            "p5_canonical_docs_present": all(
                (root / path).is_file() for path in P5_CANONICAL_DOCS
            ),
            "p5_as_built_records_complete": all(
                (root / path).is_file() for path in P5_AS_BUILT_RECORDS
            ),
            "p5_canonical_status_closed": (
                "P5 IMPLEMENTATION COMPLETE" in readme
                and "| P5-S9 | COMPLETE |" in readme
                and "P5-S1..P5-S9 COMPLETE" in implementation
                and "**Status:** COMPLETE"
                in implementation.split("### P5-S9", maxsplit=1)[-1]
            ),
            "nsl_wc_runtime_coupling_absent": not nsl_wc_hits,
            "direct_provider_client_absent": not provider_hits,
            "step_result_write_identity_fail_closed": (
                '"business_operation_id": None' in step_result
                and '"operation_fingerprint": None' in step_result
                and 'result["business_operation_id"] is not None' in step_result
                and 'result["operation_fingerprint"] is not None' in step_result
            ),
        },
        "excluded_scope_hits": {
            "nsl_wc": nsl_wc_hits,
            "direct_provider_imports": provider_hits,
        },
    }


def _actual_postgres_passed(evidence: Mapping[str, Any]) -> bool:
    checks = dict(evidence.get("checks") or {})
    return (
        evidence.get("status") == "PASS"
        and evidence.get("actual_postgres") is True
        and evidence.get("database") == p5_s8.EXPECTED_DATABASE
        and evidence.get("role") == p5_s8.EXPECTED_ROLE
        and bool(checks)
        and all(checks.values())
    )


def _required_checks_passed(checks: Mapping[str, Any], names: Sequence[str]) -> bool:
    return all(checks.get(name) is True for name in names)


def _cleanup_remaining(evidence: Mapping[str, Any]) -> int | None:
    value = (evidence.get("cleanup_counts") or {}).get("remaining")
    return value if isinstance(value, int) else None


def _postgres_projection(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": evidence.get("status"),
        "actual_postgres": evidence.get("actual_postgres", False),
        "database": evidence.get("database"),
        "role": evidence.get("role"),
        "migration": dict(evidence.get("migration") or {}),
        "check_count": len(evidence.get("checks") or {}),
        "row_counts": dict(evidence.get("row_counts") or {}),
        "cleanup_remaining": _cleanup_remaining(evidence),
    }


def _read_sources(root: Path, paths: Sequence[Path]) -> dict[str, str]:
    return {str(path): _read_text(root / path) for path in paths}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _token_hits(sources: Mapping[str, str], tokens: Sequence[str]) -> list[str]:
    return sorted(
        f"{path}:{token}"
        for path, source in sources.items()
        for token in tokens
        if token in source
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    restart = evidence.get("restart") or {}
    journey = evidence.get("journey") or {}
    rows = journey.get("row_counts") or {}
    return (
        "p5_planning_execution_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"restart={str(restart.get('status') or 'not-run').lower()} "
        f"journey={str(journey.get('status') or 'not-run').lower()} "
        f"migrations={(journey.get('migration') or {}).get('planned_count', 0)} "
        f"results={rows.get('step_result', 0)}/{rows.get('agent_result', 0)} "
        f"deliveries={rows.get('result_delivery', 0)} "
        f"cleanup={journey.get('cleanup_remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    p5_s8.load_env_file(ROOT / ".env.local")
    evidence = run_p5_planning_execution_foundation_closure()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
