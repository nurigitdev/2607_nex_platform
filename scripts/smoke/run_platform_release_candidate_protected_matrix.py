#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from nex_runtime.release_candidate_protected_matrix import (  # noqa: E402
    RELEASE_CANDIDATE_PROTECTED_MATRIX_SCHEMA_VERSION,
    build_release_candidate_protected_matrix,
)
import run_platform_generation_golden_scenarios as golden  # noqa: E402
import run_platform_release_candidate_admission as admission  # noqa: E402
import run_platform_release_candidate_assurance as assurance  # noqa: E402
import run_platform_release_candidate_browser_ag_operations as operations  # noqa: E402
import run_platform_release_candidate_live_providers as providers  # noqa: E402
import run_platform_release_candidate_postgres_restart as postgres  # noqa: E402


ENABLE_ENV = "NEX_S140_RELEASE_CANDIDATE_PROTECTED_MATRIX"
SourceRunner = Callable[..., Mapping[str, Any]]


def run_platform_release_candidate_protected_matrix(
    environ: Mapping[str, str] | None = None,
    *,
    admission_runner: SourceRunner = admission.run_platform_release_candidate_admission,
    golden_runner: SourceRunner = golden.run_platform_generation_golden_scenarios,
    postgres_runner: SourceRunner = postgres.run_platform_release_candidate_postgres_restart,
    provider_runner: SourceRunner = providers.run_platform_release_candidate_live_providers,
    operations_runner: SourceRunner = operations.run_platform_release_candidate_browser_ag_operations,
    assurance_runner: SourceRunner = assurance.run_platform_release_candidate_assurance,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ENABLE_ENV) != "1":
        return {
            "schema_version": RELEASE_CANDIDATE_PROTECTED_MATRIX_SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{ENABLE_ENV} is not enabled.",
            "actual_protected_execution": False,
            "next_slice": "1400",
        }

    source_env = {
        **env,
        postgres.ENABLE_ENV: "1",
        providers.ENABLE_ENV: "1",
        operations.ENABLE_ENV: "1",
        assurance.ENABLE_ENV: "1",
    }
    try:
        admission_source = dict(admission_runner(source_env))
        if admission_source.get("status") != "PASS":
            return _admission_failure(admission_source)
        golden_source = dict(golden_runner())
        postgres_source = dict(
            postgres_runner({**source_env, "NEX_MO_PROVIDER_MODE": "mock"})
        )
        provider_source = dict(provider_runner(source_env))
        trace_source_env = {
            **source_env,
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
        with _patched_environ(
            {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK"}
        ):
            operations_source = dict(operations_runner(trace_source_env))
            assurance_source = dict(assurance_runner(trace_source_env))
        result = build_release_candidate_protected_matrix(
            admission_source,
            golden_source,
            postgres_source,
            provider_source,
            operations_source,
            assurance_source,
        )
    except Exception:
        result = {
            "schema_version": RELEASE_CANDIDATE_PROTECTED_MATRIX_SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "release_candidate_protected_matrix_execution_failed",
            "readiness": "BLOCKED",
            "checks": {},
            "summary": {},
        }
    result.update(
        actual_protected_execution=(
            dict(result.get("summary") or {}).get("actual_protected_gate_count") == 5
        ),
        next_slice="1401" if result.get("status") == "PASS" else "blocked",
    )
    return result


def _admission_failure(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": RELEASE_CANDIDATE_PROTECTED_MATRIX_SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "release_candidate_protected_admission_failed",
        "readiness": "BLOCKED",
        "checks": {"protected_admission_passed": False},
        "source_projection": {
            "admission_status": source.get("status"),
            "issue_count": len(source.get("issues") or []),
        },
        "summary": {"actual_protected_gate_count": 0},
        "actual_protected_execution": False,
        "next_slice": "blocked",
    }


@contextmanager
def _patched_environ(overrides: Mapping[str, str]):
    previous = {name: os.environ.get(name) for name in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or "FAIL")
    if status == "SKIPPED":
        return "platform_release_candidate_protected_matrix=skip next=1400"
    summary = dict(result.get("summary") or {})
    return (
        "platform_release_candidate_protected_matrix="
        f"{status.lower()} gates={summary.get('passed_non_regression_gate_count', 0)}"
        "/8 protected="
        f"{summary.get('actual_protected_gate_count', 0)}/5 "
        f"pending_full={summary.get('pending_full_gate_count', 0)} "
        f"privacy={summary.get('privacy_violation_count', 0)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_release_candidate_protected_matrix()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
