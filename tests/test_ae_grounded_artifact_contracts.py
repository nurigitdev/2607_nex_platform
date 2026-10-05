from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
ADMISSION_SCHEMA = (
    CONTRACTS
    / "schemas/service/nex_ae_api/grounded_artifact_admission.v1.schema.json"
)
ARTIFACT_SCHEMA = (
    CONTRACTS / "schemas/generation/ae_artifact_record.v1.schema.json"
)
RENDER_ADMISSION_SCHEMA = (
    CONTRACTS
    / "schemas/service/nex_ae_api/async_artifact_render_admission.v1.schema.json"
)
EXAMPLE = (
    CONTRACTS
    / "examples/generation/ae_grounded_artifact_admission.enqueued.json"
)
NEGATIVE = (
    CONTRACTS
    / "tests/negative/generation/"
    "ae_grounded_artifact_admission.content_leak.json"
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_grounded_artifact_admission_contract_validates_canonical_parts() -> None:
    payload = _json(EXAMPLE)

    Draft202012Validator(_json(ADMISSION_SCHEMA)).validate(payload)
    Draft202012Validator(_json(ARTIFACT_SCHEMA)).validate(payload["artifact"])
    Draft202012Validator(_json(RENDER_ADMISSION_SCHEMA)).validate(
        payload["render_admission"]
    )


def test_grounded_artifact_admission_contract_rejects_content_leak() -> None:
    with pytest.raises(ValidationError):
        Draft202012Validator(_json(ADMISSION_SCHEMA)).validate(_json(NEGATIVE))


def test_grounded_artifact_admission_preserves_exact_lineage_ids() -> None:
    payload = _json(EXAMPLE)
    artifact = payload["artifact"]
    source = artifact["source_refs"][0]
    render = payload["render_admission"]["render"]
    binding = payload["response_binding"]

    assert render["artifact_id"] == artifact["artifact_id"]
    assert artifact["render_jobs"][0]["render_job_id"] == render["render_job_id"]
    assert binding["interaction_id"] == artifact["interaction_id"]
    assert binding["chat_document_id"] == artifact["chat_document_id"]
    assert binding["cx_generation_id"] == source["cx_generation_id"]
    assert binding["structured_draft_id"] == source["structured_draft_id"]
    assert source["quality_summary"]["citation_status"] == "VALIDATED"


def test_artifact_contract_accepts_runtime_render_stages_and_timestamps() -> None:
    artifact = _json(EXAMPLE)["artifact"]
    validator = Draft202012Validator(_json(ARTIFACT_SCHEMA))

    for stage, job_status in (
        ("QUEUED", "QUEUED"),
        ("FAILED", "FAILED"),
        ("CANCELLED", "CANCELLED"),
    ):
        candidate = deepcopy(artifact)
        candidate["render_jobs"][0].update(
            current_stage=stage,
            job_status=job_status,
        )
        validator.validate(candidate)


def test_openapi_exposes_grounded_artifact_admission() -> None:
    spec = yaml.safe_load(
        (CONTRACTS / "openapi/nex-ae-api.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    route = spec["paths"]["/api/v1/generated-responses/{response_id}/artifacts"]
    operation = route["post"]
    schemas = spec["components"]["schemas"]

    assert spec["info"]["version"] == "1.7.0"
    assert operation["operationId"] == "createAeGroundedResponseArtifact"
    assert operation["responses"]["202"]["content"]["application/json"][
        "schema"
    ]["$ref"] == "#/components/schemas/AeGroundedArtifactAdmission"
    assert schemas["AeGroundedArtifactAdmission"][
        "x-nex-canonical-json-schema"
    ].endswith("grounded_artifact_admission.v1.schema.json")
    assert schemas["AeArtifactRecord"]["x-nex-canonical-json-schema"].endswith(
        "ae_artifact_record.v1.schema.json"
    )


def test_grounded_artifact_contract_fixtures_are_indexed() -> None:
    examples = _json(CONTRACTS / "examples/index.json")["examples"]
    negatives = _json(CONTRACTS / "tests/negative/index.json")[
        "negative_examples"
    ]

    assert any(
        entry["path"]
        == "examples/generation/ae_grounded_artifact_admission.enqueued.json"
        for entry in examples
    )
    assert any(
        entry["path"]
        == (
            "tests/negative/generation/"
            "ae_grounded_artifact_admission.content_leak.json"
        )
        for entry in negatives
    )
