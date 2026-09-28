from __future__ import annotations

from copy import deepcopy
import hashlib

import pytest

from nex_ae_api.chat import SqlAlchemyChatInteractionStore
from nex_ae_api.citation_quality_workflow import build_citation_quality_workflow
from nex_ae_api.generated_response_lineage import (
    AeGeneratedResponseLineageError,
    attach_generated_response_lineage,
    generated_response_lineage_from_record,
    generated_response_storage_metadata_from_lineage,
    prepare_generated_response,
    validate_generated_response_lineage,
)
from test_nex_ae_chat import sqlite_chat_session_factory


INTERACTION_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
CHAT_DOCUMENT_ID = "62cbb468-147e-5e66-9bd8-4551a5807cf6"
CX_GENERATION_ID = "cx-generation-001"


def sample_record(*, retry: bool = False) -> dict:
    generation = {
        "async_generation": {
            "job_id": "cx-job-001",
            "cx_generation_id": CX_GENERATION_ID,
        }
    }
    if retry:
        generation["retry_lineage"] = {
            "retry_lineage_schema_version": "ae_async_generation_retry_lineage.v1",
            "parent_interaction_id": "parent-interaction-001",
            "parent_job_id": "parent-job-001",
            "parent_cx_generation_id": "parent-generation-001",
            "raw_input_included": False,
        }
    return {
        "interaction_schema_version": "ae_chat_interaction.v1",
        "interaction_id": INTERACTION_ID,
        "workspace_id": "11111111-1111-4111-8111-111111111111",
        "chat_document_id": CHAT_DOCUMENT_ID,
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "owner_user_id": "user-a",
        "status": "COMPLETED",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "request-001",
        "user_message_hash": "a" * 64,
        "user_message_preview": "Summarize the private document.",
        "cx_generation_id": CX_GENERATION_ID,
        "cx_status": "SUCCEEDED",
        "generation": generation,
        "retrieval": {
            "cx_retrieval_package_id": "retrieval-001",
            "cx_package_hash": "b" * 64,
        },
        "failure": None,
        "artifact_refs": [],
        "created_at": "2026-09-29T00:00:00Z",
        "updated_at": "2026-09-29T00:00:01Z",
    }


def sample_refresh(content: str = "Grounded answer with citation [1].") -> dict:
    encoded = content.encode("utf-8")
    return {
        "refresh_schema_version": "ae_async_generation_refresh.v1",
        "handoff_status": "READY",
        "cx_generation_id": CX_GENERATION_ID,
        "content": content,
        "content_type": "text/markdown; charset=utf-8",
        "content_sha256": hashlib.sha256(encoded).hexdigest(),
        "size_bytes": len(encoded),
        "owner_scope_enforced": True,
    }


def sample_workflow(*, repaired: bool = False) -> dict:
    repair = None
    if repaired:
        repair = {
            "repair_schema_version": "cx_citation_repair.v1",
            "mode": "BOUNDED_INLINE",
            "attempted": True,
            "attempt_count": 1,
            "max_attempts": 1,
            "trigger_error_code": "cx.citation_validation_failed",
            "same_retrieval_package": True,
            "original_provider_prompt_package_hash": "c" * 64,
            "effective_provider_prompt_package_hash": "d" * 64,
            "invalid_output_included": False,
        }
    return build_citation_quality_workflow(
        {
            "cx_generation_id": CX_GENERATION_ID,
            "request_metadata": {
                "grounding_required": True,
                "retrieval_package_id": "retrieval-001",
                "retrieval_package_hash": "b" * 64,
                "structured_draft_id": "draft-001",
                "draft_validation_status": "VALIDATED",
                "grounded_response_quality_audit_schema_version": (
                    "cx_grounded_response_citation_quality_audit.v1"
                ),
                "grounded_response_quality_status": "PASS",
                "grounded_response_quality_issue_count": 0,
                "citation_repair": repair,
            },
        },
        interaction_id=INTERACTION_ID,
    )


def sample_bundle(*, retry: bool = False, repaired: bool = False) -> dict:
    return prepare_generated_response(
        sample_record(retry=retry),
        sample_refresh(),
        sample_workflow(repaired=repaired),
        parent_response_id="parent-response-001" if retry else None,
    )


