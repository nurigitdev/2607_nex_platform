from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError
from openapi_spec_validator import validate


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "contracts/schemas/service/nex_cx"
EXAMPLE_ROOT = ROOT / "contracts/examples/retrieval"
NEGATIVE_ROOT = ROOT / "contracts/tests/negative/retrieval"
OPENAPI_PATH = ROOT / "contracts/openapi/nex-cx.openapi.yaml"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("schema_name", "example_name"),
    [
        (
            "document_intelligence_run.v1.schema.json",
            "cx_document_intelligence_run.mock_success.json",
        ),
        (
            "document_intelligence_similarity.v1.schema.json",
            "cx_document_intelligence_similarity.mock_success.json",
        ),
    ],
)
def test_document_intelligence_examples_validate(
    schema_name: str,
    example_name: str,
) -> None:
    schema = _json(SCHEMA_ROOT / schema_name)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_json(EXAMPLE_ROOT / example_name))


@pytest.mark.parametrize(
    ("schema_name", "negative_name"),
    [
        (
            "document_intelligence_run.v1.schema.json",
            "cx_document_intelligence_run.raw_summary_leak.json",
        ),
        (
            "document_intelligence_similarity.v1.schema.json",
            "cx_document_intelligence_similarity.vector_leak.json",
        ),
    ],
)
def test_document_intelligence_contracts_reject_private_payloads(
    schema_name: str,
    negative_name: str,
) -> None:
    validator = Draft202012Validator(_json(SCHEMA_ROOT / schema_name))

    with pytest.raises(ValidationError):
        validator.validate(_json(NEGATIVE_ROOT / negative_name))


def test_openapi_binds_explicit_document_intelligence_responses() -> None:
    contract = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    validate(contract)

    paths = contract["paths"]
    run_response = paths[
        "/api/v1/documents/{document_id}/intelligence/run"
    ]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    similarity_response = paths[
        "/api/v1/documents/{document_id}/intelligence/similar"
    ]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert run_response == {
        "$ref": "#/components/schemas/CxDocumentIntelligenceRun"
    }
    assert similarity_response == {
        "$ref": "#/components/schemas/CxDocumentIntelligenceSimilarity"
    }
    schemas = contract["components"]["schemas"]
    assert schemas["CxDocumentIntelligenceRun"]["additionalProperties"] is False
    assert (
        schemas["CxDocumentIntelligenceSimilarity"]["additionalProperties"]
        is False
    )
