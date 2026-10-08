from __future__ import annotations

import hashlib
import io
from types import SimpleNamespace

import pytest

from nex_runtime.object_storage import (
    ObjectStorageError,
    S3ObjectStore,
    build_owner_object_key,
    build_s3_client,
    object_storage_settings,
)


class ClientFailure(Exception):
    def __init__(self, status: int = 0, code: str = "") -> None:
        super().__init__("private upstream detail")
        self.response = {
            "ResponseMetadata": {"HTTPStatusCode": status},
            "Error": {"Code": code},
        }


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}
        self.failures: dict[str, Exception] = {}

    def _fail(self, operation: str) -> None:
        if operation in self.failures:
            raise self.failures[operation]

    def head_bucket(self, **kwargs):
        self._fail("head_bucket")
        return {"bucket": kwargs["Bucket"]}

    def head_object(self, **kwargs):
        self._fail("head_object")
        try:
            return dict(self.objects[kwargs["Key"]]["head"])
        except KeyError as exc:
            raise ClientFailure(404, "NoSuchKey") from exc

    def put_object(self, **kwargs):
        self._fail("put_object")
        key = kwargs["Key"]
        if key in self.objects:
            raise ClientFailure(412, "PreconditionFailed")
        self.objects[key] = {
            "payload": kwargs["Body"],
            "head": {
                "ContentLength": len(kwargs["Body"]),
                "ContentType": kwargs["ContentType"],
                "Metadata": kwargs["Metadata"],
                "ServerSideEncryption": kwargs["ServerSideEncryption"],
                "VersionId": "v1",
            },
        }
        return {"VersionId": "v1"}

    def get_object(self, **kwargs):
        self._fail("get_object")
        try:
            payload = self.objects[kwargs["Key"]]["payload"]
        except KeyError as exc:
            raise ClientFailure(404, "NotFound") from exc
        return {"Body": io.BytesIO(payload)}

    def delete_object(self, **kwargs):
        self._fail("delete_object")
        self.objects.pop(kwargs["Key"], None)
        return {"VersionId": "delete-v1"}


def settings_env() -> dict[str, str]:
    return {
        "NEX_CX_OBJECT_STORAGE_BACKEND": "s3",
        "NEX_CX_OBJECT_STORAGE_ENDPOINT": "https://object.example.test/",
        "NEX_CX_OBJECT_STORAGE_BUCKET": "nex-cx-private",
        "NEX_CX_OBJECT_STORAGE_ACCESS_KEY": "cx-access-key",
        "NEX_CX_OBJECT_STORAGE_SECRET_KEY": "cx-secret-key-long",
        "NEX_CX_OBJECT_STORAGE_CA_BUNDLE": "/run/secrets/platform_ca",
        "NEX_CX_OBJECT_STORAGE_REGION": "local-1",
    }


