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
sys.path.insert(0, str(ROOT / "services" / "nex-ae-api"))

from nex_ae_api.route_auth import AE_OPERATIONS_READ_SCOPE  # noqa: E402
from nex_ae_api.trace_projection import (  # noqa: E402
    AE_TRACE_OPERATIONS_PATH,
    build_ae_trace_projection,
)

SCHEMA_VERSION = "ae_trace_projection_contract_evidence.v1"
TRACE_ID = "13751375137513751375137513751375"


def run_ae_trace_projection_contract(root: Path = ROOT) -> dict[str, Any]:
    projection = build_ae_trace_projection(
        TRACE_ID,
        _records(),
        checked_at=datetime(2026, 10, 6, 11, 0, tzinfo=UTC),
    )
    schema = _load_json(
        root
        / "contracts/schemas/common/service_cross_service_trace_projection.v1.schema.json"
    )
    negative = _load_json(
        root
        / "contracts/tests/negative/operations/ae_cross_service_trace_projection.private_payload.json"
    )
    migration = _read_text(
        root / "database/nex-ae-api/migrations/1375_ae_trace_projection_indexes.sql"
    )
    serialized = json.dumps(projection, sort_keys=True)
    checks = {
        "projection_contract_valid": _validates(schema, projection),
        "private_payload_contract_rejected": _rejects(schema, negative),
        "four_durable_lifecycle_stages": [
            stage["stage_family"] for stage in projection["stages"]
        ]
        == ["UPLOAD", "GENERATION", "ARTIFACT", "ARTIFACT"],
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
        "ag_operations_scope_required": AE_OPERATIONS_READ_SCOPE == "operations:read",
        "service_only_internal_path": AE_TRACE_OPERATIONS_PATH.startswith(
            "/internal/v1/operations/"
        ),
        "upload_trace_index_present": "idx_ae_upload_trace" in migration,
        "response_trace_index_present": "idx_ae_chat_trace" in migration,
        "artifact_trace_index_present": "idx_ae_artifact_trace" in migration,
        "no_new_trace_table": migration.upper().count("CREATE TABLE") == 1
        and "schema_migrations" in migration,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1375",
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
            "new_domain_table_required": False,
            "database_required": False,
            "remote_provider_required": False,
            "next_slice": "1376" if passed else "blocked",
        },
    }


def _records() -> list[dict[str, object]]:
    common = {
        "trace_id": TRACE_ID,
        "request_id": "request-1375",
        "tenant_id": "tenant-private",
        "owner_user_id": "owner-private",
        "created_at": "2026-10-06T10:00:00Z",
    }
    return [
        {
            **common,
            "record_kind": "upload",
            "upload_handoff_id": "upload-1375",
            "cx_upload_id": "cx-upload-1375",
            "ingestion_job_id": "ingestion-1375",
            "status": "READY",
            "updated_at": "2026-10-06T10:01:00Z",
        },
        {
            **common,
            "record_kind": "response",
            "chat_interaction_id": "response-1375",
            "cx_retrieval_package_id": "retrieval-1375",
            "cx_generation_id": "generation-1375",
            "cx_generation_status": "CITATIONS_VALID",
            "status": "COMPLETED",
            "updated_at": "2026-10-06T10:02:00Z",
        },
        {
            **common,
            "record_kind": "artifact",
            "artifact_id": "artifact-1375",
            "status": "READY",
            "updated_at": "2026-10-06T10:03:00Z",
        },
        {
            **common,
            "record_kind": "render",
            "artifact_id": "artifact-1375",
            "render_job_id": "render-1375",
            "status": "COMPLETED",
            "progress_percent": 100,
            "retryable": False,
            "failure_code": None,
            "updated_at": "2026-10-06T10:04:00Z",
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
        "ae_trace_projection_contract="
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
    result = run_ae_trace_projection_contract()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
