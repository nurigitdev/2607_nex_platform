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

from nex_mo.provider_retry import build_provider_retry_policy  # noqa: E402
from nex_mo.provider_retry_transport import (  # noqa: E402
    execute_remote_json_request_with_retry,
)
from nex_mo.remote_provider import build_remote_embedding_execution_config  # noqa: E402


def run_mo_provider_retry_transport() -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    delays: list[float] = []
    events = []
    config = build_remote_embedding_execution_config(
        {
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://provider.invalid/v1/embeddings",
            "NEX_MO_REMOTE_EMBEDDING_API_KEY": "private-test-key",
        }
    )

    def requester(method, url, **kwargs):
        calls.append({"method": method, "timeout": kwargs.get("timeout")})
        if len(calls) == 1:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})

    payload = execute_remote_json_request_with_retry(
        config,
        json_payload={"model": config.model_name, "input": ["hello"]},
        requester=requester,
        error_code_prefix="mo.remote_embedding",
        retry_policy=build_provider_retry_policy("embedding"),
        sleeper=delays.append,
        jitter=lambda: 1.0,
        on_retry=events.append,
    )
    serialized = json.dumps(
        {
            "calls": calls,
            "delays": delays,
            "events": [event.to_safe_summary() for event in events],
        }
    )
    checks = {
        "retry_then_success": len(calls) == 2 and "data" in payload,
        "retry_after_honored": delays == [0.0],
        "one_retry_event": len(events) == 1,
        "safe_evidence": "private-test-key" not in serialized
        and "provider.invalid" not in serialized,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_provider_retry_transport.v1",
        "slice": "1145",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_retry_transport_failed",
        "checks": checks,
        "summary": {
            "request_count": len(calls),
            "retry_count": len(events),
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
        },
        "next_slice": "1146",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_retry_transport="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"requests={summary.get('request_count', 0)} "
        f"retries={summary.get('retry_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_retry_transport()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
