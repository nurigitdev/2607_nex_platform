from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from nex_runtime.object_storage import (
    ObjectStorageError,
    ObjectStorageSettings,
    S3ObjectStore,
)
from nex_cx.document_blob_store import (
    CxDocumentBlobError,
    DOCUMENT_BLOB_BACKEND,
    DOCUMENT_BLOB_URI_PREFIX,
    S3CxDocumentBlobStore,
    build_document_blob_store,
    source_object_key,
)
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    SOURCE_READER_S3_OBJECT,
    build_upload_registration,
    run_text_extraction_job,
)
from nex_cx.ingestion_hydration import hydrate_ingestion_runtime
from nex_cx.ingestion_orchestration import build_ingestion_run
from nex_cx.repository import InMemoryCxContentRepository


TRACE_ID = "14560000000000000000000000000001"
REQUEST_ID = "request-1456"


class ClientFailure(Exception):
    def __init__(self, status: int) -> None:
        self.response = {"ResponseMetadata": {"HTTPStatusCode": status}}


class FakeClient:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.failure: Exception | None = None

    def head_object(self, *, Key, **_kwargs):
        if self.failure:
            raise self.failure
        if Key not in self.objects:
            raise ClientFailure(404)
        return dict(self.objects[Key]["head"])

    def put_object(
        self,
        *,
        Key,
        Body,
        ContentType,
        Metadata,
        ServerSideEncryption,
        **_kwargs,
    ):
        self.objects[Key] = {
            "body": Body,
            "head": {
                "ContentLength": len(Body),
                "ContentType": ContentType,
                "Metadata": Metadata,
                "ServerSideEncryption": ServerSideEncryption,
                "VersionId": "version-1456",
            },
        }
        return {"VersionId": "version-1456"}

    def get_object(self, *, Key, **_kwargs):
        if self.failure:
            raise self.failure
        if Key not in self.objects:
            raise ClientFailure(404)
        return {"Body": io.BytesIO(self.objects[Key]["body"])}

    def delete_object(self, *, Key, **_kwargs):
        self.objects.pop(Key, None)
        return {"VersionId": "delete-1456"}

    def head_bucket(self, **_kwargs):
        return {}


def _blob_store() -> tuple[S3CxDocumentBlobStore, FakeClient]:
    settings = ObjectStorageSettings(
        owner="nex-cx",
        endpoint_url="https://object.example.test",
        bucket="nex-cx-private",
        access_key="access-key",
        secret_key="secret-key-value",
    )
    client = FakeClient()
    return S3CxDocumentBlobStore(S3ObjectStore(client, settings)), client


def _config(tmp_path: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=tmp_path,
        source_root=tmp_path / "source-files",
        extracted_markdown_root=tmp_path / "extracted-markdown",
        extraction_temp_root=tmp_path / "temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="korean_mixed_v1",
        bm25_tokenizer_fallback="korean_mixed_v1",
        private_storage_mode="S3",
    )


def _registration(config: CxStorageConfig, text: str = "private source text"):
    return build_upload_registration(
        {
            "filename": "private.md",
            "content_type": "text/markdown",
            "content_text": text,
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
        },
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )


