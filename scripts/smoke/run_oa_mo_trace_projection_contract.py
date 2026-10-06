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
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-oa",
    ROOT / "services" / "nex-mo",
):
    sys.path.insert(0, str(path))

from nex_mo.provider_auth import MO_OPERATIONS_READ_SCOPE  # noqa: E402
from nex_mo.trace_projection import (  # noqa: E402
    MO_TRACE_OPERATIONS_PATH,
    build_mo_trace_projection,
)
from nex_oa.service_auth import OA_OPERATIONS_READ_SCOPE  # noqa: E402
from nex_oa.trace_projection import (  # noqa: E402
    OA_TRACE_OPERATIONS_PATH,
    build_oa_trace_projection,
)
from nex_runtime import build_operational_event  # noqa: E402

SCHEMA_VERSION = "oa_mo_trace_projection_contract_evidence.v1"
OA_TRACE_ID = "13761376137613761376137613761376"
MO_TRACE_ID = "76137613761376137613761376137613"


def run_oa_mo_trace_projection_contract(root: Path = ROOT) -> dict[str, Any]:
    oa_projection = build_oa_trace_projection(
        OA_TRACE_ID,
        _oa_records(),
        checked_at=datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
    )
    mo_projection = build_mo_trace_projection(
        MO_TRACE_ID,
        _mo_records(),
        checked_at=datetime(2026, 10, 6, 12, 30, tzinfo=UTC),
    )
    schema = _load_json(
        root
        / "contracts/schemas/common/service_cross_service_trace_projection.v1.schema.json"
    )
    oa_negative = _load_json(
        root
        / "contracts/tests/negative/operations/oa_cross_service_trace_projection.owner_leak.json"
    )
    mo_negative = _load_json(
        root
        / "contracts/tests/negative/operations/mo_cross_service_trace_projection.provider_url.json"
    )
    oa_migration = _read_text(
        root / "database/nex-oa/migrations/1376_oa_trace_projection_index.sql"
    )
    mo_foundation = _read_text(
        root
        / "database/nex-mo/migrations/0085_service_operational_events_foundation.sql"
    )
    provider_source = "\n".join(
        (
            _read_text(root / "services/nex-mo/nex_mo/providers.py"),
            _read_text(root / "services/nex-mo/nex_mo/provider_trace.py"),
        )
    )
    serialized_oa = json.dumps(oa_projection, sort_keys=True)
    mo_stage = mo_projection["stages"][0]
    checks = {
        "oa_projection_contract_valid": _validates(schema, oa_projection),
        "mo_projection_contract_valid": _validates(schema, mo_projection),
        "oa_owner_leak_rejected": _rejects(schema, oa_negative),
        "mo_provider_url_rejected": _rejects(schema, mo_negative),
        "oa_auth_and_trust_stages_present": (
            len(oa_projection["stages"]) == 2
            and all(
                stage["stage_family"] == "AUTH" for stage in oa_projection["stages"]
            )
        ),
        "oa_owner_ids_redacted": all(
            value not in serialized_oa for value in ("tenant-private", "owner-private")
        ),
        "mo_provider_identity_metadata_present": all(
            field in mo_stage["safe_attributes"]
            for field in (
                "model_alias",
                "model_revision",
                "deployment_id",
                "provider_route_id",
                "provider_mode",
            )
        ),
        "mo_private_provider_location_absent": (
            "provider_url" not in json.dumps(mo_projection, sort_keys=True)
            and "192.168." not in json.dumps(mo_projection, sort_keys=True)
        ),
        "ag_operations_scope_required": (
            OA_OPERATIONS_READ_SCOPE == MO_OPERATIONS_READ_SCOPE == "operations:read"
        ),
        "service_only_internal_paths": all(
            path.startswith("/internal/v1/operations/")
            for path in (OA_TRACE_OPERATIONS_PATH, MO_TRACE_OPERATIONS_PATH)
        ),
        "oa_trace_index_present": "ix_oa_auth_events_trace" in oa_migration,
        "mo_operational_trace_index_reused": (
            "ix_service_operational_events_trace" in mo_foundation
        ),
        "provider_route_emits_trace_events": all(
            token in provider_source
            for token in (
                "mo.provider.request.succeeded",
                "mo.provider.request.failed",
                "trace_emitter",
            )
        ),
        "no_new_domain_table": (
            oa_migration.upper().count("CREATE TABLE") == 1
            and "schema_migrations" in oa_migration
            and not (
                root / "database/nex-mo/migrations/1376_mo_trace_projection.sql"
            ).exists()
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1376",
        "requirement": "S138",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "failed_checks": [name for name, value in checks.items() if not value],
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "oa_stage_count": len(oa_projection["stages"]),
            "mo_stage_count": len(mo_projection["stages"]),
            "owner_digest_count": sum(
                "owner_digest" in stage for stage in oa_projection["stages"]
            ),
        },
        "decision": {
            "new_domain_table_required": False,
            "database_required": False,
            "remote_provider_required": False,
            "next_slice": "1377" if passed else "blocked",
        },
    }


def _oa_records() -> list[dict[str, object]]:
    return [
        {
            "record_kind": "auth",
            "event_id": "oa-auth-1376",
            "event_type": "LOGIN_SUCCEEDED",
            "outcome": "SUCCEEDED",
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-private"},
            "subject_ref": {"type": "oa.user", "id": "owner-private"},
            "request_id": "request-1376",
            "trace_id": OA_TRACE_ID,
            "details": {},
            "occurred_at": "2026-10-06T11:00:00Z",
        },
        {
            "record_kind": "trust",
            "event_id": "oa-trust-1376",
            "event_type": "oa.service_token.issued",
            "severity": "INFO",
            "request_id": "request-1376",
            "trace_id": OA_TRACE_ID,
            "details": {},
            "created_at": "2026-10-06T11:01:00Z",
        },
    ]


def _mo_records() -> list[dict[str, object]]:
    return [
        build_operational_event(
            service_id="nex-mo",
            event_type="mo.provider.request.succeeded",
            severity="INFO",
            message="MO provider request completed.",
            trace_id=MO_TRACE_ID,
            request_id="request-1376",
            details={
                "provider_capability": "generation",
                "model_alias": "general-llm-default",
                "model_revision": "Qwen-revision",
                "deployment_id": "dgx-generation-9111",
                "provider_route_id": "route-general-llm-default",
                "provider_mode": "live",
                "provider_request_id": "provider-request-1376",
                "result_code": "SUCCEEDED",
                "retryable": False,
            },
            created_at="2026-10-06T12:00:00Z",
        )
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
        "oa_mo_trace_projection_contract="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"stages={summary.get('oa_stage_count', 0)}+"
        f"{summary.get('mo_stage_count', 0)} "
        f"digests={summary.get('owner_digest_count', 0)} "
        f"next={decision.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_oa_mo_trace_projection_contract()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
