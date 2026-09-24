from __future__ import annotations

from copy import deepcopy
import json

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.generation_request_store import (
    GENERATION_REQUEST_STORAGE_ROOT_ENV,
    build_generation_request_envelope,
    build_generation_request_store,
    load_generation_request_envelope,
    persist_generation_request_envelope,
    validate_generation_request_envelope,
    validate_generation_request_receipt,
)
from nex_cx.private_content import CxPrivateContentError
from nex_cx.private_text_store import FileSystemCxPrivateTextStore


def _context(subject_id: str = "user-1") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id="tenant-1",
        subject_id=subject_id,
        request_id="request-1",
        trace_id="trace-1",
        scopes=("service:call",),
    )


def _envelope(context: CxAccessContext | None = None) -> dict[str, object]:
    access = context or _context()
    return build_generation_request_envelope(
        access_context=access,
        cx_generation_id="generation-1",
        admission_id="admission-1",
        source_payload={"prompt": "private question", "selected_evidence_ids": ["e1"]},
        mo_payload={"cx_generation_id": "generation-1", "input": "private prompt"},
        compatibility_rule={"grounding_required": True},
        retrieval_package={"retrieval_package_id": "rp-1", "evidence": ["private"]},
        request_id="request-1",
        trace_id="trace-1",
    )


def test_persists_and_reloads_owner_private_envelope_after_restart(tmp_path) -> None:
    context = _context()
    store = FileSystemCxPrivateTextStore(tmp_path / "requests")
    receipt = persist_generation_request_envelope(
        private_text_store=store,
        access_context=context,
        envelope=_envelope(context),
    )

    reloaded = load_generation_request_envelope(
        private_text_store=FileSystemCxPrivateTextStore(tmp_path / "requests"),
        access_context=context,
        cx_generation_id="generation-1",
        receipt=receipt,
    )

    assert reloaded == _envelope(context)
    assert receipt["request_storage_uri"].startswith("cx-private://")
    assert receipt["request_envelope_size_bytes"] > 0


def test_missing_envelope_returns_none(tmp_path) -> None:
    receipt = {
        "request_receipt_schema_version": "cx_generation_request_receipt.v1",
        "request_storage_backend": "filesystem-text-v1",
        "request_storage_uri": "cx-private://missing",
        "request_envelope_sha256": "a" * 64,
        "request_envelope_size_bytes": 10,
    }
    assert load_generation_request_envelope(
        private_text_store=FileSystemCxPrivateTextStore(tmp_path),
        access_context=_context(),
        cx_generation_id="generation-1",
        receipt=receipt,
    ) is None


def test_owner_and_generation_binding_fail_closed() -> None:
    envelope = _envelope()
    with pytest.raises(CxPrivateContentError) as owner_error:
        validate_generation_request_envelope(
            envelope,
            access_context=_context("other"),
            cx_generation_id="generation-1",
        )
    assert owner_error.value.status_code == 404

    with pytest.raises(CxPrivateContentError) as generation_error:
        validate_generation_request_envelope(
            envelope,
            access_context=_context(),
            cx_generation_id="other",
        )
    assert generation_error.value.status_code == 404


def test_rejects_credentials_and_mismatched_mo_identity() -> None:
    credential = _envelope()
    credential["source_payload"]["api_key"] = "secret"
    with pytest.raises(CxPrivateContentError, match="credential"):
        validate_generation_request_envelope(
            credential,
            access_context=_context(),
            cx_generation_id="generation-1",
        )

    mismatch = _envelope()
    mismatch["mo_payload"]["cx_generation_id"] = "other"
    with pytest.raises(CxPrivateContentError, match="MO payload"):
        validate_generation_request_envelope(
            mismatch,
            access_context=_context(),
            cx_generation_id="generation-1",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(request_receipt_schema_version="v0"),
        lambda value: value.update(request_storage_backend=" "),
        lambda value: value.update(request_storage_uri="file:///tmp/private"),
        lambda value: value.update(request_envelope_sha256="bad"),
        lambda value: value.update(request_envelope_size_bytes=0),
    ],
)
def test_rejects_invalid_receipts(mutation) -> None:
    receipt = {
        "request_receipt_schema_version": "cx_generation_request_receipt.v1",
        "request_storage_backend": "filesystem-text-v1",
        "request_storage_uri": "cx-private://request",
        "request_envelope_sha256": "a" * 64,
        "request_envelope_size_bytes": 10,
    }
    mutation(receipt)
    with pytest.raises(CxPrivateContentError):
        validate_generation_request_receipt(receipt)


def test_load_rejects_size_and_json_corruption(tmp_path) -> None:
    context = _context()
    store = FileSystemCxPrivateTextStore(tmp_path / "requests")
    receipt = persist_generation_request_envelope(
        private_text_store=store,
        access_context=context,
        envelope=_envelope(),
    )
    wrong_size = {**receipt, "request_envelope_size_bytes": 1}
    with pytest.raises(CxPrivateContentError, match="size"):
        load_generation_request_envelope(
            private_text_store=store,
            access_context=context,
            cx_generation_id="generation-1",
            receipt=wrong_size,
        )

    class InvalidJsonStore:
        def get_text(self, **kwargs):
            return "not-json"

    invalid_json_receipt = {
        **receipt,
        "request_envelope_sha256": "a" * 64,
        "request_envelope_size_bytes": len("not-json"),
    }
    with pytest.raises(CxPrivateContentError, match="valid JSON"):
        load_generation_request_envelope(
            private_text_store=InvalidJsonStore(),  # type: ignore[arg-type]
            access_context=context,
            cx_generation_id="generation-1",
            receipt=invalid_json_receipt,
        )


def test_builds_configured_store(tmp_path) -> None:
    store = build_generation_request_store(
        {GENERATION_REQUEST_STORAGE_ROOT_ENV: str(tmp_path / "configured")}
    )
    assert store.root == (tmp_path / "configured").resolve()


def test_rejects_invalid_envelope_shapes() -> None:
    with pytest.raises(CxPrivateContentError, match="must be an object"):
        validate_generation_request_envelope(
            [], access_context=_context(), cx_generation_id="generation-1"
        )
    invalid = _envelope()
    invalid["envelope_schema_version"] = "v0"
    with pytest.raises(CxPrivateContentError, match="schema version"):
        validate_generation_request_envelope(
            invalid, access_context=_context(), cx_generation_id="generation-1"
        )
    invalid = _envelope()
    invalid["source_payload"] = []
    with pytest.raises(CxPrivateContentError, match="source_payload"):
        validate_generation_request_envelope(
            invalid, access_context=_context(), cx_generation_id="generation-1"
        )
    no_retrieval = _envelope()
    no_retrieval["retrieval_package"] = None
    assert validate_generation_request_envelope(
        no_retrieval, access_context=_context(), cx_generation_id="generation-1"
    )["retrieval_package"] is None


def test_canonical_persistence_is_idempotent(tmp_path) -> None:
    store = FileSystemCxPrivateTextStore(tmp_path)
    first = persist_generation_request_envelope(
        private_text_store=store,
        access_context=_context(),
        envelope=_envelope(),
    )
    second = persist_generation_request_envelope(
        private_text_store=store,
        access_context=_context(),
        envelope=json.loads(json.dumps(_envelope())),
    )
    assert first == second
