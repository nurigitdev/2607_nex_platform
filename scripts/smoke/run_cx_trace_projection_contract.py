#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-cx"))

from nex_cx.authorization import CX_OPERATIONS_READ_SCOPE  # noqa: E402
from nex_cx.trace_projection import (  # noqa: E402
    CX_TRACE_OPERATIONS_PATH,
    build_cx_trace_projection,
)


SCHEMA_VERSION = "cx_trace_projection_contract_evidence.v1"
TRACE_ID = "13741374137413741374137413741374"


def run_cx_trace_projection_contract(root: Path = ROOT) -> dict[str, Any]:
    projection = build_cx_trace_projection(
        TRACE_ID,
        _records(),
        checked_at=datetime(2026, 10, 6, 10, 0, tzinfo=UTC),
    )
    schema = _load_json(
        root
        / "contracts/schemas/common/service_cross_service_trace_projection.v1.schema.json"
    )
    negative = _load_json(
        root
        / "contracts/tests/negative/operations/cx_cross_service_trace_projection.owner_leak.json"
    )
    migration = _read_text(
        root / "database/nex-cx/migrations/1374_cx_trace_projection_indexes.sql"
    )
    serialized = json.dumps(projection, sort_keys=True)
    checks = {
        "projection_contract_valid": _validates(schema, projection),
        "owner_leak_contract_rejected": _rejects(schema, negative),
        "three_durable_stage_families": [
            stage["stage_family"] for stage in projection["stages"]
        ]
        == ["INGESTION", "RETRIEVAL", "GENERATION"],
        "owner_ids_redacted": all(
            token not in serialized for token in ("tenant-private", "owner-private")
        ),
        "private_payload_excluded": (
            projection["summary"]["private_payload_included"] is False
            and all(
                stage["private_payload_included"] is False
                for stage in projection["stages"]
            )
        ),
        "ag_operations_scope_required": CX_OPERATIONS_READ_SCOPE
        == "operations:read",
        "service_only_internal_path": CX_TRACE_OPERATIONS_PATH.startswith(
            "/internal/v1/operations/"
        ),
        "ingestion_trace_index_present": "ix_cx_ingest_runs_trace" in migration,
        "generation_trace_index_present": "ix_cx_gen_exec_trace" in migration,
        "no_new_trace_table": "CREATE TABLE" not in migration.upper(),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1374",
        "requirement": "S138",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "failed_checks": [name for name, value in checks.items() if not value],
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "stage_count": len(projection["stages"]),
            "owner_digest_count": sum(
                "owner_digest" in stage for stage in projection["stages"]
            ),
        },
        "decision": {
            "new_table_required": False,
            "database_required": False,
            "remote_provider_required": False,
            "next_slice": "1375" if passed else "blocked",
        },
    }


def _records() -> list[dict[str, object]]:
    common = {
        "trace_id": TRACE_ID,
        "request_id": "request-1374",
        "tenant_ref_id": "tenant-private",
        "owner_subject_ref_id": "owner-private",
        "created_at": "2026-10-06T09:00:00Z",
    }
    return [
        {
            **common,
            "record_kind": "ingestion",
            "run_id": "ingestion-1374",
            "status": "SUCCEEDED",
            "current_step": "PUBLISHING",
            "attempt_count": 1,
            "updated_at": "2026-10-06T09:05:00Z",
        },
        {
            **common,
            "record_kind": "retrieval",
            "retrieval_package_id": "retrieval-1374",
            "status": "READY",
            "rerank_state": "APPLIED",
            "updated_at": "2026-10-06T09:06:00Z",
        },
        {
            **common,
            "record_kind": "generation",
            "cx_generation_id": "generation-1374",
            "retrieval_package_id": "retrieval-1374",
            "status": "COMPLETED",
            "alias": "general-llm-default",
            "provider_capability": "generation",
            "updated_at": "2026-10-06T09:07:00Z",
        },
    ]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


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


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "cx_trace_projection_contract="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"stages={summary.get('stage_count', 0)} "
        f"digests={summary.get('owner_digest_count', 0)} "
        f"next={decision.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_trace_projection_contract()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
