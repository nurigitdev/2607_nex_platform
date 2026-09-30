#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import httpx


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.remote_provider import (  # noqa: E402
    execute_remote_embedding_request,
    list_remote_provider_telemetry,
    reset_remote_provider_telemetry,
)


def run_mo_provider_retry_telemetry() -> dict[str, Any]:
    reset_remote_provider_telemetry()
    environ = {
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://provider.invalid/embeddings",
        "NEX_MO_RETRY_BASE_DELAY_SECONDS": "0",
    }
    calls = 0

    def requester(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})

    execute_remote_embedding_request(
        {"inputs": ["hello"]},
        environ=environ,
        requester=requester,
    )
    snapshot = list_remote_provider_telemetry(
        capability="embedding",
        environ=environ,
    )[0]
    serialized = json.dumps(snapshot)
    checks = {
        "one_logical_request": snapshot["request_count"] == 1,
        "two_provider_attempts": snapshot["attempt_count"] == 2,
        "one_retry_recorded": snapshot["retry_count"] == 1,
        "successful_outcome_preserved": snapshot["success_count"] == 1
        and snapshot["failure_count"] == 0,
        "last_retry_safe": snapshot["last_retry_failure_kind"] == "upstream_5xx"
        and snapshot["last_retry_delay_ms"] == 0,
        "private_runtime_values_absent": "provider.invalid" not in serialized,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_provider_retry_telemetry.v1",
        "slice": "1147",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_retry_telemetry_failed",
        "checks": checks,
        "snapshot": snapshot,
        "summary": {
            "request_count": snapshot["request_count"],
            "attempt_count": snapshot["attempt_count"],
            "retry_count": snapshot["retry_count"],
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
        },
        "next_slice": "1148",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_retry_telemetry="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"requests={summary.get('request_count', 0)} "
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
    evidence = run_mo_provider_retry_telemetry()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
