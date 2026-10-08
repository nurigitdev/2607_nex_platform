from __future__ import annotations

import hashlib
import io

import pytest

from nex_runtime.object_storage import ObjectStorageError, S3ObjectStore
from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import CxPrivateContentError, build_private_payload_key
from nex_cx.private_text_store import (
    PRIVATE_STORAGE_MODE_ENV,
    S3_PRIVATE_TEXT_STORAGE_BACKEND,
    S3CxPrivateTextStore,
    build_private_text_store,
)


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

    def put_object(self, *, Key, Body, ContentType, Metadata, ServerSideEncryption, **_kwargs):
        self.objects[Key] = {
            "body": Body,
            "head": {
                "ContentLength": len(Body),
                "ContentType": ContentType,
                "Metadata": Metadata,
                "ServerSideEncryption": ServerSideEncryption,
                "VersionId": "version-1",
            },
        }
        return {"VersionId": "version-1"}

    def get_object(self, *, Key, **_kwargs):
        if self.failure:
            raise self.failure
        return {"Body": io.BytesIO(self.objects[Key]["body"])}

    def delete_object(self, *, Key, **_kwargs):
        self.objects.pop(Key, None)
        return {"VersionId": "delete-1"}

    def head_bucket(self, **_kwargs):
        return {}


def _context(subject: str = "employee-1004") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-a",
        subject_id=subject,
        request_id="request-1455",
        trace_id="14550000000000000000000000000001",
        scopes=("service:call",),
    )


def _key(kind: str = "chunk_text"):
    return build_private_payload_key(
        _context(), payload_kind=kind, content_id="content-1455"
    )


def _store() -> tuple[S3CxPrivateTextStore, FakeClient]:
    from nex_runtime.object_storage import ObjectStorageSettings

    settings = ObjectStorageSettings(
        owner="nex-cx",
        endpoint_url="https://object.example.test",
        bucket="nex-cx-private",
        access_key="access-key",
        secret_key="secret-key-value",
    )
    client = FakeClient()
    return S3CxPrivateTextStore(S3ObjectStore(client, settings)), client


@pytest.mark.parametrize(
    ("kind", "family"),
    [
        ("chunk_text", "text"),
        ("summary_text", "text"),
        ("generation_request", "generation-request"),
        ("generation_output", "generation-output"),
        ("structured_draft", "generation-output"),
    ],
)
def test_s3_text_round_trip_is_owner_scoped_opaque_and_deletable(kind: str, family: str) -> None:
    store, _client = _store()
    key = _key(kind)
    text = "private 한국어 text"
    digest = hashlib.sha256(text.encode()).hexdigest()
    receipt = store.put_text(
        access_context=_context(), key=key, text=text, expected_sha256=digest
    )
    assert receipt.storage_backend == S3_PRIVATE_TEXT_STORAGE_BACKEND
    assert f"/v1/{family}/" in receipt.storage_uri
    assert all(value not in receipt.storage_uri for value in ("tenant-a", "employee-1004", "content-1455"))
    assert store.get_text(
        access_context=_context(), key=key, expected_sha256=digest
    ) == text
    assert store.delete_text(access_context=_context(), key=key) is True
    assert store.delete_text(access_context=_context(), key=key) is False


def test_s3_text_rejects_cross_owner_oversize_invalid_kind_and_utf8(monkeypatch) -> None:
    store, client = _store()
    key = _key()
    digest = hashlib.sha256(b"private").hexdigest()
    with pytest.raises(CxPrivateContentError) as exc_info:
        store.get_text(access_context=_context("other"), key=key, expected_sha256=digest)
    assert exc_info.value.status_code == 404

    monkeypatch.setattr("nex_cx.private_text_store.MAX_PRIVATE_TEXT_BYTES", 2)
    with pytest.raises(CxPrivateContentError) as exc_info:
        store.put_text(access_context=_context(), key=key, text="long", expected_sha256=hashlib.sha256(b"long").hexdigest())
    assert exc_info.value.status_code == 413

    invalid_key = type(key)(key.tenant_id, key.subject_id, "not-text", key.content_id)
    with pytest.raises(CxPrivateContentError) as exc_info:
        store.object_key(invalid_key)
    assert exc_info.value.error_code == "CX_PRIVATE_TEXT_KIND_INVALID"

    monkeypatch.setattr("nex_cx.private_text_store.MAX_PRIVATE_TEXT_BYTES", 32 * 1024 * 1024)
    store.put_text(access_context=_context(), key=key, text="private", expected_sha256=digest)
    client.objects[store.object_key(key)]["body"] = b"\xff"
    client.objects[store.object_key(key)]["head"]["ContentLength"] = 1
    client.objects[store.object_key(key)]["head"]["Metadata"] = {"sha256": hashlib.sha256(b"\xff").hexdigest()}
    with pytest.raises(CxPrivateContentError) as exc_info:
        store.get_text(access_context=_context(), key=key, expected_sha256=hashlib.sha256(b"\xff").hexdigest())
    assert exc_info.value.error_code == "CX_PRIVATE_TEXT_ENCODING_INVALID"


