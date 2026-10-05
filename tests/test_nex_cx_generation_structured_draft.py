from __future__ import annotations

from copy import deepcopy

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.drafts import build_structured_draft
from nex_cx.generation_structured_draft import (
    GENERATION_STRUCTURED_DRAFT_PRIVATE_SCHEMA_VERSION,
    load_generation_structured_draft,
    persist_generation_structured_draft,
    validate_generation_structured_draft_metadata,
)
from nex_cx.private_content import CxPrivateContentError
from nex_cx.private_text_store import FileSystemCxPrivateTextStore


GENERATION_ID = "cx-generation-s137"


def _context(*, subject_id: str = "owner-s137") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id="tenant-s137",
        subject_id=subject_id,
        request_id="request-s137",
        trace_id="13700000000000000000000000000001",
        scopes=("service:call",),
    )


def _draft(*, generation_id: str = GENERATION_ID) -> dict:
    return build_structured_draft(
        cx_generation_id=generation_id,
        trace_id="13700000000000000000000000000001",
        request_id="request-s137",
        output_text="Grounded durable answer [1].",
        compatibility_rule=None,
        retrieval_package=None,
    )


def test_structured_draft_round_trip_survives_store_restart(tmp_path) -> None:
    root = tmp_path / "private"
    draft = _draft()
    metadata = persist_generation_structured_draft(
        private_text_store=FileSystemCxPrivateTextStore(root),
        access_context=_context(),
        cx_generation_id=GENERATION_ID,
        structured_draft=draft,
    )

    reloaded = load_generation_structured_draft(
        private_text_store=FileSystemCxPrivateTextStore(root),
        access_context=_context(),
        cx_generation_id=GENERATION_ID,
        metadata=metadata,
        expected_structured_draft_id=draft["structured_draft_id"],
    )

    assert reloaded == draft
    assert metadata["structured_draft_private_schema_version"] == (
        GENERATION_STRUCTURED_DRAFT_PRIVATE_SCHEMA_VERSION
    )
    assert metadata["structured_draft_storage_uri"].startswith("cx-private://")
    assert "Grounded durable answer" not in str(metadata)


def test_structured_draft_is_hidden_from_another_owner(tmp_path) -> None:
    store = FileSystemCxPrivateTextStore(tmp_path / "private")
    metadata = persist_generation_structured_draft(
        private_text_store=store,
        access_context=_context(),
        cx_generation_id=GENERATION_ID,
        structured_draft=_draft(),
    )

    assert load_generation_structured_draft(
        private_text_store=store,
        access_context=_context(subject_id="other-owner"),
        cx_generation_id=GENERATION_ID,
        metadata=metadata,
        expected_structured_draft_id=_draft()["structured_draft_id"],
    ) is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(structured_draft_private_schema_version="v0"),
        lambda value: value.update(structured_draft_storage_backend=""),
        lambda value: value.update(structured_draft_storage_uri="/private/path"),
        lambda value: value.update(structured_draft_sha256="bad"),
        lambda value: value.update(structured_draft_size_bytes=True),
        lambda value: value.update(structured_draft_size_bytes=0),
    ],
)
def test_structured_draft_metadata_validation_fails_closed(mutate) -> None:
    metadata = {
        "structured_draft_private_schema_version": (
            GENERATION_STRUCTURED_DRAFT_PRIVATE_SCHEMA_VERSION
        ),
        "structured_draft_storage_backend": "local_fs",
        "structured_draft_storage_uri": "cx-private://opaque",
        "structured_draft_sha256": "a" * 64,
        "structured_draft_size_bytes": 100,
    }
    mutate(metadata)

    with pytest.raises(CxPrivateContentError):
        validate_generation_structured_draft_metadata(metadata)


def test_structured_draft_rejects_generation_and_draft_identity_drift(
    tmp_path,
) -> None:
    store = FileSystemCxPrivateTextStore(tmp_path / "private")
    with pytest.raises(CxPrivateContentError, match="generation identity"):
        persist_generation_structured_draft(
            private_text_store=store,
            access_context=_context(),
            cx_generation_id=GENERATION_ID,
            structured_draft=_draft(generation_id="different"),
        )

    draft = _draft()
    metadata = persist_generation_structured_draft(
        private_text_store=store,
        access_context=_context(),
        cx_generation_id=GENERATION_ID,
        structured_draft=draft,
    )
    with pytest.raises(CxPrivateContentError, match="identity"):
        load_generation_structured_draft(
            private_text_store=store,
            access_context=_context(),
            cx_generation_id=GENERATION_ID,
            metadata=metadata,
            expected_structured_draft_id="different",
        )

    invalid = deepcopy(draft)
    invalid["structured_draft_schema_version"] = "v0"
    with pytest.raises(CxPrivateContentError, match="schema version"):
        persist_generation_structured_draft(
            private_text_store=store,
            access_context=_context(),
            cx_generation_id=GENERATION_ID,
            structured_draft=invalid,
        )


@pytest.mark.parametrize(
    ("payload", "size_bytes", "error"),
    [
        ("{}", 3, "size"),
        ("{", 1, "valid JSON"),
        ("[]", 2, "must be an object"),
    ],
)
def test_structured_draft_payload_integrity_fails_closed(
    payload: str,
    size_bytes: int,
    error: str,
) -> None:
    class PayloadStore:
        @staticmethod
        def get_text(**_kwargs) -> str:
            return payload

    metadata = {
        "structured_draft_private_schema_version": (
            GENERATION_STRUCTURED_DRAFT_PRIVATE_SCHEMA_VERSION
        ),
        "structured_draft_storage_backend": "local_fs",
        "structured_draft_storage_uri": "cx-private://opaque",
        "structured_draft_sha256": "a" * 64,
        "structured_draft_size_bytes": size_bytes,
    }

    with pytest.raises(CxPrivateContentError, match=error):
        load_generation_structured_draft(
            private_text_store=PayloadStore(),
            access_context=_context(),
            cx_generation_id=GENERATION_ID,
            metadata=metadata,
            expected_structured_draft_id=None,
        )
