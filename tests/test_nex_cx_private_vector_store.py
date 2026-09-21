from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import sys

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.embedding_index import sha256_json
from nex_cx.private_content import (
    CxPrivateContentError,
    CxPrivatePayloadReceipt,
    CxVectorStore,
    build_private_payload_key,
    serialize_private_vector,
    sha256_private_vector,
)
from nex_cx.private_vector_store import (
    DEFAULT_PRIVATE_VECTOR_STORAGE_ROOT,
    PRIVATE_VECTOR_STORAGE_BACKEND,
    FileSystemCxVectorStore,
    build_private_vector_store,
    link_private_vector_metadata,
    persist_and_link_private_vector,
)
import run_cx_private_vector_store_smoke as smoke


def _context(
    *, tenant_id: str = "tenant-a", subject_id: str = "employee-1004"
) -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id=tenant_id,
        subject_id=subject_id,
        request_id="request-0916",
        trace_id="91600000000000000000000000000001",
        scopes=("service:call",),
    )


def _key(
    context: CxAccessContext | None = None,
    *,
    payload_kind: str = "chunk_embedding",
    content_id: str = "chunk-0916",
):
    return build_private_payload_key(
        context or _context(),
        payload_kind=payload_kind,
        content_id=content_id,
    )


@pytest.mark.parametrize(
    ("payload_kind", "content_id"),
    [
        ("chunk_embedding", "chunk-0916"),
        ("summary_embedding", "summary-0916"),
    ],
)
def test_filesystem_vector_store_round_trip_restart_and_delete(
    tmp_path: Path,
    payload_kind: str,
    content_id: str,
) -> None:
    context = _context()
    key = _key(context, payload_kind=payload_kind, content_id=content_id)
    vector = (0.125, -0.25, 0.5)
    checksum = sha256_private_vector(vector)
    store = FileSystemCxVectorStore(tmp_path / "private-vectors")

    receipt = store.put_vector(
        access_context=context,
        key=key,
        vector=vector,
        expected_sha256=checksum,
    )

    assert isinstance(store, CxVectorStore)
    assert receipt.storage_backend == PRIVATE_VECTOR_STORAGE_BACKEND
    assert receipt.sha256 == checksum
    assert receipt.vector_dimension == 3
    assert receipt.size_bytes == len(serialize_private_vector(vector))
    assert all(
        value not in receipt.storage_uri
        for value in (context.tenant_id, context.subject_id, content_id)
    )
    restarted = FileSystemCxVectorStore(tmp_path / "private-vectors")
    assert restarted.get_vector(
        access_context=context,
        key=key,
        expected_sha256=checksum,
        expected_dimension=3,
    ) == vector
    assert restarted.delete_vector(access_context=context, key=key) is True
    assert restarted.get_vector(
        access_context=context,
        key=key,
        expected_sha256=checksum,
        expected_dimension=3,
    ) is None
    assert restarted.delete_vector(access_context=context, key=key) is False


def test_private_vector_hash_matches_existing_embedding_metadata_contract() -> None:
    vector = [0.0, 0.5, 1.0]

    assert sha256_private_vector(vector) == sha256_json({"embedding": vector})
    assert json.loads(serialize_private_vector(vector)) == {"embedding": vector}


def test_filesystem_vector_store_is_idempotent_and_immutable(tmp_path: Path) -> None:
    context = _context()
    key = _key(context)
    vector = (1.0, 2.0)
    checksum = sha256_private_vector(vector)
    store = FileSystemCxVectorStore(tmp_path)

    first = store.put_vector(
        access_context=context,
        key=key,
        vector=vector,
        expected_sha256=checksum,
    )
    second = store.put_vector(
        access_context=context,
        key=key,
        vector=vector,
        expected_sha256=checksum,
    )
    with pytest.raises(CxPrivateContentError) as caught:
        store.put_vector(
            access_context=context,
            key=key,
            vector=(3.0, 4.0),
            expected_sha256=sha256_private_vector((3.0, 4.0)),
        )

    assert second == first
    assert caught.value.error_code == "CX_PRIVATE_VECTOR_IMMUTABLE_CONFLICT"


@pytest.mark.parametrize("operation", ["put", "get", "delete"])
def test_filesystem_vector_store_hides_cross_owner_access(
    tmp_path: Path,
    operation: str,
) -> None:
    key = _key()
    vector = (1.0,)
    checksum = sha256_private_vector(vector)
    store = FileSystemCxVectorStore(tmp_path)
    other_context = _context(subject_id="employee-other")

    with pytest.raises(CxPrivateContentError) as caught:
        if operation == "put":
            store.put_vector(
                access_context=other_context,
                key=key,
                vector=vector,
                expected_sha256=checksum,
            )
        elif operation == "get":
            store.get_vector(
                access_context=other_context,
                key=key,
                expected_sha256=checksum,
                expected_dimension=1,
            )
        else:
            store.delete_vector(access_context=other_context, key=key)

    assert caught.value.status_code == 404
    assert caught.value.error_code == "CX_PRIVATE_PAYLOAD_NOT_FOUND"


