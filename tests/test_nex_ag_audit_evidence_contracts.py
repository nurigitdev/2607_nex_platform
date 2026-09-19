from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
import yaml

from nex_ag.audit_evidence_api import AuditEvidencePackageService
from nex_ag.audit_evidence_operations import (
    AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
    build_audit_evidence_operations_projection,
)
from nex_ag.audit_evidence_package import verify_audit_evidence_package
from nex_ag.operator_reviews import OperatorEvidenceExportStore
from nex_runtime import InMemoryOperationalEventStore, build_operational_event


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = ROOT / "contracts"
SCHEMA_PATH = (
    CONTRACTS_ROOT
    / "schemas"
    / "service"
    / "nex_ag"
    / "audit_evidence.v1.schema.json"
)
OPERATIONS_SCHEMA_PATH = (
    CONTRACTS_ROOT
    / "schemas"
    / "service"
    / "nex_ag"
    / "operations_projection.v1.schema.json"
)
OPENAPI_PATH = CONTRACTS_ROOT / "openapi" / "nex-ag.openapi.yaml"
EXAMPLES = CONTRACTS_ROOT / "examples" / "operations"
NEGATIVE_EXAMPLES = CONTRACTS_ROOT / "tests" / "negative" / "operations"
PACKAGE_RESPONSE_PATH = (
    EXAMPLES / "ag_audit_evidence_package_response.mock_success.json"
)
VERIFY_RESPONSE_PATH = (
    EXAMPLES / "ag_audit_evidence_verify_response.mock_success.json"
)
OPERATIONS_RESPONSE_PATH = (
    EXAMPLES / "ag_audit_evidence_operations_projection.mock_success.json"
)
TRACE_ID = "a" * 32
REQUEST_TRACE_ID = "c" * 32


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _stores() -> tuple[InMemoryOperationalEventStore, OperatorEvidenceExportStore]:
    events = InMemoryOperationalEventStore()
    events.append(
        build_operational_event(
            service_id="nex-ag",
            event_type="ag.audit.selected",
            severity="INFO",
            message="Contract source message must remain private.",
            trace_id=TRACE_ID,
            request_id="request-source-0867",
            subject_ref={"type": "audit_contract", "id": "source-0867"},
            details={"credential": "must-not-cross-contract"},
            created_at="2026-09-20T08:00:00Z",
            event_id="event-0867",
        )
    )
    exports = OperatorEvidenceExportStore()
    exports.save(
        {
            "export_id": "export-0867",
            "trace_id": TRACE_ID,
            "evidence_hash": "b" * 64,
            "evidence_item_count": 1,
            "export_status": "READY",
            "redaction_profile": "ag_redacted_manifest_v1",
            "evidence_manifest": {"raw_body": "must-not-cross-contract"},
            "updated_at": "2026-09-20T08:01:00Z",
        }
    )
    return events, exports


def test_schema_accepts_safe_examples_and_rejects_privacy_failures() -> None:
    schema = _load_json(SCHEMA_PATH)
    validator = Draft202012Validator(schema)

    Draft202012Validator.check_schema(schema)
    for path in (
        PACKAGE_RESPONSE_PATH,
        VERIFY_RESPONSE_PATH,
        OPERATIONS_RESPONSE_PATH,
    ):
        validator.validate(_load_json(path))
    for name in (
        "ag_audit_evidence_verify_response.raw_payload_leak.json",
        "ag_audit_evidence_verify_response.untrusted_package_id.json",
        "ag_audit_evidence_operations_projection.manifest_leak.json",
    ):
        assert list(validator.iter_errors(_load_json(NEGATIVE_EXAMPLES / name)))


def test_request_definitions_reject_client_selected_events_and_extra_envelopes() -> None:
    definitions = _load_json(SCHEMA_PATH)["$defs"]
    create_validator = Draft202012Validator(
        {"$ref": "#/$defs/create_request", "$defs": definitions}
    )
    verify_validator = Draft202012Validator(
        {"$ref": "#/$defs/verify_request", "$defs": definitions}
    )
    package = _load_json(PACKAGE_RESPONSE_PATH)["package"]

    create_validator.validate(
        {
            "trace_id": TRACE_ID,
            "expected_event_ids": ["event-0867"],
            "required_event_types": ["ag.audit.selected"],
        }
    )
    verify_validator.validate({"package": package})
    assert list(
        create_validator.iter_errors({"trace_id": TRACE_ID, "events": []})
    )
    assert list(
        verify_validator.iter_errors({"package": package, "raw_payload": {}})
    )