def test_s3_text_maps_retryable_and_integrity_failures() -> None:
    store, client = _store()
    key = _key()
    digest = hashlib.sha256(b"private").hexdigest()
    client.failure = ClientFailure(503)
    with pytest.raises(CxPrivateContentError) as exc_info:
        store.get_text(access_context=_context(), key=key, expected_sha256=digest)
    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is True

    client.failure = None
    store.put_text(access_context=_context(), key=key, text="private", expected_sha256=digest)
    client.objects[store.object_key(key)]["head"]["ServerSideEncryption"] = None
    with pytest.raises(CxPrivateContentError) as exc_info:
        store.put_text(access_context=_context(), key=key, text="private", expected_sha256=digest)
    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "CX_PRIVATE_TEXT_INTEGRITY_FAILED"


def test_builder_selects_s3_and_rejects_unsafe_configuration(monkeypatch) -> None:
    fake_store, _client = _store()
    monkeypatch.setattr("nex_cx.private_text_store.build_s3_client", lambda _settings: fake_store.object_store.client)
    env = {
        PRIVATE_STORAGE_MODE_ENV: "s3",
        "NEX_CX_OBJECT_STORAGE_BACKEND": "S3",
        "NEX_CX_OBJECT_STORAGE_ENDPOINT": "https://object.example.test",
        "NEX_CX_OBJECT_STORAGE_ACCESS_KEY": "cx-access-key",
        "NEX_CX_OBJECT_STORAGE_SECRET_KEY": "cx-secret-key-long",
    }
    assert isinstance(build_private_text_store(env), S3CxPrivateTextStore)
    with pytest.raises(CxPrivateContentError) as exc_info:
        build_private_text_store({PRIVATE_STORAGE_MODE_ENV: "bad"})
    assert exc_info.value.error_code == "CX_PRIVATE_STORAGE_MODE_INVALID"
    with pytest.raises(CxPrivateContentError) as exc_info:
        build_private_text_store({PRIVATE_STORAGE_MODE_ENV: "s3"})
    assert exc_info.value.error_code == "CX_PRIVATE_STORAGE_CONFIGURATION_INVALID"
    with pytest.raises(CxPrivateContentError) as exc_info:
        build_private_text_store({
            **env,
            "NEX_CX_OBJECT_STORAGE_ENDPOINT": "http://rustfs:9000",
            "NEX_CX_OBJECT_STORAGE_ALLOW_INSECURE": "true",
            "NEX_RUNTIME_PROFILE": "production",
        })
    assert exc_info.value.error_code == "CX_PRIVATE_STORAGE_INSECURE_FORBIDDEN"
    with pytest.raises(CxPrivateContentError) as exc_info:
        build_private_text_store({**env, "NEX_CX_OBJECT_STORAGE_ALLOW_INSECURE": "maybe"})
    assert exc_info.value.error_code == "CX_PRIVATE_STORAGE_MODE_INVALID"
    assert isinstance(build_private_text_store({
        **env,
        "NEX_CX_OBJECT_STORAGE_ENDPOINT": "http://rustfs:9000",
        "NEX_CX_OBJECT_STORAGE_ALLOW_INSECURE": "true",
        "NEX_RUNTIME_PROFILE": "protected_test",
    }), S3CxPrivateTextStore)