def test_document_blob_round_trips_source_and_owner_scoped_markdown() -> None:
    store, _client = _blob_store()
    source = b"private source"
    source_sha = hashlib.sha256(source).hexdigest()
    key = source_object_key(source_sha, "source.PDF")

    source_receipt = store.put_source(
        storage_key=key,
        payload=source,
        expected_sha256=source_sha,
        content_type="application/pdf",
    )
    assert source_receipt.storage_backend == DOCUMENT_BLOB_BACKEND
    assert source_receipt.storage_uri == f"{DOCUMENT_BLOB_URI_PREFIX}{key}"
    assert store.get_source(
        storage_key=key,
        expected_sha256=source_sha,
        expected_size_bytes=len(source),
        max_size_bytes=1024,
    ) == source

    markdown = "# private\n\n한국어 본문"
    markdown_sha = hashlib.sha256(markdown.encode()).hexdigest()
    receipt = store.put_markdown(
        tenant_id="tenant-a",
        subject_id="user-a",
        document_id="document-a",
        markdown_text=markdown,
        expected_sha256=markdown_sha,
    )
    assert all(
        value not in receipt.storage_uri
        for value in ("tenant-a", "user-a", "document-a")
    )
    assert store.get_markdown(
        storage_uri=receipt.storage_uri,
        tenant_id="tenant-a",
        subject_id="user-a",
        document_id="document-a",
        expected_sha256=markdown_sha,
    ) == markdown
    with pytest.raises(CxDocumentBlobError) as denied:
        store.get_markdown(
            storage_uri=receipt.storage_uri,
            tenant_id="tenant-a",
            subject_id="user-b",
            document_id="document-a",
            expected_sha256=markdown_sha,
        )
    assert denied.value.status_code == 409


def test_document_blob_rejects_integrity_key_size_and_storage_failures(
    monkeypatch,
) -> None:
    store, client = _blob_store()
    source = b"private source"
    digest = hashlib.sha256(source).hexdigest()
    key = source_object_key(digest, "source.bin")

    with pytest.raises(CxDocumentBlobError) as mismatch:
        store.put_source(
            storage_key=key,
            payload=b"tampered",
            expected_sha256=digest,
            content_type="application/octet-stream",
        )
    assert mismatch.value.status_code == 409
    assert str(mismatch.value) == mismatch.value.detail
    with pytest.raises(CxDocumentBlobError):
        store.get_source(
            storage_key=f"v1/source/aa/bb/{digest}.bin",
            expected_sha256=digest,
            expected_size_bytes=len(source),
            max_size_bytes=1024,
        )
    with pytest.raises(CxDocumentBlobError):
        store.get_source(
            storage_key="unsafe",
            expected_sha256=digest,
            expected_size_bytes=len(source),
            max_size_bytes=1024,
        )
    assert store.get_source(
        storage_key=key,
        expected_sha256=digest,
        expected_size_bytes=len(source),
        max_size_bytes=1024,
    ) is None

    with pytest.raises(CxDocumentBlobError):
        store.put_markdown(
            tenant_id="tenant-a",
            subject_id="user-a",
            document_id="document-a",
            markdown_text=object(),  # type: ignore[arg-type]
            expected_sha256=digest,
        )
    with pytest.raises(CxDocumentBlobError) as markdown_mismatch:
        store.put_markdown(
            tenant_id="tenant-a",
            subject_id="user-a",
            document_id="document-a",
            markdown_text="wrong",
            expected_sha256=digest,
        )
    assert markdown_mismatch.value.status_code == 409
    with pytest.raises(CxDocumentBlobError):
        store.markdown_key(
            tenant_id="",
            subject_id="user-a",
            document_id="document-a",
        )

    monkeypatch.setattr(
        "nex_cx.document_blob_store.MAX_EXTRACTED_MARKDOWN_BYTES", 2
    )
    with pytest.raises(CxDocumentBlobError) as large:
        store.put_markdown(
            tenant_id="tenant-a",
            subject_id="user-a",
            document_id="document-a",
            markdown_text="long",
            expected_sha256=hashlib.sha256(b"long").hexdigest(),
        )
    assert large.value.status_code == 413
    monkeypatch.setattr(
        "nex_cx.document_blob_store.MAX_EXTRACTED_MARKDOWN_BYTES",
        64 * 1024 * 1024,
    )

    def fail_put(**_kwargs):
        raise ObjectStorageError(
            "OBJECT_STORAGE_IMMUTABLE_CONFLICT", "conflict"
        )

    monkeypatch.setattr(store.object_store, "put_immutable", fail_put)
    with pytest.raises(CxDocumentBlobError) as conflict:
        store.put_markdown(
            tenant_id="tenant-a",
            subject_id="user-a",
            document_id="document-a",
            markdown_text="private",
            expected_sha256=hashlib.sha256(b"private").hexdigest(),
        )
    assert conflict.value.error_code == "cx.document_blob.integrity_failed"

    client.failure = ClientFailure(503)
    with pytest.raises(CxDocumentBlobError) as unavailable:
        store.get_source(
            storage_key=key,
            expected_sha256=digest,
            expected_size_bytes=len(source),
            max_size_bytes=1024,
        )
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True