@pytest.mark.parametrize("operation", ["put", "get", "delete", "uri"])
def test_filesystem_vector_store_rejects_text_key(
    tmp_path: Path,
    operation: str,
) -> None:
    store = FileSystemCxVectorStore(tmp_path)
    key = _key(payload_kind="chunk_text")
    with pytest.raises(CxPrivateContentError) as caught:
        if operation == "put":
            store.put_vector(
                access_context=_context(),
                key=key,
                vector=(1.0,),
                expected_sha256=sha256_private_vector((1.0,)),
            )
        elif operation == "get":
            store.get_vector(
                access_context=_context(),
                key=key,
                expected_sha256=sha256_private_vector((1.0,)),
                expected_dimension=1,
            )
        elif operation == "delete":
            store.delete_vector(access_context=_context(), key=key)
        else:
            store.storage_uri(key)

    assert caught.value.error_code == "CX_PRIVATE_VECTOR_KIND_INVALID"


@pytest.mark.parametrize("dimension", [None, True, 0, -1, "3"])
def test_filesystem_vector_store_rejects_invalid_expected_dimension(
    tmp_path: Path,
    dimension: object,
) -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        FileSystemCxVectorStore(tmp_path).get_vector(
            access_context=_context(),
            key=_key(),
            expected_sha256="0" * 64,
            expected_dimension=dimension,  # type: ignore[arg-type]
        )

    assert caught.value.error_code == "CX_PRIVATE_VECTOR_DIMENSION_INVALID"


def test_filesystem_vector_store_detects_hash_and_dimension_mismatch(
    tmp_path: Path,
) -> None:
    store = FileSystemCxVectorStore(tmp_path)
    vector = (1.0, 2.0)
    checksum = sha256_private_vector(vector)
    store.put_vector(
        access_context=_context(),
        key=_key(),
        vector=vector,
        expected_sha256=checksum,
    )

    with pytest.raises(CxPrivateContentError) as hash_error:
        store.get_vector(
            access_context=_context(),
            key=_key(),
            expected_sha256="0" * 64,
            expected_dimension=2,
        )
    with pytest.raises(CxPrivateContentError) as dimension_error:
        store.get_vector(
            access_context=_context(),
            key=_key(),
            expected_sha256=checksum,
            expected_dimension=3,
        )

    assert hash_error.value.error_code == "CX_PRIVATE_PAYLOAD_HASH_MISMATCH"
    assert dimension_error.value.error_code == "CX_PRIVATE_VECTOR_DIMENSION_MISMATCH"


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff",
        b"not-json",
        b"[]",
        b'{"embedding":[1.0],"private":"leak"}',
        b'{"embedding":"invalid"}',
    ],
)
def test_filesystem_vector_store_rejects_invalid_payload(
    tmp_path: Path,
    payload: bytes,
) -> None:
    store = FileSystemCxVectorStore(tmp_path)
    path = store._payload_path(_key())
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)

    with pytest.raises(CxPrivateContentError) as caught:
        store.get_vector(
            access_context=_context(),
            key=_key(),
            expected_sha256="0" * 64,
            expected_dimension=1,
        )

    assert caught.value.error_code in {
        "CX_PRIVATE_VECTOR_ENCODING_INVALID",
        "CX_PRIVATE_VECTOR_INVALID",
    }


def test_private_vector_store_builder_uses_default_and_override(tmp_path: Path) -> None:
    assert build_private_vector_store({}).root == DEFAULT_PRIVATE_VECTOR_STORAGE_ROOT
    assert build_private_vector_store(
        {"NEX_CX_PRIVATE_VECTOR_STORAGE_ROOT": str(tmp_path)}
    ).root == tmp_path.resolve()
    with pytest.raises(CxPrivateContentError) as caught:
        FileSystemCxVectorStore(" ")

    assert caught.value.error_code == "CX_PRIVATE_VECTOR_ROOT_INVALID"