def test_prepare_original_response_separates_private_payload_and_public_lineage() -> None:
    bundle = sample_bundle()
    lineage = bundle["lineage"]
    payload = bundle["storage_payload"]

    assert lineage["lineage_type"] == "ORIGINAL"
    assert lineage["citation_workflow_status"] == "VALIDATED"
    assert lineage["retrieval_package_id"] == "retrieval-001"
    assert lineage["structured_draft_id"] == "draft-001"
    assert lineage["raw_content_included"] is False
    assert lineage["storage_ref_included"] is False
    assert "content" not in lineage
    assert "storage_ref" not in lineage
    assert payload["content"] == "Grounded answer with citation [1]."
    assert payload["response_id"] == lineage["response_id"]
    assert generated_response_storage_metadata_from_lineage(lineage) == {
        key: value for key, value in payload.items() if key != "content"
    }
    assert sample_bundle()["lineage"]["response_id"] == lineage["response_id"]


def test_prepare_retry_and_repaired_response_records_parent_lineage() -> None:
    lineage = sample_bundle(retry=True, repaired=True)["lineage"]

    assert lineage["lineage_type"] == "RETRY_CHILD"
    assert lineage["parent_interaction_id"] == "parent-interaction-001"
    assert lineage["parent_response_id"] == "parent-response-001"
    assert lineage["citation_workflow_status"] == "REPAIRED"
    assert lineage["bounded_repair_applied"] is True


def test_attach_and_sqlite_round_trip_preserve_metadata_without_private_content() -> None:
    record = sample_record()
    lineage = sample_bundle()["lineage"]
    attached = attach_generated_response_lineage(record, lineage)
    repeated = attach_generated_response_lineage(attached, lineage)
    store = SqlAlchemyChatInteractionStore(sqlite_chat_session_factory())

    store.save(repeated)
    loaded = store.get(INTERACTION_ID)

    assert loaded is not None
    assert generated_response_lineage_from_record(loaded) == lineage
    encoded_generation = str(loaded["generation"])
    assert "Grounded answer" not in encoded_generation
    assert "ae://chat-responses/" not in encoded_generation
    assert record["generation"].get("generated_response") is None


def test_lineage_lookup_returns_none_and_rejects_cross_record_drift() -> None:
    assert generated_response_lineage_from_record({"generation": None}) is None
    assert generated_response_lineage_from_record(sample_record()) is None
    attached = attach_generated_response_lineage(
        sample_record(), sample_bundle()["lineage"]
    )
    attached["chat_document_id"] = "different-chat"

    with pytest.raises(AeGeneratedResponseLineageError) as error:
        generated_response_lineage_from_record(attached)

    assert error.value.error_code == "ae.generated_response_lineage_invalid"


def test_prepare_rejects_invalid_record_refresh_workflow_and_retrieval() -> None:
    invalid_cases = []
    missing_generation = sample_record()
    missing_generation["generation"] = None
    invalid_cases.append((missing_generation, sample_refresh(), sample_workflow()))
    missing_projection = sample_record()
    missing_projection["generation"] = {}
    invalid_cases.append((missing_projection, sample_refresh(), sample_workflow()))
    mismatched_record = sample_record()
    mismatched_record["cx_generation_id"] = "different"
    invalid_cases.append((mismatched_record, sample_refresh(), sample_workflow()))
    bad_refresh = sample_refresh()
    bad_refresh["handoff_status"] = "PENDING"
    invalid_cases.append((sample_record(), bad_refresh, sample_workflow()))
    bad_workflow = sample_workflow()
    bad_workflow["interaction_id"] = "different"
    invalid_cases.append((sample_record(), sample_refresh(), bad_workflow))
    bad_retrieval = sample_record()
    bad_retrieval["retrieval"]["cx_package_hash"] = "e" * 64
    invalid_cases.append((bad_retrieval, sample_refresh(), sample_workflow()))

    for record, refresh, workflow in invalid_cases:
        with pytest.raises(AeGeneratedResponseLineageError):
            prepare_generated_response(record, refresh, workflow)


def test_prepare_rejects_integrity_and_retry_parent_errors() -> None:
    bad_hash = sample_refresh()
    bad_hash["content_sha256"] = "f" * 64
    with pytest.raises(AeGeneratedResponseLineageError, match="integrity"):
        prepare_generated_response(sample_record(), bad_hash, sample_workflow())

    with pytest.raises(AeGeneratedResponseLineageError, match="parent_response_id"):
        prepare_generated_response(
            sample_record(retry=True), sample_refresh(), sample_workflow()
        )
    with pytest.raises(AeGeneratedResponseLineageError, match="cannot have"):
        prepare_generated_response(
            sample_record(),
            sample_refresh(),
            sample_workflow(),
            parent_response_id="unexpected",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("extra", "unexpected"),
        ("content", None),
        ("content_type", None),
        ("size_bytes", True),
    ],
)
def test_prepare_rejects_invalid_refresh_shape_and_values(
    field: str, value: object
) -> None:
    refresh = sample_refresh()
    refresh[field] = value

    with pytest.raises(AeGeneratedResponseLineageError):
        prepare_generated_response(sample_record(), refresh, sample_workflow())


