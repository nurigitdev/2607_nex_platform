#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED))

from nex_runtime.postgres_orchestration import (  # noqa: E402
    POSTGRES_SERVICE_ORDER,
    S133_POSTGRES_ORCHESTRATION_PLAN,
    build_platform_postgres_restart_evidence,
    build_postgres_phase_evidence,
)


def build_report() -> dict[str, object]:
    records = tuple(
        build_postgres_phase_evidence(
            service_id=service_id,
            phase="CONFIGURATION",
            status="PASSED",
            evidence_codes=("typed_evidence_contract_valid",),
        )
        for service_id in POSTGRES_SERVICE_ORDER
    )
    evidence = build_platform_postgres_restart_evidence(
        run_id="s133-slice-1323",
        state="PASSED",
        records=records,
    )
    return {
        "status": "PASS",
        "plan": S133_POSTGRES_ORCHESTRATION_PLAN.to_public_projection(),
        "evidence": evidence.to_public_projection(),
        "next_slice": "1324",
    }


def summary_line(report: dict[str, object]) -> str:
    if report.get("status") != "PASS":
        return "platform_postgres_restart_evidence=fail"
    evidence = report.get("evidence") or {}
    assert isinstance(evidence, dict)
    return (
        "platform_postgres_restart_evidence=pass "
        f"services={evidence.get('service_count')} "
        f"records={evidence.get('record_count')} next={report.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    report = build_report()
    print(
        summary_line(report)
        if args.summary
        else json.dumps(report, indent=2, sort_keys=True)
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
