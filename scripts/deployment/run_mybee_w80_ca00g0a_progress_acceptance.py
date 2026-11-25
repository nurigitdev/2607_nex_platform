#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/deployment"))

import run_canonical_platform_installed_acceptance as installed
import run_mybee_w80_ca00f5_split_live_journeys as split

EXECUTION_ENV = "NEX_MYBEE_W80_CA00G0A_LIVE"
SCHEMA_VERSION = "mybee_w80_ca00g0a_progress_acceptance.v1"
DEFAULT_REPORT = (
    ROOT / "reports/deployment/mybee-w80-ca00g0a-progress-acceptance.json"
)
SCREENSHOT_DIR = (
    ROOT / "reports/deployment/mybee-w80-ca00g0a-progress-screens"
)


class ProgressAcceptanceError(RuntimeError):
    pass


def run_progress_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    source = _source_admission()
    if not execute or env.get(EXECUTION_ENV) != "1":
        return {**source, "status": "SOURCE_ADMITTED", "executed": False}
    runtime_env = {
        **env,
        split.EXECUTION_ENV: "1",
        split.PROGRESS_ACCEPTANCE_ENV: "1",
        "NEX_MYBEE_W80_SPLIT_SCREENSHOT_DIR": str(SCREENSHOT_DIR),
    }
    result = split.run_split_live_journeys(runtime_env, execute=True)
    try:
        checks = _protected_checks(result)
    except (KeyError, TypeError, ProgressAcceptanceError) as exc:
        return {
            **source,
            "status": "FAIL",
            "executed": True,
            "issues": [str(exc)],
            "protected_result_status": result.get("status"),
        }
    return {
        **source,
        **result,
        "schema_version": SCHEMA_VERSION,
        "slice": "W80-CA00G.0A",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "executed": True,
        "progress_checks": checks,
        "screen_evidence_root": SCREENSHOT_DIR.relative_to(ROOT).as_posix(),
    }


def _source_admission() -> dict[str, Any]:
    split_source = split.run_split_live_journeys({}, execute=False)
    runner_source = split.PLAYWRIGHT_RUNNER.read_text(encoding="utf-8")
    required_markers = (
        "observeExecutionProgress",
        "evaluateExecutionProgressAcceptance",
        split.PROGRESS_ACCEPTANCE_ENV,
        'aria-label="실행 진행 로그"',
    )
    missing = [marker for marker in required_markers if marker not in runner_source]
    if missing:
        raise ProgressAcceptanceError(
            "progress acceptance runner markers are missing"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "W80-CA00G.0A",
        "source_admitted": True,
        "split_journey_prerequisite": split_source["source_admitted"],
        "actual_postgres_required": True,
        "actual_remote_generation_required": True,
        "actual_playwright_required": True,
        "progress_runner_markers": list(required_markers),
        "secret_included": False,
        "raw_prompt_in_report": False,
    }


def _protected_checks(result: Mapping[str, Any]) -> dict[str, bool]:
    if result.get("status") != "PASS":
        raise ProgressAcceptanceError("protected split journey did not pass")
    browser = result["extended_acceptance"]["browser"]
    progress = [browser[mode]["progress_acceptance"] for mode in ("journal", "allocation")]
    checks = {
        "both_product_journeys_passed": all(
            browser[mode]["status"] == "PASS" for mode in ("journal", "allocation")
        ),
        "both_progress_acceptances_passed": all(
            item["status"] == "PASS" for item in progress
        ),
        "polling_overlapped_chat_post": all(
            item["checks"]["progress_poll_started_before_chat_response"]
            for item in progress
        ),
        "dom_append_only_with_debug_time": all(
            item["checks"]["progress_dom_is_append_only"]
            and item["checks"]["progress_debug_time_prefix_visible"]
            for item in progress
        ),
        "owner_projection_terminal_and_private": all(
            item["checks"]["progress_projection_owner_scoped"]
            and item["checks"]["progress_projection_terminal"]
            and item["checks"]["progress_projection_private_payload_absent"]
            for item in progress
        ),
        "polling_stopped_after_terminal": all(
            item["checks"]["progress_polling_stopped_after_terminal"]
            for item in progress
        ),
        "ordered_unique_projection": all(
            item["checks"]["progress_projection_ordered_and_unique"]
            for item in progress
        ),
        "screen_evidence_captured": all(
            item["checks"]["progress_screen_evidence_captured"]
            for item in progress
        ),
        "zero_residue": result.get("zero_residue") is True,
    }
    return checks


def summary_line(result: Mapping[str, Any]) -> str:
    return (
        "mybee_w80_ca00g0a_progress="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"executed={str(bool(result.get('executed'))).lower()} "
        f"screens={str(bool(result.get('progress_checks', {}).get('screen_evidence_captured'))).lower()}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run protected W80-CA00G.0A progress and Playwright acceptance"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    result = run_progress_acceptance(os.environ, execute=args.execute)
    installed._write_report(args.report, result)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SOURCE_ADMITTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