def test_prepare_converts_storage_validation_and_workflow_errors() -> None:
    unsupported_type = sample_refresh()
    unsupported_type["content_type"] = "application/json"
    with pytest.raises(AeGeneratedResponseLineageError, match="content type"):
        prepare_generated_response(
            sample_record(), unsupported_type, sample_workflow()
        )

    workflow = sample_workflow()
    workflow["extra"] = True
    with pytest.raises(AeGeneratedResponseLineageError, match="shape"):
        prepare_generated_response(sample_record(), sample_refresh(), workflow)


def test_prepare_rejects_retry_shape_and_retrieval_id_drift() -> None:
    invalid_retry = sample_record()
    invalid_retry["generation"]["retry_lineage"] = "invalid"
    with pytest.raises(AeGeneratedResponseLineageError, match="retry lineage"):
        prepare_generated_response(invalid_retry, sample_refresh(), sample_workflow())

    bad_retrieval_id = sample_record()
    bad_retrieval_id["retrieval"]["cx_retrieval_package_id"] = "different"
    with pytest.raises(AeGeneratedResponseLineageError, match="package ID"):
        prepare_generated_response(
            bad_retrieval_id, sample_refresh(), sample_workflow()
        )

    no_retrieval = sample_record()
    no_retrieval["retrieval"] = None
    assert prepare_generated_response(
        no_retrieval, sample_refresh(), sample_workflow()
    )["lineage"]["retrieval_package_id"] == "retrieval-001"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lineage_schema_version", "v0"),
        ("response_id", ""),
        ("lineage_type", "UNKNOWN"),
        ("content_type", "application/json"),
        ("content_sha256", "bad"),
        ("size_bytes", True),
        ("content_available", False),
        ("citation_workflow_status", "UNKNOWN"),
        ("bounded_repair_applied", "false"),
        ("owner_scope_enforced", False),
        ("raw_content_included", True),
        ("storage_ref_included", True),
    ],
)
def test_lineage_validator_rejects_invalid_fields(field: str, value: object) -> None:
    lineage = sample_bundle()["lineage"]
    lineage[field] = value

    with pytest.raises(AeGeneratedResponseLineageError):
        validate_generated_response_lineage(lineage)


def test_lineage_validator_rejects_shape_parent_repair_and_conflict_drift() -> None:
    lineage = sample_bundle()["lineage"]
    with pytest.raises(AeGeneratedResponseLineageError, match="shape"):
        validate_generated_response_lineage({**lineage, "content": "private"})
    with pytest.raises(AeGeneratedResponseLineageError, match="parent"):
        validate_generated_response_lineage(
            {**lineage, "parent_response_id": "parent"}
        )
    with pytest.raises(AeGeneratedResponseLineageError, match="incomplete"):
        validate_generated_response_lineage(
            {
                **lineage,
                "lineage_type": "RETRY_CHILD",
                "parent_interaction_id": "parent",
            }
        )
    with pytest.raises(AeGeneratedResponseLineageError, match="repair"):
        validate_generated_response_lineage(
            {**lineage, "bounded_repair_applied": True}
        )

    attached = attach_generated_response_lineage(sample_record(), lineage)
    different = deepcopy(lineage)
    different["response_id"] = "different-response"
    with pytest.raises(AeGeneratedResponseLineageError) as error:
        attach_generated_response_lineage(attached, different)
    assert error.value.status_code == 409


def test_lineage_validator_accepts_nullable_retrieval_hash() -> None:
    lineage = sample_bundle()["lineage"]
    lineage["retrieval_package_hash"] = None

    assert validate_generated_response_lineage(lineage)[
        "retrieval_package_hash"
    ] is None


def test_attach_rejects_missing_generation_and_cross_chat_lineage() -> None:
    lineage = sample_bundle()["lineage"]
    with pytest.raises(AeGeneratedResponseLineageError, match="missing"):
        attach_generated_response_lineage({"generation": None}, lineage)

    with pytest.raises(AeGeneratedResponseLineageError, match="inconsistent"):
        attach_generated_response_lineage(
            sample_record(), {**lineage, "interaction_id": "different"}
        )