def test_link_private_vector_metadata_for_chunk_and_summary(tmp_path: Path) -> None:
    store = FileSystemCxVectorStore(tmp_path)
    context = _context()
    vector = (0.25, 0.5)
    checksum = sha256_private_vector(vector)
    chunk_receipt = store.put_vector(
        access_context=context,
        key=_key(context),
        vector=vector,
        expected_sha256=checksum,
    )
    summary_key = _key(
        context,
        payload_kind="summary_embedding",
        content_id="summary-0916",
    )
    summary_receipt = store.put_vector(
        access_context=context,
        key=summary_key,
        vector=vector,
        expected_sha256=checksum,
    )

    chunk = link_private_vector_metadata({"ordinal": 0}, chunk_receipt)
    summary = link_private_vector_metadata({}, summary_receipt)

    assert chunk == {
        "ordinal": 0,
        "chunk_id": "chunk-0916",
        "embedding_sha256": checksum,
        "vector_dimension": 2,
        "embedding_storage_uri": chunk_receipt.storage_uri,
    }
    assert summary["document_summary_id"] == "summary-0916"
    assert "embedding" not in chunk and "vector" not in chunk
    assert "embedding" not in summary and "vector" not in summary


@pytest.mark.parametrize(
    "metadata",
    [
        {"chunk_id": "other"},
        {"embedding_sha256": "0" * 64},
        {"vector_dimension": 99},
        {"embedding_storage_uri": "cx-private://other/value"},
    ],
)
def test_link_private_vector_metadata_rejects_conflicts(
    tmp_path: Path,
    metadata: dict[str, object],
) -> None:
    vector = (1.0,)
    receipt = FileSystemCxVectorStore(tmp_path).put_vector(
        access_context=_context(),
        key=_key(),
        vector=vector,
        expected_sha256=sha256_private_vector(vector),
    )

    with pytest.raises(CxPrivateContentError) as caught:
        link_private_vector_metadata(metadata, receipt)

    assert caught.value.error_code == "CX_PRIVATE_VECTOR_METADATA_CONFLICT"


def test_link_private_vector_metadata_rejects_invalid_receipt() -> None:
    receipt = CxPrivatePayloadReceipt(
        key=_key(),
        storage_backend=PRIVATE_VECTOR_STORAGE_BACKEND,
        storage_uri="cx-private://filesystem-vector-v1/value",
        sha256="0" * 64,
        size_bytes=1,
        vector_dimension=None,
    )

    with pytest.raises(CxPrivateContentError) as caught:
        link_private_vector_metadata({}, receipt)

    assert caught.value.error_code == "CX_PRIVATE_VECTOR_RECEIPT_INVALID"


def test_persist_and_link_private_vector_requires_metadata_hash(tmp_path: Path) -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        persist_and_link_private_vector(
            access_context=_context(),
            vector_store=FileSystemCxVectorStore(tmp_path),
            payload_kind="chunk_embedding",
            content_id="chunk-0916",
            vector=(1.0,),
            metadata={},
        )

    assert caught.value.error_code == "CX_PRIVATE_VECTOR_METADATA_INVALID"


def test_persist_and_link_private_vector_round_trip(tmp_path: Path) -> None:
    vector = (1.0, 2.0, 3.0)
    checksum = sha256_private_vector(vector)
    linked = persist_and_link_private_vector(
        access_context=_context(),
        vector_store=FileSystemCxVectorStore(tmp_path),
        payload_kind="summary_embedding",
        content_id="summary-0916",
        vector=vector,
        metadata={
            "document_summary_id": "summary-0916",
            "embedding_sha256": checksum,
            "vector_dimension": 3,
        },
    )

    assert linked["embedding_sha256"] == checksum
    assert linked["embedding_storage_uri"].startswith(
        "cx-private://filesystem-vector-v1/"
    )


def test_private_vector_store_smoke_evidence(tmp_path: Path) -> None:
    result = smoke.run_private_vector_store_smoke(tmp_path / "smoke")

    assert result["status"] == "PASS"
    assert result["checks"] == 10
    assert result["restart_reload"] is True
    assert result["metadata_linked"] is True
    assert result["dgx_required"] is False


def test_private_vector_store_smoke_cli_modes(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_cx_private_vector_store_smoke.py",
            "--summary",
            "--storage-root",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit) as summary_exit:
        runpy.run_module("run_cx_private_vector_store_smoke", run_name="__main__")

    assert summary_exit.value.code == 0
    assert "cx_private_vector_store=pass" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["run_cx_private_vector_store_smoke.py"])
    with pytest.raises(SystemExit) as json_exit:
        runpy.run_module("run_cx_private_vector_store_smoke", run_name="__main__")

    assert json_exit.value.code == 0
    assert json.loads(capsys.readouterr().out)["checks"] == 10


def test_private_vector_store_smoke_main_returns_failure(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_private_vector_store_smoke",
        lambda root: {
            "status": "FAIL",
            "checks": 9,
            "checks_total": 10,
            "restart_reload": False,
            "metadata_linked": True,
            "dgx_required": False,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_cx_private_vector_store_smoke.py", "--summary", "--storage-root", str(tmp_path)],
    )

    assert smoke.main() == 1
    assert "cx_private_vector_store=fail" in capsys.readouterr().out