def test_markdown_read_rejects_missing_invalid_encoding_and_storage_errors(
    monkeypatch,
) -> None:
    store, client = _blob_store()
    markdown = "private"
    digest = hashlib.sha256(markdown.encode()).hexdigest()
    uri = (
        f"{DOCUMENT_BLOB_URI_PREFIX}"
        f"{store.markdown_key(tenant_id='tenant-a', subject_id='user-a', document_id='doc-a')}"
    )
    assert store.get_markdown(
        storage_uri=uri,
        tenant_id="tenant-a",
        subject_id="user-a",
        document_id="doc-a",
        expected_sha256=digest,
    ) is None

    receipt = store.put_markdown(
        tenant_id="tenant-a",
        subject_id="user-a",
        document_id="doc-a",
        markdown_text=markdown,
        expected_sha256=digest,
    )
    monkeypatch.setattr(store.object_store, "get_bytes", lambda **_kwargs: None)
    assert store.get_markdown(
        storage_uri=receipt.storage_uri,
        tenant_id="tenant-a",
        subject_id="user-a",
        document_id="doc-a",
        expected_sha256=digest,
    ) is None

    monkeypatch.undo()
    key = receipt.storage_key
    client.objects[key]["body"] = b"\xff"
    client.objects[key]["head"]["ContentLength"] = 1
    invalid_digest = hashlib.sha256(b"\xff").hexdigest()
    client.objects[key]["head"]["Metadata"] = {"sha256": invalid_digest}
    with pytest.raises(CxDocumentBlobError) as encoding:
        store.get_markdown(
            storage_uri=receipt.storage_uri,
            tenant_id="tenant-a",
            subject_id="user-a",
            document_id="doc-a",
            expected_sha256=invalid_digest,
        )
    assert encoding.value.status_code == 409

    def fail_get(**_kwargs):
        raise ObjectStorageError("OBJECT_STORAGE_GET_FAILED", "failed")

    monkeypatch.setattr(store.object_store, "get_bytes", fail_get)
    with pytest.raises(CxDocumentBlobError) as failed:
        store.get_markdown(
            storage_uri=receipt.storage_uri,
            tenant_id="tenant-a",
            subject_id="user-a",
            document_id="doc-a",
            expected_sha256=invalid_digest,
        )
    assert failed.value.status_code == 500


