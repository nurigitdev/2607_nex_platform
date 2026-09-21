from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError
from openapi_spec_validator import validate

from nex_runtime import (
    CX_INGESTION_LEASE_RECOVERED_EVENT,
    operational_event_taxonomy_by_type,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "contracts/schemas/service/nex_cx"
EXAMPLE_ROOT = ROOT / "contracts/examples"
OPENAPI_PATH = ROOT / "contracts/openapi/nex-cx.openapi.yaml"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("schema_name", "example_path"),
    [
        (
            "ingestion_run_read_model.v1.schema.json",
            "retrieval/cx_ingestion_run_read_model.mock_success.json",
        ),
        (
            "ingestion_restart_plan.v1.schema.json",
            "operations/cx_ingestion_restart_plan.mock_success.json",
        ),
        (
            "ingestion_recovery.v1.schema.json",
            "operations/cx_ingestion_recovery.mock_success.json",
        ),
    ],
)
def test_ingestion_operations_examples_validate(
    schema_name: str, example_path: str
) -> None:
    schema = load_json(SCHEMA_ROOT / schema_name)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(load_json(EXAMPLE_ROOT / example_path))


def test_ingestion_contracts_reject_private_or_mutating_fields() -> None:
    read_model_schema = load_json(
        SCHEMA_ROOT / "ingestion_run_read_model.v1.schema.json"
    )
    read_model = load_json(
        EXAMPLE_ROOT / "retrieval/cx_ingestion_run_read_model.mock_success.json"
    )
    read_model["source_text"] = "private"
    with pytest.raises(ValidationError):
        Draft202012Validator(read_model_schema).validate(read_model)

    restart_schema = load_json(
        SCHEMA_ROOT / "ingestion_restart_plan.v1.schema.json"
    )
    restart = load_json(
        EXAMPLE_ROOT / "operations/cx_ingestion_restart_plan.mock_success.json"
    )
    restart["mutation_performed"] = True
    with pytest.raises(ValidationError):
        Draft202012Validator(restart_schema).validate(restart)


def test_openapi_freezes_owner_and_internal_ingestion_routes() -> None:
    contract = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    validate(contract)

    paths = contract["paths"]
    assert paths["/api/v1/ingestion-runs/{run_id}"]["get"]["operationId"] == (
        "getCxOwnerScopedIngestionRun"
    )
    assert paths["/api/v1/documents/{document_id}/ingestion-runs"]["get"][
        "operationId"
    ] == "listCxOwnerScopedDocumentIngestionRuns"
    restart = paths["/internal/v1/ingestion/restart-plan"]["get"]
    assert restart["parameters"][0]["schema"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 500,
    }
    recovery = paths[
        "/internal/v1/ingestion/jobs/{job_id}/recover-expired-lease"
    ]["post"]
    assert set(recovery["responses"]) == {"200", "401", "404", "409", "503"}
    assert contract["components"]["schemas"]["CxIngestionRestartPlan"][
        "properties"
    ]["mutation_performed"] == {"const": False}


def test_recovery_event_taxonomy_is_metadata_only() -> None:
    event = operational_event_taxonomy_by_type()[
        CX_INGESTION_LEASE_RECOVERED_EVENT
    ]
    assert event["default_severity"] == "WARNING"
    assert event["subject_type"] == "job"
    assert event["lifecycle_state"] == "recovered"
    sensitive_tokens = {"payload", "source_text", "prompt", "vector", "authorization"}
    assert sensitive_tokens.isdisjoint(event["detail_keys"])
