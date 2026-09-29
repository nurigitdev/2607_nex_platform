from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError

from nex_ae_api.artifacts import ArtifactRecordStore
from nex_ae_api.async_artifact_render_recovery import (
    inspect_async_artifact_render_recovery,
    reconcile_async_artifact_render,
)
from nex_ae_api.async_artifact_rendering import (
    admit_async_artifact_render,
    build_async_artifact_render_request,
    get_async_artifact_render_projection,
)
from nex_runtime import InMemoryJobQueue, build_job_error


ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-09-29T08:00:00Z"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64

SCHEMA_FILES = {
    "request": "async_artifact_render_request.v1.schema.json",
    "projection": "async_artifact_render_projection.v1.schema.json",
    "admission": "async_artifact_render_admission.v1.schema.json",
    "recovery": "async_artifact_render_recovery.v1.schema.json",
    "reconciliation": "async_artifact_render_reconciliation.v1.schema.json",
}

EXAMPLE_FILES = {
    "request": "ae_async_artifact_render_request.queued.json",
    "projection": "ae_async_artifact_render_projection.queued.json",
    "admission": "ae_async_artifact_render_admission.enqueued.json",
    "recovery": "ae_async_artifact_render_recovery.retry_scheduled.json",
    "reconciliation": (
        "ae_async_artifact_render_reconciliation.retry_reset.json"
    ),
}

NEGATIVE_FILES = {
    "request": "ae_async_artifact_render_request.raw_content_leak.json",
    "projection": (
        "ae_async_artifact_render_projection.content_flag_true.json"
    ),
    "admission": "ae_async_artifact_render_admission.storage_ref_leak.json",
    "recovery": "ae_async_artifact_render_recovery.raw_error_detail.json",
    "reconciliation": (
        "ae_async_artifact_render_reconciliation.content_leak.json"
    ),
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema(name: str) -> dict:
    return _json(
        ROOT
        / "contracts/schemas/service/nex_ae_api"
        / SCHEMA_FILES[name]
    )


def _artifact() -> dict:
    return {
        "artifact_id": "artifact-1",
        "artifact_status": "DRAFT",
        "chat_document_id": "chat-document-1",
        "interaction_id": "interaction-1",
        "owner_actor_ref": {
            "actor_type": "user",
            "actor_id": "owner-1",
            "tenant_id": "tenant-1",
        },
        "workspace_ref": {
            "workspace_id": "workspace-1",
            "tenant_id": "tenant-1",
        },
        "source_refs": [
            {
                "cx_generation_id": "generation-1",
                "structured_draft_id": "draft-1",
                "structured_draft_content_hash": DIGEST_A,
                "citation_claims_hash": DIGEST_B,
            }
        ],
        "versions": [],
        "render_jobs": [],
        "files": [],
        "links": [],
        "updated_at": NOW,
    }


def _runtime_values() -> dict[str, dict]:
    store = ArtifactRecordStore()
    store.create(_artifact())
    queue = InMemoryJobQueue()
    request = build_async_artifact_render_request(
        artifact_record=_artifact(),
        render_request_id="render-request-1",
        target_formats=["MD", "PDF"],
        request_id="request-1",
        trace_id="trace-1",
        response_id="response-1",
        max_attempts=3,
        requested_at=NOW,
    )
    admission = admit_async_artifact_render(
        request=request,
        artifact_store=store,
        job_queue=queue,
    )
    projection = get_async_artifact_render_projection(
        render_job_id=request["render_job_id"],
        artifact_store=store,
        job_queue=queue,
    )
    queue.start_job(request["render_job_id"], updated_at=NOW)
    render = store.get_render_job(request["render_job_id"])
    store.save_render_job_state(
        {
            **render,
            "job_status": "RUNNING",
            "current_stage": "HANDOFF_VALIDATING",
            "progress_percent": 10,
            "started_at": NOW,
            "updated_at": NOW,
        }
    )
    queue.retry_job(
        request["render_job_id"],
        error=build_job_error(
            error_code="ae.render_dependency_unavailable",
            detail="private dependency detail",
            retryable=True,
        ),
        failed_at=NOW,
    )
    recovery = inspect_async_artifact_render_recovery(
        render_job_id=request["render_job_id"],
        artifact_store=store,
        job_queue=queue,
    )
    reconciliation = reconcile_async_artifact_render(
        render_job_id=request["render_job_id"],
        artifact_store=store,
        job_queue=queue,
        observed_at="2026-09-29T08:00:01Z",
    )
    return {
        "request": request,
        "projection": projection,
        "admission": admission,
        "recovery": recovery,
        "reconciliation": reconciliation,
    }


@pytest.mark.parametrize("name", SCHEMA_FILES)
def test_async_artifact_render_schemas_accept_examples_and_runtime_values(
    name: str,
) -> None:
    validator = Draft202012Validator(_schema(name))
    validator.validate(
        _json(ROOT / "contracts/examples/generation" / EXAMPLE_FILES[name])
    )
    validator.validate(_runtime_values()[name])


@pytest.mark.parametrize("name", NEGATIVE_FILES)
def test_async_artifact_render_contracts_reject_private_or_invalid_state(
    name: str,
) -> None:
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema(name)).validate(
            _json(
                ROOT
                / "contracts/tests/negative/generation"
                / NEGATIVE_FILES[name]
            )
        )