def test_settings_are_owner_scoped_and_fail_closed() -> None:
    settings = object_storage_settings("nex-cx", settings_env())
    assert settings.bucket == "nex-cx-private"
    assert settings.endpoint_url == "https://object.example.test"
    assert settings.ca_bundle == "/run/secrets/platform_ca"
    assert settings.region == "local-1"

    ae_env = {
        "NEX_AE_OBJECT_STORAGE_BACKEND": "S3",
        "NEX_AE_OBJECT_STORAGE_ENDPOINT": "http://rustfs:9000",
        "NEX_AE_OBJECT_STORAGE_ACCESS_KEY": "ae-access-key",
        "NEX_AE_OBJECT_STORAGE_SECRET_KEY": "ae-secret-key-long",
    }
    ae = object_storage_settings("nex-ae-api", ae_env, allow_insecure_endpoint=True)
    assert ae.bucket == "nex-ae-private"
    assert ae.region == "us-east-1"
    assert ae.ca_bundle is None

    bad_cases = [
        ("unknown", settings_env(), False, "OBJECT_STORAGE_OWNER_UNSUPPORTED"),
        ("nex-cx", {}, False, "OBJECT_STORAGE_CONFIGURATION_MISSING"),
        ("nex-cx", {**settings_env(), "NEX_CX_OBJECT_STORAGE_BACKEND": "RUSTFS"}, False, "OBJECT_STORAGE_BACKEND_UNSUPPORTED"),
        ("nex-cx", {**settings_env(), "NEX_CX_OBJECT_STORAGE_ENDPOINT": "http://rustfs:9000"}, False, "OBJECT_STORAGE_ENDPOINT_INVALID"),
        ("nex-cx", {**settings_env(), "NEX_CX_OBJECT_STORAGE_ENDPOINT": "https://user:pass@host/path?q=1"}, False, "OBJECT_STORAGE_ENDPOINT_INVALID"),
        ("nex-cx", {**settings_env(), "NEX_CX_OBJECT_STORAGE_BUCKET": "127.0.0.1"}, False, "OBJECT_STORAGE_BUCKET_INVALID"),
        ("nex-cx", {**settings_env(), "NEX_CX_OBJECT_STORAGE_BUCKET": "bad..bucket"}, False, "OBJECT_STORAGE_BUCKET_INVALID"),
        ("nex-cx", {**settings_env(), "NEX_CX_OBJECT_STORAGE_ACCESS_KEY": "short"}, False, "OBJECT_STORAGE_CREDENTIAL_INVALID"),
        ("nex-cx", {**settings_env(), "NEX_CX_OBJECT_STORAGE_SECRET_KEY": "placeholder"}, False, "OBJECT_STORAGE_CREDENTIAL_INVALID"),
    ]
    for owner, env, allow, code in bad_cases:
        with pytest.raises(ObjectStorageError) as exc_info:
            object_storage_settings(owner, env, allow_insecure_endpoint=allow)
        assert exc_info.value.code == code


def test_owner_object_key_is_opaque_deterministic_and_validated() -> None:
    key = build_owner_object_key(
        payload_family="generation-output",
        tenant_id="tenant-private",
        subject_id="user-private",
        content_id="response-private",
        suffix=".json",
    )
    assert key.startswith("v1/generation-output/")
    assert key.endswith(".json")
    assert all(value not in key for value in ("tenant-private", "user-private", "response-private"))
    assert key == build_owner_object_key(
        payload_family="generation-output",
        tenant_id="tenant-private",
        subject_id="user-private",
        content_id="response-private",
        suffix="json",
    )
    for values in (
        {"payload_family": "../bad", "tenant_id": "t", "subject_id": "s", "content_id": "c", "suffix": "txt"},
        {"payload_family": "text", "tenant_id": "", "subject_id": "s", "content_id": "c", "suffix": "txt"},
        {"payload_family": "text", "tenant_id": "t", "subject_id": "s", "content_id": "c", "suffix": "toolongsuffixvalue"},
    ):
        with pytest.raises(ObjectStorageError):
            build_owner_object_key(**values)


def test_immutable_put_get_head_delete_and_readiness() -> None:
    client = FakeS3Client()
    store = S3ObjectStore(client, object_storage_settings("nex-cx", settings_env()))
    payload = b"private payload"
    digest = hashlib.sha256(payload).hexdigest()
    key = build_owner_object_key(
        payload_family="text", tenant_id="t", subject_id="s", content_id="c", suffix="utf8"
    )
    assert store.check_ready() is True
    assert store.head(key) is None
    created = store.put_immutable(
        key=key, payload=payload, expected_sha256=digest, content_type="text/plain"
    )
    assert created.storage_uri == f"s3://nex-cx-private/{key}"
    assert created.version_id == "v1"
    assert created.server_side_encryption == "AES256"
    client.objects[key]["head"]["Metadata"] = {"Sha256": digest}
    assert store.head(key) == created
    assert store.put_immutable(
        key=key, payload=payload, expected_sha256=digest, content_type="text/plain"
    ) == created
    assert store.get_bytes(
        key=key,
        expected_sha256=digest,
        expected_size_bytes=len(payload),
        max_size_bytes=100,
    ) == payload
    assert store.delete(key) == "delete-v1"
    assert store.get_bytes(
        key=key, expected_sha256=digest, expected_size_bytes=len(payload), max_size_bytes=100
    ) is None


