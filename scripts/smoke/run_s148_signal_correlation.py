#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime import ObservabilitySignal, correlate_observability_signals


def run_signal_correlation() -> dict[str, Any]:
    trace_id = "1474" * 8
    signals = [
        ObservabilitySignal(
            signal_id=f"signal:{service_id}:{kind.lower()}",
            service_id=service_id,
            signal_kind=kind,
            signal_name=f"{service_id}.s148.{kind.lower()}",
            observed_at=f"2026-10-08T01:00:0{index}Z",
            severity="INFO" if index < 3 else "WARNING",
            status="HEALTHY" if index < 3 else "DEGRADED",
            correlation_key="s148:journey:1474",
            trace_id=trace_id,
            measurements={"latency_ms": 10 + index},
            reason_codes=("SIGNAL_ADMITTED",),
            safe_attributes={"environment_class": "test", "state": "OBSERVED"},
        )
        for index, (service_id, kind) in enumerate(
            (
                ("nex-oa", "TRACE"),
                ("nex-ae-api", "LOG"),
                ("nex-cx", "METRIC"),
                ("nex-mo", "READINESS"),
                ("nex-ag", "METRIC"),
            )
        )
    ]
    projection = correlate_observability_signals(
        signals,
        checked_at="2026-10-08T01:00:10Z",
        maximum_age_seconds=60,
    )
    checks = {
        "five_service_signals": projection["summary"]["signal_count"] == 5,
        "four_signal_kinds": set(projection["summary"]["by_kind"])
        == {"METRIC", "LOG", "TRACE", "READINESS"},
        "single_trace_group": projection["summary"]["group_count"] == 1,
        "all_trace_linked": projection["summary"]["trace_linked_count"] == 5,
        "fresh_projection": projection["correlation_status"] == "READY",
        "degraded_signal_visible": projection["groups"][0]["degraded"] is True,
        "private_payload_absent": projection["summary"]["private_payload_included"] is False,
        "digests_are_unique": len({signal.signal_digest for signal in signals}) == 5,
    }
    passed = all(checks.values())
    return {
        "schema_version": "s148_signal_correlation.v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": projection["summary"],
        "signal_digests": [signal.signal_digest for signal in signals],
        "next_slice": "1475" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    return (
        "s148_signal_correlation="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"signals={summary.get('signal_count', 0)} "
        f"groups={summary.get('group_count', 0)} "
        f"kinds={len(summary.get('by_kind') or {})} "
        f"checks={sum(bool(value) for value in dict(result.get('checks') or {}).values())}/8 "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_signal_correlation()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
