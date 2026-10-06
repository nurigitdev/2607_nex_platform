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

from nex_runtime.release_candidate_operations import (  # noqa: E402
    RELEASE_CANDIDATE_OPERATIONS_SCHEMA_VERSION,
    build_release_candidate_browser_ag_evidence,
)
import run_platform_ag_trace_postgres_smoke as ag  # noqa: E402
import run_s139_ae_web_protected_acceptance as browser  # noqa: E402


ENABLE_ENV = "NEX_S140_RELEASE_CANDIDATE_BROWSER_AG_OPERATIONS"
SourceRunner = Callable[[Mapping[str, str]], Mapping[str, Any]]


def run_platform_release_candidate_browser_ag_operations(
    environ: Mapping[str, str] | None = None,
    *,
    browser_runner: SourceRunner = browser.run_s139_ae_web_protected_acceptance,
    ag_runner: SourceRunner = ag.run_platform_ag_trace_postgres_smoke,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ENABLE_ENV) != "1":
        return {
            "schema_version": RELEASE_CANDIDATE_OPERATIONS_SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{ENABLE_ENV} is not enabled.",
            "actual_browser_execution": False,
            "actual_ag_postgresql_execution": False,
            "next_slice": "1398",
        }

    source_env = {
        **env,
        browser.SMOKE_ENV: "1",
        ag.SMOKE_ENV: "1",
    }
    try:
        browser_source = dict(browser_runner(source_env))
        ag_source = dict(ag_runner(source_env))
        evidence = build_release_candidate_browser_ag_evidence(
            browser_source,
            ag_source,
        )
    except Exception:
        browser_source = locals().get("browser_source", {})
        ag_source = {}
        evidence = build_release_candidate_browser_ag_evidence(
            browser_source,
            ag_source,
        )
        evidence["failure_code"] = (
            "release_candidate_browser_ag_operations_execution_failed"
        )

    gates = {
        item.get("gate_id"): item for item in evidence.get("gate_evidence", [])
    }
    evidence.update(
        actual_browser_execution=(
            gates.get("korean_browser_journey", {}).get("actual_execution") is True
        ),
        actual_ag_postgresql_execution=(
            gates.get("ag_trace_operations", {}).get("actual_execution") is True
        ),
        source_projection={
            "browser_status": browser_source.get("status", "NOT_RUN"),
            "ag_status": ag_source.get("status", "NOT_RUN"),
        },
        next_slice="1399" if evidence["status"] == "PASS" else "blocked",
    )
    return evidence


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or "FAIL")
    if status == "SKIPPED":
        return "platform_release_candidate_browser_ag=skip next=1398"
    gates = {
        item.get("gate_id"): item
        for item in result.get("gate_evidence", [])
        if isinstance(item, Mapping)
    }
    browser_metrics = dict(
        gates.get("korean_browser_journey", {}).get("metrics") or {}
    )
    ag_metrics = dict(gates.get("ag_trace_operations", {}).get("metrics") or {})
    return (
        "platform_release_candidate_browser_ag="
        f"{status.lower()} viewports={browser_metrics.get('passed_viewport_count', 0)}"
        f"/{browser_metrics.get('viewport_count', 0)} "
        f"trace_families={ag_metrics.get('trace_stage_count', 0)} "
        f"audit={ag_metrics.get('audit_export_count', 0)} "
        f"residue={browser_metrics.get('residue_count', 0) + ag_metrics.get('residue_count', 0)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_release_candidate_browser_ag_operations()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
