#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from nex_runtime.release_candidate_providers import (  # noqa: E402
    RELEASE_CANDIDATE_PROVIDER_SCHEMA_VERSION,
    build_release_candidate_live_provider_evidence,
)
import run_platform_grounded_generation_artifact_live_postgres_smoke as grounded  # noqa: E402
import run_protected_remote_provider_live_smoke as provider  # noqa: E402
import run_s136_permission_hybrid_live_postgres_smoke as retrieval  # noqa: E402


ENABLE_ENV = "NEX_S140_RELEASE_CANDIDATE_LIVE_PROVIDERS"
SourceRunner = Callable[[Mapping[str, str]], Mapping[str, Any]]


def run_platform_release_candidate_live_providers(
    environ: Mapping[str, str] | None = None,
    *,
    provider_runner: SourceRunner = provider.run_protected_remote_provider_live_smoke,
    retrieval_runner: SourceRunner = retrieval.run_s136_permission_hybrid_live_postgres_smoke,
    grounded_runner: SourceRunner = grounded.run_platform_grounded_generation_artifact_live_postgres_smoke,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ENABLE_ENV) != "1":
        return {
            "schema_version": RELEASE_CANDIDATE_PROVIDER_SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{ENABLE_ENV} is not enabled.",
            "actual_live_provider_execution": False,
            "next_slice": "1397",
        }

    source_env = {
        **env,
        provider.LIVE_SMOKE_ENV: "1",
        retrieval.SMOKE_ENV: "1",
        grounded.SMOKE_ENV: "1",
        "NEX_MO_PROVIDER_MODE": "live",
    }
    try:
        provider_source = dict(provider_runner(source_env))
        retrieval_source = dict(retrieval_runner(source_env))
        grounded_source = dict(grounded_runner(source_env))
        evidence = build_release_candidate_live_provider_evidence(
            provider_source,
            retrieval_source,
            grounded_source,
        )
    except Exception:
        evidence = build_release_candidate_live_provider_evidence({}, {}, {})
        evidence["failure_code"] = "release_candidate_live_provider_execution_failed"

    evidence.update(
        actual_live_provider_execution=(
            evidence["gate_evidence"].get("actual_execution") is True
        ),
        source_projection={
            "provider_status": provider_source.get("status")
            if "provider_source" in locals()
            else "FAIL",
            "retrieval_status": retrieval_source.get("status")
            if "retrieval_source" in locals()
            else "NOT_RUN",
            "grounded_status": grounded_source.get("status")
            if "grounded_source" in locals()
            else "NOT_RUN",
        },
        next_slice="1398" if evidence["status"] == "PASS" else "blocked",
    )
    return evidence


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or "FAIL")
    if status == "SKIPPED":
        return "platform_release_candidate_live_providers=skip next=1397"
    gate = dict(result.get("gate_evidence") or {})
    metrics = dict(gate.get("metrics") or {})
    return (
        "platform_release_candidate_live_providers="
        f"{status.lower()} providers={metrics.get('provider_capability_count', 0)} "
        f"failed={metrics.get('failed_provider_count', 0)} "
        f"calibration={metrics.get('calibration_sample_count', 0)} "
        f"residue={metrics.get('residue_count', 0)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_release_candidate_live_providers()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