def test_store_rejects_integrity_metadata_size_key_and_immutable_drift() -> None:
    client = FakeS3Client()
    store = S3ObjectStore(client, object_storage_settings("nex-cx", settings_env()))
    payload = b"payload"
    digest = hashlib.sha256(payload).hexdigest()
    key = "v1/text/aa/owner/content.utf8"
    with pytest.raises(ObjectStorageError, match="integrity"):
        store.put_immutable(key=key, payload=payload, expected_sha256="0" * 64, content_type="text/plain")
    with pytest.raises(ObjectStorageError) as exc_info:
        store.put_immutable(key=key, payload="bad", expected_sha256=digest, content_type="text/plain")  # type: ignore[arg-type]
    assert exc_info.value.code == "OBJECT_STORAGE_PAYLOAD_INVALID"
    store.put_immutable(key=key, payload=payload, expected_sha256=digest, content_type="text/plain")
    client.objects[key]["head"]["Metadata"] = {}
    with pytest.raises(ObjectStorageError) as exc_info:
        store.head(key)
    assert exc_info.value.code == "OBJECT_STORAGE_METADATA_INVALID"
    client.objects[key]["head"]["Metadata"] = {"sha256": digest}
    client.objects[key]["head"]["ServerSideEncryption"] = None
    with pytest.raises(ObjectStorageError) as exc_info:
        store.put_immutable(key=key, payload=payload, expected_sha256=digest, content_type="text/plain")
    assert exc_info.value.code == "OBJECT_STORAGE_IMMUTABLE_CONFLICT"
    for invalid in ("bad", "v1/../bad", "v1/a//b"):
        with pytest.raises(ObjectStorageError):
            store.head(invalid)
    with pytest.raises(ObjectStorageError) as exc_info:
        store.get_bytes(key=key, expected_sha256=digest, expected_size_bytes=101, max_size_bytes=100)
    assert exc_info.value.code == "OBJECT_STORAGE_SIZE_INVALID"


def test_store_maps_client_failures_without_leaking_details() -> None:
    client = FakeS3Client()
    store = S3ObjectStore(client, object_storage_settings("nex-cx", settings_env()))
    key = "v1/text/aa/owner/content.utf8"
    cases = [
        ("head_bucket", lambda: store.check_ready(), "OBJECT_STORAGE_UNAVAILABLE", True),
        ("head_object", lambda: store.head(key), "OBJECT_STORAGE_HEAD_FAILED", True),
        ("put_object", lambda: store.put_immutable(key=key, payload=b"x", expected_sha256=hashlib.sha256(b"x").hexdigest(), content_type="text/plain"), "OBJECT_STORAGE_PUT_FAILED", False),
        ("get_object", lambda: store.get_bytes(key=key, expected_sha256=hashlib.sha256(b"x").hexdigest(), expected_size_bytes=1, max_size_bytes=1), "OBJECT_STORAGE_GET_FAILED", True),
        ("delete_object", lambda: store.delete(key), "OBJECT_STORAGE_DELETE_FAILED", True),
    ]
    for operation, call, code, retryable in cases:
        client.objects.clear()
        client.failures = {operation: ClientFailure(503 if retryable else 403, "Denied")}
        with pytest.raises(ObjectStorageError) as exc_info:
            call()
        assert exc_info.value.code == code
        assert exc_info.value.retryable is retryable
        assert "private upstream detail" not in str(exc_info.value)


