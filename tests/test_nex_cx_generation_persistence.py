from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.generation_persistence import (
    CxGenerationPersistenceError,
    build_generation_persistence_record,
    generation_persistence_has_private_payload,
)
from nex_cx.owner_lineage import build_owner_lineage


NOW = datetime(2026, 9, 21, tzinfo=UTC)


def _lineage():
    return build_owner_lineage(
        CxAccessContext(
            caller_service_id="nex-cx",
            tenant_id="tenant-a",
            subject_id="employee-1004",
            request_id="request-0917",
            trace_id="91700000000000000000000000000001",
            scopes=("service:call",),
        )
    )


def _record(**overrides):
    value = {
        "record_schema_version": "cx_generation_execution_record.v1",
        "cx_generation_id": "cx-gen-0917",
        "status": "COMPLETED",
        "trace_id": "91700000000000000000000000000001",
        "request_id": "request-0917",
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "mo_generation_id": "mo-gen-0917",
        "request_metadata": {
            "generation_request_hash": "a" * 64,
            "retrieval_package_id": "91700000-0000-0000-0000-000000000001",
            "source_has_prompt": True,
            "prompt": "private prompt",
            "nested": {"text": "private"},
        },
        "response_metadata": {
            "finish_reason": "stop",
            "output_hash": "b" * 64,
            "output_preview": "private output",
        },
        "mo_runtime_metadata": {
            "queue_ms": 1,
            "provider_ms": 2,
            "total_ms": 3,
            "provider_url": "private endpoint",
        },
        "usage": {"input_tokens": 2, "output_tokens": 3, "unknown": 9},
        "created_at": NOW,
        "updated_at": NOW,
    }
    value.update(overrides)
    return value


def test_build_generation_persistence_record_keeps_only_safe_metadata() -> None:
    persisted = build_generation_persistence_record(_record(), owner_lineage=_lineage())

    assert persisted["tenant_ref_id"] == "tenant-a"
    assert persisted["owner_subject_ref_id"] == "employee-1004"
    assert persisted["retrieval_package_id"] == "91700000-0000-0000-0000-000000000001"
    assert "retrieval_package_id" not in persisted["request_metadata"]
    assert persisted["request_metadata"]["source_has_prompt"] is True
    assert "prompt" not in persisted["request_metadata"]
    assert "nested" not in persisted["request_metadata"]
    assert persisted["response_metadata"] == {
        "finish_reason": "stop",
        "output_hash": "b" * 64,
    }
    assert persisted["mo_runtime_metadata"] == {
        "queue_ms": 1,
        "provider_ms": 2,
        "total_ms": 3,
    }
    assert persisted["usage"] == {"input_tokens": 2, "output_tokens": 3}
    assert persisted["failure"] is None
    assert generation_persistence_has_private_payload(persisted) is False


def test_build_failed_generation_persistence_record_keeps_safe_lineage() -> None:
    persisted = build_generation_persistence_record(
        _record(
            status="FAILED",
            mo_generation_id=None,
            failure={
                "failure_code": "mo.provider_timeout",
                "retryable": True,
                "safe_message": "untrusted message",
                "detail": "private detail",
            },
            recovery_lineage={
                "root_generation_id": "cx-gen-root",
                "attempt_no": 2,
                "changed_fields": ["temperature"],
                "prompt": "private",
            },
        ),
        owner_lineage=_lineage(),
    )

    assert persisted["failure"] == {
        "failure_code": "mo.provider_timeout",
        "retryable": True,
    }
    assert persisted["recovery_lineage"] == {
        "root_generation_id": "cx-gen-root",
        "attempt_no": 2,
        "changed_fields": ["temperature"],
    }


