#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_telemetry_persistence import (  # noqa: E402
    DurableProviderTelemetryRecord,
    ProviderTelemetryIdentity,
    ProviderTelemetryMutation,
)


def run_mo_provider_telemetry_persistence_contract() -> dict[str, Any]:
    identity = ProviderTelemetryIdentity(
        capability="generation",
        request_shape="openai_chat_completions",
        deployment_id="smoke-deployment",
        model_revision="smoke-revision",
    )
    retry = ProviderTelemetryMutation(
        identity=identity,
        mutation_kind="retry",
        observed_at="2026-09-30T01:00:00Z",
        attempt_increment=1,
        retry_increment=1,
        last_retry_delay_ms=250,
        last_retry_failure_kind="upstream_5xx",
    )
    success = ProviderTelemetryMutation(
        identity=identity,
        mutation_kind="success",
        observed_at="2026-09-30T01:00:01Z",
        request_increment=1,
        success_increment=1,
        attempt_increment=1,
        last_outcome="success",
        last_latency_ms=23,
        last_status_code=200,
    )
    record = DurableProviderTelemetryRecord(
        identity=identity,
        request_count=1,
        success_count=1,
        failure_count=0,
        retryable_failure_count=0,
        degraded_count=0,
        attempt_count=2,
        retry_count=1,
        last_outcome="success",
        last_observed_at=success.observed_at,
        last_latency_ms=23,
        last_status_code=200,
        last_retry_at=retry.observed_at,
        last_retry_delay_ms=250,
        last_retry_failure_kind="upstream_5xx",
    )
    checks = {
        "identity_has_four_fields": len(identity.to_params()) == 4,
        "retry_is_attempt_only": retry.request_increment == 0
        and retry.attempt_increment == 1,
        "success_closes_logical_request": success.request_increment == 1
        and success.success_increment == 1,
        "aggregate_invariants_hold": record.attempt_count
        == record.request_count + record.retry_count,
        "projection_excludes_private_runtime_values": all(
            field not in record.to_mapping()
            for field in ("provider_endpoint", "provider_api_key", "request_payload")
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_provider_telemetry_persistence_contract.v1",
        "slice": "1153",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "identity_field_count": len(identity.to_params()),
            "mutation_count": 2,
            "request_count": record.request_count,
            "attempt_count": record.attempt_count,
            "retry_count": record.retry_count,
        },
        "record": record.to_mapping(),
        "next_slice": "1154" if passed else None,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_telemetry_persistence_contract="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"identity_fields={summary.get('identity_field_count', 0)} "
        f"mutations={summary.get('mutation_count', 0)} "
        f"requests={summary.get('request_count', 0)} "
        f"attempts={summary.get('attempt_count', 0)} "
        f"retries={summary.get('retry_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_telemetry_persistence_contract()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