def test_admission_contract_accepts_idempotent_join_of_running_render() -> None:
    admission = _json(
        ROOT
        / "contracts/examples/generation"
        / EXAMPLE_FILES["admission"]
    )
    admission["admission_status"] = "JOINED"
    admission["render"].update(
        lifecycle_status="RUNNING",
        render_job_status="RUNNING",
        queue_job_status="RUNNING",
        current_stage="HANDOFF_VALIDATING",
        progress_percent=10,
        attempt_count=1,
    )

    Draft202012Validator(_schema("admission")).validate(admission)


def test_openapi_exposes_async_artifact_render_lifecycle_contracts() -> None:
    spec = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-ae-api.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    paths = spec["paths"]
    schemas = spec["components"]["schemas"]

    assert spec["info"]["version"] == "1.7.0"
    assert paths["/api/v1/artifacts/{artifact_id}/async-render-jobs"]["post"][
        "operationId"
    ] == "createAeAsyncArtifactRenderJob"
    assert paths["/api/v1/async-artifact-render-jobs/{render_job_id}"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/AeAsyncArtifactRenderProjection"
    )
    assert paths[
        "/api/v1/async-artifact-render-jobs/{render_job_id}/recovery"
    ]["get"]["operationId"] == "getAeAsyncArtifactRenderRecovery"
    assert paths[
        "/api/v1/async-artifact-render-jobs/{render_job_id}/reconcile"
    ]["post"]["operationId"] == "reconcileAeAsyncArtifactRenderJob"

    expected_canonical = {
        "AeAsyncArtifactRenderProjection": SCHEMA_FILES["projection"],
        "AeAsyncArtifactRenderAdmission": SCHEMA_FILES["admission"],
        "AeAsyncArtifactRenderRecovery": SCHEMA_FILES["recovery"],
        "AeAsyncArtifactRenderReconciliation": SCHEMA_FILES["reconciliation"],
    }
    for component, schema_file in expected_canonical.items():
        assert schemas[component]["x-nex-canonical-json-schema"].endswith(
            schema_file
        )
        assert "content" not in schemas[component].get("properties", {})
        assert "storage_ref" not in schemas[component].get("properties", {})


def test_contract_indexes_register_all_async_artifact_examples() -> None:
    examples = _json(ROOT / "contracts/examples/index.json")["examples"]
    negatives = _json(ROOT / "contracts/tests/negative/index.json")[
        "negative_examples"
    ]
    example_paths = {entry["path"] for entry in examples}
    negative_paths = {entry["path"] for entry in negatives}

    assert {
        f"examples/generation/{filename}" for filename in EXAMPLE_FILES.values()
    }.issubset(example_paths)
    assert {
        f"tests/negative/generation/{filename}"
        for filename in NEGATIVE_FILES.values()
    }.issubset(negative_paths)