@pytest.mark.parametrize(
    ("status", "failure"),
    [("COMPLETED", {"failure_code": "failed"}), ("FAILED", None)],
)
def test_generation_persistence_rejects_status_failure_mismatch(status, failure) -> None:
    with pytest.raises(CxGenerationPersistenceError) as caught:
        build_generation_persistence_record(
            _record(status=status, failure=failure),
            owner_lineage=_lineage(),
        )

    assert caught.value.error_code == "CX_GENERATION_PERSISTENCE_STATUS_INVALID"


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "RUNNING"},
        {"record_schema_version": "v2"},
        {"cx_generation_id": ""},
        {"request_id": 1},
        {"alias": "x" * 257},
        {"provider_capability": None},
        {"trace_id": "not-a-trace"},
        {"mo_generation_id": ""},
        {"request_metadata": []},
        {"response_metadata": []},
        {"mo_runtime_metadata": []},
        {"usage": []},
        {"usage": {"input_tokens": -1}},
        {"created_at": "2026-09-21"},
        {"updated_at": None},
    ],
)
def test_generation_persistence_rejects_invalid_records(overrides) -> None:
    with pytest.raises(CxGenerationPersistenceError) as caught:
        build_generation_persistence_record(
            _record(**overrides),
            owner_lineage=_lineage(),
        )

    assert caught.value.error_code == "CX_GENERATION_PERSISTENCE_INVALID"


@pytest.mark.parametrize("retrieval_id", [1, "not-a-uuid"])
def test_generation_persistence_rejects_invalid_retrieval_package_id(retrieval_id) -> None:
    request_metadata = _record()["request_metadata"] | {
        "retrieval_package_id": retrieval_id
    }
    with pytest.raises(CxGenerationPersistenceError):
        build_generation_persistence_record(
            _record(request_metadata=request_metadata),
            owner_lineage=_lineage(),
        )


def test_generation_persistence_accepts_absent_optional_metadata() -> None:
    persisted = build_generation_persistence_record(
        _record(
            request_metadata=None,
            response_metadata=None,
            mo_runtime_metadata=None,
            usage=None,
            mo_generation_id=None,
        ),
        owner_lineage=_lineage(),
    )

    assert persisted["retrieval_package_id"] is None
    assert persisted["request_metadata"] == {}
    assert persisted["response_metadata"] == {}
    assert persisted["usage"] == {}


def test_generation_persistence_keeps_private_output_reference_metadata() -> None:
    persisted = build_generation_persistence_record(
        _record(
            response_metadata={
                "finish_reason": "STOP",
                "output_hash": "b" * 64,
                "private_output_schema_version": "cx_generation_private_output.v1",
                "output_storage_backend": "filesystem-text-v1",
                "output_storage_uri": "cx-private://filesystem-text-v1/safe/ref",
                "output_size_bytes": 42,
            }
        ),
        owner_lineage=_lineage(),
    )

    assert persisted["response_metadata"]["output_storage_uri"].startswith(
        "cx-private://"
    )
    assert generation_persistence_has_private_payload(persisted) is False


def test_private_payload_detection_is_recursive() -> None:
    assert generation_persistence_has_private_payload({"prompt": "private"}) is True
    assert generation_persistence_has_private_payload(
        {"safe": [{"output_preview": "private"}]}
    ) is True
    assert generation_persistence_has_private_payload(({"text": "private"},)) is True
    assert generation_persistence_has_private_payload("ordinary metadata") is False


def test_nested_metadata_values_are_discarded() -> None:
    persisted = build_generation_persistence_record(
        _record(
            request_metadata={"structured_draft_id": {"text": "private"}},
            recovery_lineage={"changed_fields": [{"prompt": "private"}]},
        ),
        owner_lineage=_lineage(),
    )

    assert persisted["request_metadata"] == {}
    assert persisted["recovery_lineage"] == {}


def test_generation_persistence_rejects_private_key_introduced_by_lineage(monkeypatch) -> None:
    monkeypatch.setattr(
        "nex_cx.generation_persistence.attach_owner_lineage",
        lambda record, lineage: {**record, "prompt": "private"},
    )
    with pytest.raises(CxGenerationPersistenceError) as caught:
        build_generation_persistence_record(_record(), owner_lineage=_lineage())

    assert caught.value.error_code == "CX_GENERATION_PERSISTENCE_PRIVATE_PAYLOAD"
