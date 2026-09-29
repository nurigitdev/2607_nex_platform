from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError

from nex_ae_api.async_generation import build_async_generation_projection
from nex_ae_api.generation_progress import (
    build_generation_progress_projection,
    build_generation_recovery_plan,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
PROGRESS_SCHEMA = (
    CONTRACTS
    / "schemas/service/nex_ae_api/generation_progress.v1.schema.json"
)
RECOVERY_SCHEMA = (
    CONTRACTS
    / "schemas/service/nex_ae_api/generation_recovery_plan.v1.schema.json"
)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _job(status: str, *, retryable: bool = True) -> dict:
    error = None
    if status in {"FAILED", "CANCELLED"}:
        error = {
            "error_code": "cx.generation.failed",
            "retryable": retryable,
            "dead_lettered": not retryable,
        }
    return {
        "job_id": "job-contract",
        "cx_generation_id": "generation-contract",
        "status": status,
        "attempt_count": 1 if status != "QUEUED" else 0,
        "max_attempts": 3,
        "retryable": retryable,
        "links": {
            "generation": "/api/v1/generations/generation-contract",
            "async_job": "/api/v1/generation-jobs/job-contract",
        },
        "error": error,
    }


def _projection(status: str, *, retryable: bool = True) -> dict:
    return build_async_generation_projection(
        {
            "admission_status": "ENQUEUED",
            "job": _job(status, retryable=retryable),
            "generation": None,
        }
    )


@pytest.mark.parametrize(
    ("status", "retryable"),
    [
        ("QUEUED", True),
        ("RUNNING", True),
        ("SUCCEEDED", False),
        ("FAILED", True),
        ("FAILED", False),
        ("CANCELLED", True),
    ],
)
def test_runtime_progress_and_recovery_validate_against_canonical_schemas(
    status: str,
    retryable: bool,
) -> None:
    projection = _projection(status, retryable=retryable)
    progress = build_generation_progress_projection(
        interaction_id="interaction-contract",
        async_generation=projection,
    )
    recovery = build_generation_recovery_plan(projection)

    Draft202012Validator(_load(PROGRESS_SCHEMA)).validate(progress)
    Draft202012Validator(_load(RECOVERY_SCHEMA)).validate(recovery)


def test_completed_runtime_progress_validates_against_canonical_schema() -> None:
    projection = _projection("SUCCEEDED", retryable=False)
    projection.update(
        lifecycle_status="COMPLETED",
        handoff_status="READY",
        next_action="PRESENT_GENERATION_TO_OWNER",
    )

    Draft202012Validator(_load(PROGRESS_SCHEMA)).validate(
        build_generation_progress_projection(
            interaction_id="interaction-completed",
            async_generation=projection,
        )
    )


@pytest.mark.parametrize(
    ("payload_path", "schema_path"),
    [
        (
            "examples/generation/ae_generation_progress.queued.json",
            PROGRESS_SCHEMA,
        ),
        (
            "examples/generation/ae_generation_progress.completed.json",
            PROGRESS_SCHEMA,
        ),
        (
            "examples/generation/ae_generation_recovery_plan.retry.json",
            RECOVERY_SCHEMA,
        ),
    ],
)
def test_registered_positive_examples_validate(payload_path, schema_path) -> None:
    Draft202012Validator(_load(schema_path)).validate(
        _load(CONTRACTS / payload_path)
    )


@pytest.mark.parametrize(
    ("payload_path", "schema_path"),
    [
        (
            "tests/negative/generation/ae_generation_progress.content_leak.json",
            PROGRESS_SCHEMA,
        ),
        (
            "tests/negative/generation/ae_generation_progress.completed_wrong_percent.json",
            PROGRESS_SCHEMA,
        ),
        (
            "tests/negative/generation/ae_generation_recovery_plan.retry_without_lineage.json",
            RECOVERY_SCHEMA,
        ),
    ],
)
def test_registered_negative_examples_are_rejected(payload_path, schema_path) -> None:
    with pytest.raises(ValidationError):
        Draft202012Validator(_load(schema_path)).validate(
            _load(CONTRACTS / payload_path)
        )


def test_openapi_exposes_canonical_progress_and_recovery_routes() -> None:
    spec = yaml.safe_load(
        (CONTRACTS / "openapi/nex-ae-api.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert spec["info"]["version"] == "1.7.0"
    paths = spec["paths"]
    assert paths["/api/v1/chat/interactions/{interaction_id}/progress"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/AeGenerationProgress"
    )
    assert paths["/api/v1/chat/interactions/{interaction_id}/recovery"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/AeGenerationRecoveryPlan"
    )
    schemas = spec["components"]["schemas"]
    assert schemas["AeGenerationProgress"]["x-nex-canonical-json-schema"] == (
        "schemas/service/nex_ae_api/generation_progress.v1.schema.json"
    )
    assert schemas["AeGenerationRecoveryPlan"][
        "x-nex-canonical-json-schema"
    ] == "schemas/service/nex_ae_api/generation_recovery_plan.v1.schema.json"