def test_read_limits_body_failures_publish_race_and_builder(monkeypatch) -> None:
    client = FakeS3Client()
    store = S3ObjectStore(client, object_storage_settings("nex-cx", settings_env()))
    key = "v1/text/aa/owner/content.utf8"
    payload = b"xy"
    digest = hashlib.sha256(payload).hexdigest()
    store.put_immutable(key=key, payload=payload, expected_sha256=digest, content_type="text/plain")
    with pytest.raises(ObjectStorageError) as exc_info:
        store.get_bytes(key=key, expected_sha256=digest, expected_size_bytes=1, max_size_bytes=2)
    assert exc_info.value.code == "OBJECT_STORAGE_SIZE_MISMATCH"
    client.objects[key]["payload"] = b"xyz"
    with pytest.raises(ObjectStorageError) as exc_info:
        store.get_bytes(key=key, expected_sha256=digest, expected_size_bytes=2, max_size_bytes=2)
    assert exc_info.value.code == "OBJECT_STORAGE_SIZE_MISMATCH"

    class BrokenBody:
        def read(self, _size):
            raise OSError("private")

        def close(self):
            self.closed = True

    client.get_object = lambda **_kwargs: {"Body": BrokenBody()}  # type: ignore[method-assign]
    with pytest.raises(ObjectStorageError) as exc_info:
        store.get_bytes(key=key, expected_sha256=digest, expected_size_bytes=2, max_size_bytes=2)
    assert exc_info.value.code == "OBJECT_STORAGE_READ_FAILED"

    captured: dict[str, object] = {}
    fake_config = SimpleNamespace(Config=lambda **kwargs: captured.setdefault("config", kwargs) or kwargs)
    fake_boto = SimpleNamespace(client=lambda *args, **kwargs: captured.update(args=args, kwargs=kwargs) or client)

    def fake_import(name: str):
        return fake_boto if name == "boto3" else fake_config

    monkeypatch.setattr("nex_runtime.object_storage.importlib.import_module", fake_import)
    settings = object_storage_settings("nex-cx", settings_env())
    assert build_s3_client(settings) is client
    assert captured["args"] == ("s3",)
    assert captured["kwargs"]["verify"] == "/run/secrets/platform_ca"


def test_publish_race_incomplete_visibility_and_body_without_close() -> None:
    key = "v1/text/aa/owner/content.utf8"
    payload = b"xy"
    digest = hashlib.sha256(payload).hexdigest()
    settings = object_storage_settings("nex-cx", settings_env())

    race_client = FakeS3Client()
    race_store = S3ObjectStore(race_client, settings)
    original_put = race_client.put_object

    def concurrent_put(**kwargs):
        original_put(**kwargs)
        raise ClientFailure(412, "PreconditionFailed")

    race_client.put_object = concurrent_put  # type: ignore[method-assign]
    published = race_store.put_immutable(
        key=key,
        payload=payload,
        expected_sha256=digest,
        content_type="text/plain",
    )
    assert published.sha256 == digest

    invisible_client = FakeS3Client()
    invisible_client.put_object = lambda **_kwargs: {}  # type: ignore[method-assign]
    invisible_store = S3ObjectStore(invisible_client, settings)
    with pytest.raises(ObjectStorageError) as exc_info:
        invisible_store.put_immutable(
            key=key,
            payload=payload,
            expected_sha256=digest,
            content_type="text/plain",
        )
    assert exc_info.value.code == "OBJECT_STORAGE_PUBLISH_INCOMPLETE"
    assert exc_info.value.retryable is True

    class BodyWithoutClose:
        def read(self, _size):
            return payload

    read_client = FakeS3Client()
    read_client.get_object = lambda **_kwargs: {"Body": BodyWithoutClose()}  # type: ignore[method-assign]
    read_store = S3ObjectStore(read_client, settings)
    assert read_store.get_bytes(
        key=key,
        expected_sha256=digest,
        expected_size_bytes=len(payload),
        max_size_bytes=10,
    ) == payload
