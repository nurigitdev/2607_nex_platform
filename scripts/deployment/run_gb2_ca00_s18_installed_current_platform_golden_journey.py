#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "services/_shared"),
    str(ROOT / "scripts/deployment"),
]

import run_canonical_platform_golden_journey as canonical_journey
from nex_runtime.current_platform_installation import (
    CURRENT_JOURNEY_WORKERS,
    admit_current_platform_installation,
)

EXECUTION_ENV = "NEX_GB2_CA00_S18_LIVE"
SCHEMA_VERSION = "gb2_ca00_s18_installed_current_platform_continuity.v1"
DEFAULT_REPORT = (
    ROOT / "reports/deployment/gb2-ca00-s18-installed-current-platform.json"
)
GOLDEN_JOURNEY_EVIDENCE_CONTRACT = {
    "platform_integrated": True,
    "runtime_transition_fixture": False,
    "manual_domain_transition": False,
    "installed_process_continuity": True,
}


class InstalledCurrentPlatformContinuityError(RuntimeError):
    pass


def run_installed_current_platform_continuity(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    root: Path = ROOT,
    protected_runner: Callable[[Mapping[str, str]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    source = _source_admission(root)
    if not execute or env.get(EXECUTION_ENV) != "1":
        return {**source, "status": "SOURCE_ADMITTED", "executed": False}
    try:
        runner = protected_runner or (
            lambda values: canonical_journey.execute_canonical_platform_golden_journey(
                values,
                root=root,
                worker_inventory=CURRENT_JOURNEY_WORKERS,
            )
        )
        protected = dict(runner(env))
        checks = _continuity_checks(protected)
        if not all(checks.values()):
            raise InstalledCurrentPlatformContinuityError(
                "installed current Platform continuity invariant failed"
            )
        return {
            **source,
            **protected,
            "schema_version": SCHEMA_VERSION,
            "slice": "GB2-CA00-S18",
            **GOLDEN_JOURNEY_EVIDENCE_CONTRACT,
            "status": "PASS",
            "executed": True,
            "continuity_checks": checks,
            "current_topology_source": "nex_runtime.current_platform_installation",
            "secret_included": False,
            "token_value_included": False,
        }
    except (
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        return {
            **source,
            "status": "FAIL",
            "executed": True,
            "issues": [str(exc)],
            "secret_included": False,
            "token_value_included": False,
        }


def _source_admission(root: Path) -> dict[str, Any]:
    installation = admit_current_platform_installation(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "GB2-CA00-S18",
        **GOLDEN_JOURNEY_EVIDENCE_CONTRACT,
        "source_admitted": True,
        "current_installation": installation,
        "actual_postgres_required": True,
        "actual_openbao_required": True,
        "actual_rustfs_required": True,
        "actual_remote_generation_required": True,
        "actual_playwright_required": True,
        "current_artifact_count": installation["artifact_count"],
        "current_process_count": installation["process_count"],
        "secret_included": False,
        "token_value_included": False,
    }


def _continuity_checks(evidence: Mapping[str, Any]) -> dict[str, bool]:
    extended = evidence.get("extended_acceptance")
    restarted = evidence.get("post_restart_acceptance")
    extended_checks = extended.get("checks") if isinstance(extended, Mapping) else None
    restart_checks = restarted.get("checks") if isinstance(restarted, Mapping) else None
    return {
        "installed_acceptance_passed": evidence.get("status") == "PASS",
        "actual_postgres": evidence.get("actual_postgres") is True,
        "actual_compose": evidence.get("actual_compose") is True,
        "actual_openbao": evidence.get("actual_openbao") is True,
        "actual_rustfs": evidence.get("actual_rustfs") is True,
        "actual_remote_generation": evidence.get("actual_remote_generation") is True,
        "actual_playwright": evidence.get("actual_playwright") is True,
        "journey_invariants": isinstance(extended_checks, Mapping)
        and bool(extended_checks)
        and all(value is True for value in extended_checks.values()),
        "restart_invariants": isinstance(restart_checks, Mapping)
        and bool(restart_checks)
        and all(value is True for value in restart_checks.values()),
        "queue_state_stable": evidence.get("pre_activation_queue_counts")
        == evidence.get("post_restart_queue_counts"),
    }


def _write_report(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(dict(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    return (
        "gb2_ca00_s18_installed_current_platform="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"executed={str(bool(result.get('executed'))).lower()} "
        f"processes={result.get('current_process_count', 0)} "
        f"postgres={str(bool(result.get('actual_postgres'))).lower()} "
        f"provider={str(bool(result.get('actual_remote_generation'))).lower()} "
        f"playwright={str(bool(result.get('actual_playwright'))).lower()}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run GB2-CA00-S18 installed current Platform continuity"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    result = run_installed_current_platform_continuity(os.environ, execute=args.execute)
    _write_report(args.report, result)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SOURCE_ADMITTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
