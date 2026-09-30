#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_registry import ProviderRouteError  # noqa: E402
from nex_mo.provider_retry import (  # noqa: E402
    build_provider_retry_policy,
    execute_with_provider_retry,
)


def run_mo_provider_retry_executor() -> dict[str, Any]:
    attempts = 0
    delays: list[float] = []
    events: list[dict[str, object]] = []

    def operation() -> dict[str, str]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ProviderRouteError(
                503,
                "mo.remote_embedding_unavailable",
                "Remote provider unavailable.",
                retryable=True,
                degraded=True,
                failure_kind="connection_error",
            )
        return {"status": "ok"}

    result = execute_with_provider_retry(
        operation,
        policy=build_provider_retry_policy("embedding"),
        sleeper=delays.append,
        jitter=lambda: 0.5,
        on_retry=lambda event: events.append(event.to_safe_summary()),
    )
    checks = {
        "third_attempt_succeeds": result.value == {"status": "ok"},
        "attempt_budget_observed": result.attempt_count == 3,
        "retry_count_observed": result.retry_count == 2,
        "bounded_delays_observed": delays == [0.125, 0.25],
        "safe_retry_events_observed": len(events) == 2
        and all("url" not in str(item).lower() for item in events),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_provider_retry_executor.v1",
        "slice": "1144",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_retry_executor_failed",
        "checks": checks,
        "events": events,
        "summary": {
            "attempt_count": result.attempt_count,
            "retry_count": result.retry_count,
            "delay_count": len(delays),
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
        },
        "next_slice": "1145",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_retry_executor="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"attempts={summary.get('attempt_count', 0)} "
        f"retries={summary.get('retry_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_retry_executor()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
