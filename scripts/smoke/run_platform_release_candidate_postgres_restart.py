#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.release_candidate_postgres import (  # noqa: E402
    RELEASE_CANDIDATE_POSTGRES_SCHEMA_VERSION,
    build_release_candidate_postgres_restart_evidence,
)
from run_platform_postgres_restart_smoke import (  # noqa: E402
    SMOKE_ENV as SOURCE_SMOKE_ENV,
    run_smoke as run_source_smoke,
)


ENABLE_ENV = "NEX_S140_RELEASE_CANDIDATE_POSTGRES_RESTART"
RestartRunner = Callable[[Mapping[str, str]], Mapping[str, Any]]


def run_platform_release_candidate_postgres_restart(
    environ: Mapping[str, str] | None = None,
    *,
    restart_runner: RestartRunner = run_source_smoke,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ENABLE_ENV) != "1":
        return {
            "schema_version": RELEASE_CANDIDATE_POSTGRES_SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{ENABLE_ENV} is not enabled.",
            "actual_postgresql_execution": False,
            "next_slice": "1396",
        }

    env[SOURCE_SMOKE_ENV] = "1"
    try:
        source = dict(restart_runner(env))
    except Exception:
        source = {
            "status": "FAIL",
            "failure_code": "release_candidate_postgres_restart_execution_failed",
        }
    evidence = build_release_candidate_postgres_restart_evidence(source)
    gate = dict(evidence["gate_evidence"])
    evidence.update(
        actual_postgresql_execution=True,
        source_projection={
            "status": source.get("status"),
            "failure_code": source.get("failure_code"),
            "service_id": source.get("service_id"),
            "service_count": source.get("service_count"),
            "migration_count_per_generation": source.get(
                "migration_count_per_generation"
            ),
            "restored_count": source.get("restored_count"),
            "cleaned_count": source.get("cleaned_count"),
            "absence_count": source.get("absence_count"),
        },
        next_slice="1397" if gate.get("status") == "PASS" else "blocked",
    )
    return evidence


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or "FAIL")
    if status == "SKIPPED":
        return "platform_release_candidate_postgres_restart=skip next=1396"
    gate = dict(result.get("gate_evidence") or {})
    metrics = dict(gate.get("metrics") or {})
    return (
        "platform_release_candidate_postgres_restart="
        f"{status.lower()} databases={metrics.get('database_count', 0)} "
        f"restored={metrics.get('restored_database_count', 0)} "
        f"residue={metrics.get('database_residue_count', 0)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_release_candidate_postgres_restart()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
