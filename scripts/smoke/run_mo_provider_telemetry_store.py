#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_telemetry_persistence import (  # noqa: E402
    DurableProviderTelemetryRecord,
    ProviderTelemetryIdentity,
)
from nex_mo.provider_telemetry_store import DurableProviderTelemetryStore  # noqa: E402


class _Repository:
    def __init__(self, record: DurableProviderTelemetryRecord) -> None:
        self.record = record

    def list_records(self, *, capability: str | None = None):
        if capability is None or capability == self.record.identity.capability:
            return [self.record]
        return []

    def apply(self, mutation):  # pragma: no cover - read smoke only
        raise AssertionError("read smoke does not mutate")

    def clear(self):  # pragma: no cover - read smoke only
        return 0


def run_mo_provider_telemetry_store() -> dict[str, Any]:
    config = SimpleNamespace(
        capability="generation",
        endpoint_env="NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
        configured=True,
        request_shape="openai_chat_completions",
        model_name="runtime-model",
        model_revision="runtime-revision",
        deployment_id="runtime-deployment",
        api_key_env="NEX_MO_VLLM_API_KEY",
        api_key="private-smoke-key",
    )
    record = DurableProviderTelemetryRecord(
        identity=ProviderTelemetryIdentity.from_config(config),
        request_count=1,
        success_count=1,
        failure_count=0,
        retryable_failure_count=0,
        degraded_count=0,
        attempt_count=2,
        retry_count=1,
        last_outcome="success",
        last_observed_at="2026-09-30T01:00:01Z",
        last_latency_ms=12,
        last_status_code=200,
        last_retry_at="2026-09-30T01:00:00Z",
        last_retry_delay_ms=100,
        last_retry_failure_kind="upstream_5xx",
    )
    item = DurableProviderTelemetryStore(_Repository(record)).snapshot([config])[0]
    serialized = json.dumps(item, sort_keys=True)
    checks = {
        "durable_counters_merged": item["request_count"] == 1
        and item["attempt_count"] == 2
        and item["retry_count"] == 1,
        "runtime_config_merged": item["model_name"] == "runtime-model"
        and item["authorization_configured"] is True,
        "wire_field_count_preserved": len(item) == 26,
        "credentials_not_projected": "private-smoke-key" not in serialized,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_provider_telemetry_store_smoke.v1",
        "slice": "1155",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "wire_field_count": len(item),
            "request_count": item["request_count"],
            "attempt_count": item["attempt_count"],
            "retry_count": item["retry_count"],
        },
        "next_slice": "1156" if passed else None,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_telemetry_store="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"fields={summary.get('wire_field_count', 0)} "
        f"requests={summary.get('request_count', 0)} "
        f"attempts={summary.get('attempt_count', 0)} "
        f"retries={summary.get('retry_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_telemetry_store()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