def test_s3_ingestion_persists_and_restart_hydrates_private_objects(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    blob_store, client = _blob_store()
    repository = InMemoryCxContentRepository()
    store = ContentIngestionStore(
        content_repository=repository,
        document_blob_store=blob_store,
    )
    registration = _registration(config)
    assert registration["storage"]["source_storage_backend"] == DOCUMENT_BLOB_BACKEND
    assert "source_storage_path" not in registration["storage"]
    assert "private.md" not in registration["storage"]["source_storage_key"]

    saved = store.save_upload_registration(
        registration,
        source_text="private source text",
    )
    source_file = repository.get_source_file(
        store.get_content_ref(saved["document_id"])["source_file_id"]
    )
    assert source_file["storage_uri"].startswith(DOCUMENT_BLOB_URI_PREFIX)
    assert source_file["checksum_verified_at"] is not None

    store.source_bytes.clear()
    store.source_texts.clear()
    extraction = run_text_extraction_job(
        saved["ingestion_job"]["job_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    assert extraction["source_reader"]["source"] == SOURCE_READER_S3_OBJECT
    assert extraction["extracted_markdown_storage_uri"].startswith(
        DOCUMENT_BLOB_URI_PREFIX
    )
    artifact = repository.find_latest_extraction_artifact(
        content_object_id=saved["document_id"]
    )
    assert artifact["markdown_storage_uri"] == extraction[
        "extracted_markdown_storage_uri"
    ]

    Path(extraction["extracted_markdown_path"]).unlink()
    run = build_ingestion_run(
        document_id=saved["document_id"],
        job_id=saved["ingestion_job"]["job_id"],
        idempotency_key=saved["upload_id"],
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "user-a"},
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        created_at=saved["created_at"],
    )
    restarted = ContentIngestionStore(
        content_repository=repository,
        document_blob_store=blob_store,
    )
    evidence = hydrate_ingestion_runtime(
        run,
        store=restarted,
        storage_config=config,
    )
    hydrated = restarted.get_extraction_result(saved["document_id"])
    assert evidence["extraction_hydrated"] is True
    assert (
        Path(hydrated["extracted_markdown_path"]).read_text()
        == "private source text\n"
    )
    assert len(client.objects) == 2


def test_builder_selects_s3_and_rejects_unsafe_modes(monkeypatch) -> None:
    fake_store, _client = _blob_store()
    monkeypatch.setattr(
        "nex_cx.document_blob_store.build_s3_client",
        lambda _settings: fake_store.object_store.client,
    )
    env = {
        "NEX_CX_PRIVATE_STORAGE_MODE": "S3",
        "NEX_CX_OBJECT_STORAGE_BACKEND": "S3",
        "NEX_CX_OBJECT_STORAGE_ENDPOINT": "https://object.example.test",
        "NEX_CX_OBJECT_STORAGE_ACCESS_KEY": "cx-access-key",
        "NEX_CX_OBJECT_STORAGE_SECRET_KEY": "cx-secret-key-long",
    }
    assert isinstance(build_document_blob_store(env), S3CxDocumentBlobStore)
    assert build_document_blob_store({"NEX_CX_PRIVATE_STORAGE_MODE": "FILESYSTEM"}) is None
    with pytest.raises(CxDocumentBlobError):
        build_document_blob_store({"NEX_CX_PRIVATE_STORAGE_MODE": "bad"})
    with pytest.raises(CxDocumentBlobError) as missing:
        build_document_blob_store({"NEX_CX_PRIVATE_STORAGE_MODE": "S3"})
    assert missing.value.error_code == "cx.document_blob.configuration_invalid"
    with pytest.raises(CxDocumentBlobError):
        source_object_key("invalid", "source.txt")
    assert source_object_key("a" * 64, "source.bad.ext") == (
        f"v1/source/aa/aa/{'a' * 64}.ext"
    )
    with pytest.raises(CxDocumentBlobError):
        build_document_blob_store(
            {**env, "NEX_CX_OBJECT_STORAGE_ALLOW_INSECURE": "maybe"}
        )
    with pytest.raises(CxDocumentBlobError) as forbidden:
        build_document_blob_store(
            {
                **env,
                "NEX_CX_OBJECT_STORAGE_ENDPOINT": "http://rustfs:9000",
                "NEX_CX_OBJECT_STORAGE_ALLOW_INSECURE": "true",
                "NEX_RUNTIME_PROFILE": "production",
            }
        )
    assert forbidden.value.error_code == "cx.document_blob.insecure_endpoint_forbidden"
    assert isinstance(
        build_document_blob_store(
            {
                **env,
                "NEX_CX_OBJECT_STORAGE_ENDPOINT": "http://rustfs:9000",
                "NEX_CX_OBJECT_STORAGE_ALLOW_INSECURE": "true",
                "NEX_RUNTIME_PROFILE": "protected_test",
            }
        ),
        S3CxDocumentBlobStore,
    )
