from __future__ import annotations

from typing import Any, Callable, Mapping

from nex_ae_api.generated_response_lineage import (
    attach_generated_response_lineage,
    generated_response_lineage_from_record,
    generated_response_storage_metadata_from_lineage,
    prepare_generated_response,
)
from nex_ae_api.generated_response_storage import (
    GeneratedResponseStorage,
    GeneratedResponseStorageError,
)


def persist_ready_generated_response(
    record: Mapping[str, Any],
    refresh_result: Mapping[str, Any],
    citation_workflow: Mapping[str, Any],
    *,
    storage: GeneratedResponseStorage,
    save_record: Callable[[dict[str, Any]], dict[str, Any]],
    cx_generation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    existing = generated_response_lineage_from_record(record)
    bundle = prepare_generated_response(
        record,
        refresh_result,
        citation_workflow,
        cx_generation=cx_generation,
    )
    lineage = bundle["lineage"]
    attached = attach_generated_response_lineage(record, lineage)
    metadata = generated_response_storage_metadata_from_lineage(lineage)
    saved_ref = storage.save(bundle["storage_payload"])
    if saved_ref != metadata["storage_ref"]:
        raise GeneratedResponseStorageError(
            error_code="ae.generated_response_storage_invalid",
            detail="AE generated response storage returned an inconsistent reference.",
        )
    try:
        return save_record(attached)
    except Exception:
        if existing is None:
            try:
                storage.delete(metadata)
            except GeneratedResponseStorageError:
                pass
        raise
