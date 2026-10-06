#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED_PATH))

from nex_runtime import (  # noqa: E402
    TRACE_FORBIDDEN_KEY_FRAGMENTS,
    build_cross_service_trace_stage,
    build_cross_service_trace_timeline,
)


SCHEMA_VERSION = "platform_trace_envelope_contract_evidence.v1"
TRACE_ID = "13731373137313731373137313731373"
CONTRACT_PATHS = {
    "stage_schema": "contracts/schemas/common/cross_service_trace_stage.v1.schema.json",
    "timeline_schema": "contracts/schemas/service/nex_ag/cross_service_trace_e2e.v1.schema.json",
    "stage_example": "contracts/examples/common/cross_service_trace_stage.generation.json",
    "timeline_example": "contracts/examples/operations/ag_cross_service_trace_e2e.ready.json",
    "stage_negative": "contracts/tests/negative/common/cross_service_trace_stage.prompt_leak.json",
    "timeline_negative": "contracts/tests/negative/operations/ag_cross_service_trace_e2e.private_stage.json",
}


def run_platform_trace_envelope_contract(root: Path = ROOT) -> dict[str, Any]:
    payloads = {
        name: _load_json(root / path) for name, path in CONTRACT_PATHS.items()
    }
    stage = build_cross_service_trace_stage(
        stage_id="stage-generation-1373",
        trace_id=TRACE_ID,
        request_id="request-1373",
        service_id="nex-cx",
        stage_family="GENERATION",
        stage_status="SUCCEEDED",
        operation_timestamp="2026-10-06T09:13:00Z",
        owner_digest="a" * 64,
        correlation_refs={
            "retrieval_package_id": "retrieval-1373",
            "cx_generation_id": "generation-1373",
        },
        safe_attributes={
            "event_type": "generation.completed",
            "citation_status": "VALIDATED",
            "attempt": 1,
        },
    )
    timeline = build_cross_service_trace_timeline(
        trace_id=TRACE_ID,
        stages=[stage],
        source_statuses={"nex-cx": "READY"},
        checked_at="2026-10-06T09:14:00Z",
    )
    example_index = _load_json(root / "contracts/examples/index.json")
    negative_index = _load_json(root / "contracts/tests/negative/index.json")
    checks = {
        "contract_paths_present": all(
            (root / path).is_file() for path in CONTRACT_PATHS.values()
        ),
        "stage_schema_valid": _schema_is_valid(payloads["stage_schema"]),
        "timeline_schema_valid": _schema_is_valid(payloads["timeline_schema"]),
        "stage_example_valid": _validates(
            payloads["stage_schema"], payloads["stage_example"]
        ),
        "timeline_example_valid": _validates(
            payloads["timeline_schema"], payloads["timeline_example"]
        ),
        "stage_private_field_rejected": _rejects(
            payloads["stage_schema"], payloads["stage_negative"]
        ),
        "timeline_private_field_rejected": _rejects(
            payloads["timeline_schema"], payloads["timeline_negative"]
        ),
        "runtime_stage_matches_contract_example": stage
        == payloads["stage_example"],
        "runtime_timeline_matches_contract_example": timeline
        == payloads["timeline_example"],
        "positive_payloads_are_metadata_only": not _contains_forbidden_key(stage)
        and not _contains_forbidden_key(timeline),
        "examples_registered": _paths_registered(
            example_index,
            "examples",
            {
                CONTRACT_PATHS["stage_example"].removeprefix("contracts/"),
                CONTRACT_PATHS["timeline_example"].removeprefix("contracts/"),
            },
        ),
        "negative_examples_registered": _paths_registered(
            negative_index,
            "negative_examples",
            {
                CONTRACT_PATHS["stage_negative"].removeprefix("contracts/"),
                CONTRACT_PATHS["timeline_negative"].removeprefix("contracts/"),
            },
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1373",
        "requirement": "S138",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "failed_checks": [name for name, value in checks.items() if not value],
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "stage_count": len(timeline["timeline"]),
            "contract_count": 2,
        },
        "decision": {
            "private_payload_allowed": False,
            "database_required": False,
            "remote_provider_required": False,
            "next_slice": "1374" if passed else "blocked",
        },
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _schema_is_valid(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    try:
        Draft202012Validator.check_schema(schema)
    except Exception:
        return False
    return True


def _validates(schema: Any, payload: Any) -> bool:
    if not isinstance(schema, dict) or payload is None:
        return False
    try:
        Draft202012Validator(schema).validate(payload)
    except Exception:
        return False
    return True


def _rejects(schema: Any, payload: Any) -> bool:
    if not isinstance(schema, dict) or payload is None:
        return False
    try:
        Draft202012Validator(schema).validate(payload)
    except ValidationError:
        return True
    except Exception:
        return False
    return False


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str) and any(
                fragment in key.lower()
                for fragment in TRACE_FORBIDDEN_KEY_FRAGMENTS
            ):
                return True
            if _contains_forbidden_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _paths_registered(index: Any, key: str, expected: set[str]) -> bool:
    if not isinstance(index, dict) or not isinstance(index.get(key), list):
        return False
    registered = {
        entry.get("path") for entry in index[key] if isinstance(entry, dict)
    }
    return expected <= registered


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_trace_envelope_contract="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"stages={summary.get('stage_count', 0)} "
        f"contracts={summary.get('contract_count', 0)} "
        f"next={decision.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_trace_envelope_contract()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
