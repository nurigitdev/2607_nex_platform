from __future__ import annotations

from typing import Any, Mapping

import pytest

from nex_ae_api.generated_response_handoff import persist_ready_generated_response
from nex_ae_api.generated_response_lineage import attach_generated_response_lineage
from nex_ae_api.generated_response_storage import (
    GeneratedResponseStorageError,
    InMemoryGeneratedResponseStorage,
)
from test_nex_ae_generated_response_lineage import (
    sample_bundle,
    sample_record,
    sample_refresh,
    sample_workflow,
)


def test_ready_handoff_persists_payload_then_safe_record_idempotently() -> None:
    storage = InMemoryGeneratedResponseStorage()
    saved_records: list[dict[str, Any]] = []

    def save(record: dict[str, Any]) -> dict[str, Any]:
        saved_records.append(record)
        return record

    first = persist_ready_generated_response(
        sample_record(),
        sample_refresh(),
        sample_workflow(),
        storage=storage,
        save_record=save,
    )
    second = persist_ready_generated_response(
        first,
        sample_refresh(),
        sample_workflow(),
        storage=storage,
        save_record=save,
    )

    lineage = first["generation"]["generated_response"]
    assert second["generation"]["generated_response"] == lineage
    assert len(storage.payloads) == 1
    assert len(saved_records) == 2
    assert "Grounded answer" not in str(second)
    assert "ae://chat-responses/" not in str(second)


def test_new_payload_is_compensated_when_record_save_fails() -> None:
    storage = InMemoryGeneratedResponseStorage()

    def fail_save(record: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        persist_ready_generated_response(
            sample_record(),
            sample_refresh(),
            sample_workflow(),
            storage=storage,
            save_record=fail_save,
        )

    assert storage.payloads == {}


def test_existing_payload_is_not_deleted_when_replay_record_save_fails() -> None:
    bundle = sample_bundle()
    record = attach_generated_response_lineage(
        sample_record(), bundle["lineage"]
    )
    storage = InMemoryGeneratedResponseStorage()
    storage.save(bundle["storage_payload"])

    with pytest.raises(RuntimeError):
        persist_ready_generated_response(
            record,
            sample_refresh(),
            sample_workflow(),
            storage=storage,
            save_record=lambda _: (_ for _ in ()).throw(RuntimeError("down")),
        )

    assert len(storage.payloads) == 1


class DeleteFailingStorage(InMemoryGeneratedResponseStorage):
    def delete(self, metadata: Mapping[str, Any]) -> bool:
        raise GeneratedResponseStorageError(
            error_code="ae.generated_response_storage_unavailable",
            detail="cleanup unavailable",
            retryable=True,
        )


def test_compensation_failure_does_not_hide_record_save_failure() -> None:
    storage = DeleteFailingStorage()

    with pytest.raises(RuntimeError, match="database unavailable"):
        persist_ready_generated_response(
            sample_record(),
            sample_refresh(),
            sample_workflow(),
            storage=storage,
            save_record=lambda _: (_ for _ in ()).throw(
                RuntimeError("database unavailable")
            ),
        )


class WrongReferenceStorage(InMemoryGeneratedResponseStorage):
    def save(self, payload: Mapping[str, Any]) -> str:
        super().save(payload)
        return "ae://chat-responses/wrong"


def test_handoff_rejects_inconsistent_storage_reference() -> None:
    with pytest.raises(GeneratedResponseStorageError) as error:
        persist_ready_generated_response(
            sample_record(),
            sample_refresh(),
            sample_workflow(),
            storage=WrongReferenceStorage(),
            save_record=lambda record: record,
        )

    assert error.value.error_code == "ae.generated_response_storage_invalid"
