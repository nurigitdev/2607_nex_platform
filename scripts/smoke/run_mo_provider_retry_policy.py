#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_retry import (  # noqa: E402
    build_provider_retry_policy,
    decide_provider_retry,
)
from nex_mo.provider_transport import (  # noqa: E402
    RemoteProviderFailureDecision,
)


def run_mo_provider_retry_policy() -> dict[str, Any]:
    policies = {
        capability: build_provider_retry_policy(capability)
        for capability in ("embedding", "reranking", "generation")
    }
    connect_failure = RemoteProviderFailureDecision(
        failure_kind="connection_error",
        error_code="mo.remote_provider_unavailable",
        status_code=503,
        detail="Remote provider unavailable.",
        retryable=True,
        degraded=True,
    )
    read_timeout = RemoteProviderFailureDecision(
        failure_kind="read_timeout",
        error_code="mo.remote_provider_timeout",
        status_code=504,
        detail="Remote provider response timed out.",
        retryable=True,
        degraded=True,
    )
    decisions = {
        "embedding_transient": decide_provider_retry(
            policies["embedding"], connect_failure, attempt_number=1
        ).to_safe_summary(),
        "generation_transient": decide_provider_retry(
            policies["generation"], connect_failure, attempt_number=1
        ).to_safe_summary(),
        "generation_ambiguous": decide_provider_retry(
            policies["generation"], read_timeout, attempt_number=1
        ).to_safe_summary(),
    }
    checks = {
        "attempt_limits_bounded": [
            policies[name].max_attempts
            for name in ("embedding", "reranking", "generation")
        ]
        == [3, 3, 2],
        "safe_transient_retries_allowed": (
            decisions["embedding_transient"]["retry"] is True
            and decisions["generation_transient"]["retry"] is True
        ),
        "ambiguous_generation_replay_blocked": (
            decisions["generation_ambiguous"]["retry"] is False
        ),
        "summaries_are_private": all(
            "url" not in str(policy.to_safe_summary()).lower()
            and "api_key" not in str(policy.to_safe_summary()).lower()
            for policy in policies.values()
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_provider_retry_policy.v1",
        "slice": "1143",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_retry_policy_failed",
        "checks": checks,
        "policies": {
            name: policy.to_safe_summary() for name, policy in policies.items()
        },
        "decisions": decisions,
        "summary": {
            "policy_count": len(policies),
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
        },
        "next_slice": "1144",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_retry_policy="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"policies={summary.get('policy_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_retry_policy()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
