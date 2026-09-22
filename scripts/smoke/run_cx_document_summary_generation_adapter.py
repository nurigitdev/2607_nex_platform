#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
CX_PATH = ROOT / "services" / "nex-cx"
SHARED_PATH = ROOT / "services" / "_shared"
for path in (CX_PATH, SHARED_PATH):
    sys.path.insert(0, str(path))

from nex_cx.document_summary_generation import (  # noqa: E402
    DEFAULT_SUMMARY_MODEL_PROFILE,
    generate_document_summary,
)
from nex_cx.ingestion import sha256_text  # noqa: E402


SCHEMA_VERSION = "cx_document_summary_generation_adapter_evidence.v1"


class _DeterministicMoClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {"payload": payload, "request_id": request_id, "trace_id": trace_id}
        )
        return {
            "mo_generation_id": "mo-summary-0954",
            "alias": payload["alias"],
            "model_revision": DEFAULT_SUMMARY_MODEL_PROFILE,
            "deployment_id": "mock-generation-local",
            "provider_type": "mock-generation",
            "output": {
                "type": "text",
                "text": "Deployment approval is effective on 2026-10-01.",
            },
            "finish_reason": "STOP",
            "usage": {
                "input_tokens": 24,
                "output_tokens": 9,
                "total_tokens": 33,
            },
        }


def run_cx_document_summary_generation_adapter() -> dict[str, Any]:
    markdown = "# Decision\n\nDeployment approval is effective on 2026-10-01."
    client = _DeterministicMoClient()
    result = generate_document_summary(
        client=client,
        markdown_text=markdown,
        source_markdown_sha256=sha256_text(markdown),
        system_prompt="Summarize under 900 characters and preserve dates.",
        request_id="request-0954",
        trace_id="95400000000000000000000000000001",
        summary_max_chars=900,
        summary_hard_limit_chars=1000,
    )
    call = client.calls[0]
    payload = call["payload"]
    serialized_metadata = json.dumps(payload["metadata"], sort_keys=True)
    serialized_result = json.dumps(result, sort_keys=True)
    checks = {
        "single_provider_call": len(client.calls) == 1,
        "generation_alias": payload["alias"] == "general-llm-default",
        "batch_workload": payload["workload_class"] == "LLM_BATCH",
        "non_streaming": payload["stream"] is False,
        "timeout_profile": payload["timeout_ms"] == 60_000,
        "hard_limit": len(result["summary_text"]) <= 1000,
        "model_profile": (
            result["provider"]["model_profile_id"] == DEFAULT_SUMMARY_MODEL_PROFILE
        ),
        "lineage_complete": all(
            result["provider"].get(field)
            for field in ("provider", "model_revision", "deployment_id")
        ),
        "raw_markdown_excluded_from_metadata": markdown not in serialized_metadata,
        "runtime_private_fields_excluded": "provider_url" not in serialized_result,
    }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "checks_total": len(checks),
        "model_profile_id": DEFAULT_SUMMARY_MODEL_PROFILE,
        "postgres_required": False,
        "live_provider_required": False,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    return (
        "cx_document_summary_generation_adapter="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={result.get('passed_checks', 0)}/{result.get('checks_total', 0)} "
        f"model={result.get('model_profile_id', 'unknown')} "
        f"postgres_required={result.get('postgres_required', True)} "
        f"live_required={result.get('live_provider_required', True)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_document_summary_generation_adapter()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