def test_package_fixture_is_cryptographically_self_consistent() -> None:
    fixture = _load_json(PACKAGE_RESPONSE_PATH)

    verification = verify_audit_evidence_package(fixture["package"])

    assert verification == fixture["verification"]
    assert verification["verification_status"] == "VERIFIED"


def test_runtime_package_and_operations_projection_match_contract() -> None:
    source_events, exports = _stores()
    package_response = AuditEvidencePackageService(
        event_store=source_events,
        export_store=exports,
    ).create_package(
        {
            "trace_id": TRACE_ID,
            "expected_event_ids": ["event-0867"],
            "required_event_types": ["ag.audit.selected"],
        },
        request_id="request-0867",
        request_trace_id=REQUEST_TRACE_ID,
    )
    operations_events = InMemoryOperationalEventStore()
    operations_events.append(
        build_operational_event(
            service_id="nex-ag",
            event_type=AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
            severity="INFO",
            message="Generated package details remain redacted.",
            trace_id=TRACE_ID,
            request_id="request-0867",
            subject_ref={
                "type": "audit_evidence_package",
                "id": package_response["package"]["package_id"],
            },
            details={
                "package_id": package_response["package"]["package_id"],
                "package_hash": package_response["package"]["package_hash"],
                "verification_status": "VERIFIED",
            },
            created_at="2026-09-20T08:02:00Z",
            event_id="event-generated-0867",
        )
    )
    operations = build_audit_evidence_operations_projection(
        event_store=operations_events,
        export_store=exports,
        request_trace_id=REQUEST_TRACE_ID,
    )
    validator = Draft202012Validator(_load_json(SCHEMA_PATH))

    validator.validate(package_response)
    validator.validate(operations)
    serialized = json.dumps((package_response, operations))
    assert "must-not-cross-contract" not in serialized
    assert "Contract source message" not in serialized


def test_dashboard_contract_is_strict_when_audit_integrity_is_present() -> None:
    schema = _load_json(OPERATIONS_SCHEMA_PATH)
    projection = _load_json(OPERATIONS_RESPONSE_PATH)
    section_schema = {
        "$ref": "#/$defs/dashboard_audit_integrity",
        "$defs": schema["$defs"],
    }

    Draft202012Validator(section_schema).validate(projection)
    leaked = deepcopy(projection)
    leaked["recent_exports"][0]["evidence_manifest"] = {"raw": "secret"}

    assert schema["properties"]["audit_integrity"] == {
        "$ref": "#/$defs/dashboard_audit_integrity"
    }
    assert list(Draft202012Validator(section_schema).iter_errors(leaked))


def test_openapi_freezes_protected_audit_evidence_surface() -> None:
    contract = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    validate(contract)
    paths = contract["paths"]
    schemas = contract["components"]["schemas"]

    operations = paths["/admin/v1/operations/audit-integrity"]["get"]
    create = paths["/admin/v1/audit-integrity/evidence-packages"]["post"]
    verify = paths[
        "/admin/v1/audit-integrity/evidence-packages/verify"
    ]["post"]

    assert operations["operationId"] == "getAgAuditEvidenceOperationsProjection"
    assert create["operationId"] == "createAgAuditEvidencePackage"
    assert verify["operationId"] == "verifyAgAuditEvidencePackage"
    assert create["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AgAuditEvidencePackageCreateRequest"
    }
    assert verify["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AgAuditEvidenceVerifyResponse"}
    assert schemas["AgAuditEvidencePackage"]["additionalProperties"] is False
    assert schemas["AgAuditEvidenceOperationsProjection"][
        "additionalProperties"
    ] is False
    assert schemas["AgAuditEvidenceOperationsProjection"]["properties"][
        "recent_exports"
    ]["items"]["additionalProperties"] is False


def test_contract_indexes_register_all_audit_evidence_fixtures() -> None:
    examples = {
        entry["path"] for entry in _load_json(CONTRACTS_ROOT / "examples/index.json")["examples"]
    }
    negatives = {
        entry["path"]
        for entry in _load_json(
            CONTRACTS_ROOT / "tests" / "negative" / "index.json"
        )["negative_examples"]
    }

    assert {
        "examples/operations/ag_audit_evidence_package_response.mock_success.json",
        "examples/operations/ag_audit_evidence_verify_response.mock_success.json",
        "examples/operations/ag_audit_evidence_operations_projection.mock_success.json",
    }.issubset(examples)
    assert {
        "tests/negative/operations/ag_audit_evidence_verify_response.raw_payload_leak.json",
        "tests/negative/operations/ag_audit_evidence_verify_response.untrusted_package_id.json",
        "tests/negative/operations/ag_audit_evidence_operations_projection.manifest_leak.json",
    }.issubset(negatives)
