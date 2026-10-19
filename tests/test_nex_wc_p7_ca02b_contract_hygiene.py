from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from nex_wc.work_results import WorkResultError, validate_work_result

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "contracts/openapi/nex-wc.openapi.yaml"
FROZEN_SCHEMA_PATH = (
    ROOT / "docs/transition/P7/contracts/p7-work-result-v2.1.schema.json"
)

WORK_ITEM_ID = "66666666-6666-4666-8666-666666666666"
CLAIM_ID = "77777777-7777-4777-8777-777777777776"
ASSIGNMENT_ID = "88888888-8888-4888-8888-888888888886"
AGENT_ID = "11111111-1111-4111-8111-111111111116"

EFFECTIVE_REQUIRED_FIELDS = {
    "schema_version",
    "tenant_id",
    "result_id",
    "work_item_id",
    "revision_no",
    "result_type",
    "schema_ref",
    "technical_outcome",
    "business_outcome",
    "source_execution_ref",
    "claim_ref",
    "claim_generation",
    "assignment_ref",
    "submitted_by",
    "trace",
    "submitted_at",
}


def _work_result(*, payload: object = None) -> dict[str, object]:
    return {
        "schema_version": "2.1",
        "tenant_id": "tenant-p7-ca02b",
        "result_id": "result-p7-ca02b",
        "work_item_id": WORK_ITEM_ID,
        "revision_no": 1,
        "result_type": "PROJECT_MARGIN_ANALYSIS",
        "summary": "Project margin evidence is ready.",
        "payload": payload,
        "schema_ref": "urn:nex:result:project-margin:1",
        "technical_outcome": "SUCCEEDED",
        "business_outcome": "VERIFIED",
        "artifact_refs": [],
        "evidence_refs": [],
        "business_object_refs": [],
        "source_execution_ref": "execution-p7-ca02b",
        "source_plan_ref": "plan-p7-ca02b",
        "claim_ref": CLAIM_ID,
        "claim_generation": 1,
        "assignment_ref": ASSIGNMENT_ID,
        "submitted_by": {"entity_type": "AGENT", "entity_id": AGENT_ID},
        "trace": {
            "correlation_id": "trace-p7-ca02b",
            "causation_id": "execution-p7-ca02b",
            "request_id": "request-p7-ca02b",
        },
        "submitted_at": "2026-10-19T08:00:00Z",
    }


def _openapi() -> dict[str, object]:
    return yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))


def _openapi_validator(component: str) -> Draft202012Validator:
    document = _openapi()
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": f"#/components/schemas/{component}",
        "components": document["components"],
    }
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _frozen_validator() -> Draft202012Validator:
    schema = json.loads(FROZEN_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _assert_runtime_and_openapi_reject(candidate: object) -> None:
    with pytest.raises(WorkResultError):
        validate_work_result(candidate)
    assert list(_openapi_validator("WorkResult").iter_errors(candidate))


def test_ca02b_valid_p7_profile_conforms_to_frozen_runtime_and_openapi() -> None:
    result = _work_result(payload={"margin": 12.5})

    _frozen_validator().validate(result)
    assert validate_work_result(result) == result
    _openapi_validator("WorkResult").validate(result)
    _openapi_validator("WorkResultSubmitRequest").validate(
        {"expected_version": 3, "work_result": result}
    )


def test_ca02b_openapi_freezes_effective_required_fields_and_agent_ref() -> None:
    schemas = _openapi()["components"]["schemas"]
    work_result = schemas["WorkResult"]
    submitted_by = schemas["SubmittedByAgentRef"]

    assert EFFECTIVE_REQUIRED_FIELDS <= set(work_result["required"])
    assert work_result["properties"]["submitted_by"] == {
        "$ref": "#/components/schemas/SubmittedByAgentRef"
    }
    assert submitted_by["properties"]["entity_type"] == {"const": "AGENT"}
    assert submitted_by["properties"]["entity_id"] == {
        "type": "string",
        "format": "uuid",
    }


@pytest.mark.parametrize("field", sorted(EFFECTIVE_REQUIRED_FIELDS))
def test_ca02b_runtime_and_openapi_reject_each_missing_effective_field(
    field: str,
) -> None:
    candidate = _work_result()
    candidate.pop(field)

    _assert_runtime_and_openapi_reject(candidate)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update(submitted_by="AGENT"),
        lambda value: value["submitted_by"].update(entity_type="USER"),
        lambda value: value["submitted_by"].update(entity_id="not-a-uuid"),
        lambda value: value.update(work_item_id="not-a-uuid"),
        lambda value: value.update(claim_ref="not-a-uuid"),
        lambda value: value.update(assignment_ref="not-a-uuid"),
        lambda value: value.update(claim_generation=0),
        lambda value: value.update(trace={}),
        lambda value: value.update(
            trace={"correlation_id": "trace", "unsupported": "value"}
        ),
        lambda value: value.update(trace={"correlation_id": "x" * 129}),
    ),
)
def test_ca02b_runtime_and_openapi_reject_authority_or_trace_drift(mutation) -> None:
    candidate = _work_result()
    mutation(candidate)

    _assert_runtime_and_openapi_reject(candidate)


@pytest.mark.parametrize(
    "payload",
    (None, "scalar", ["list", 1], 42, True, {"nested": {"value": 1}}),
)
def test_ca02b_payload_accepts_every_json_shape(payload: object) -> None:
    result = _work_result(payload=payload)

    assert validate_work_result(result)["payload"] == payload
    _openapi_validator("WorkResult").validate(result)


def test_ca02b_wrapper_requires_expected_version_and_work_result() -> None:
    validator = _openapi_validator("WorkResultSubmitRequest")
    valid = {"expected_version": 1, "work_result": _work_result()}

    validator.validate(valid)
    for field in ("expected_version", "work_result"):
        candidate = copy.deepcopy(valid)
        candidate.pop(field)
        assert list(validator.iter_errors(candidate))
