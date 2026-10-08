from __future__ import annotations

import hashlib
import io

import pytest

from nex_runtime.object_storage import (
    ObjectStorageError,
    ObjectStorageSettings,
    S3ObjectStore,
)
from nex_ae_api.artifacts import (
    ArtifactHandoffError,
    S3RenderedArtifactStorage,
    build_default_rendered_artifact_storage,
    build_rendered_artifact_file,
)
from nex_ae_api.generated_response_storage import (
    GeneratedResponseStorageError,
    S3GeneratedResponseStorage,
    build_default_generated_response_storage,
    build_generated_response_payload,
    delete_generated_response_for_record,
    generated_response_storage_metadata,
    load_generated_response_for_record,
    save_generated_response_for_record,
)
from nex_ae_api.private_object_store import (
    AePrivateObjectStorageError,
    ae_private_storage_mode,
    build_ae_private_object_store,
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
        if self.failure:
            raise self.failure
        self.objects[Key] = {
            "body": Body,
            "head": {
                "ContentLength": len(Body),
                "ContentType": ContentType,
                "Metadata": Metadata,
                "ServerSideEncryption": ServerSideEncryption,
                "VersionId": "version-1457",
            },
        }
        return {"VersionId": "version-1457"}

    def get_object(self, *, Key, **_kwargs):
        if self.failure:
            raise self.failure
        if Key not in self.objects:
            raise ClientFailure(404)
        return {"Body": io.BytesIO(self.objects[Key]["body"])}

    def delete_object(self, *, Key, **_kwargs):
        if self.failure:
            raise self.failure
        self.objects.pop(Key, None)
        return {"VersionId": "delete-1457"}

    def head_bucket(self, **_kwargs):
        if self.failure:
            raise self.failure
        return {}


def _object_store() -> tuple[S3ObjectStore, FakeClient]:
    settings = ObjectStorageSettings(
        owner="nex-ae-api",
        endpoint_url="https://object.example.test",
        bucket="nex-ae-private",
        access_key="access-key",
        secret_key="secret-key-value",
    )
    client = FakeClient()
    return S3ObjectStore(client, settings), client


def _owner_record(subject_id: str = "user-a") -> dict:
    return {
        "tenant_id": "tenant-a",
        "owner_user_id": subject_id,
    }


def _artifact_file(payload: bytes = b"private artifact") -> dict:
    return build_rendered_artifact_file(
        artifact_record={
            "artifact_id": "artifact-1457",
            "display_title": "Private Customer Report",
            "owner_actor_ref": {
                "actor_type": "user",
                "actor_id": "user-a",
                "tenant_id": "tenant-a",
            },
        },
        artifact_version={
            "artifact_version_id": "version-1457",
            "artifact_content_hash": "a" * 64,
            "created_at": "2026-10-08T00:00:00Z",
        },
        target_format="PDF",
        payload=payload,
    )


def test_generated_response_s3_round_trip_is_owner_scoped_and_compensatable() -> None:
    object_store, client = _object_store()
    storage = S3GeneratedResponseStorage(object_store)
    payload = build_generated_response_payload(
        response_id="response-1457",
        content="Owner-private generated response.",
    )
    metadata = generated_response_storage_metadata(payload)

    assert save_generated_response_for_record(
        storage,
        payload,
        _owner_record(),
    ) == payload["storage_ref"]
    key = next(iter(client.objects))
    assert key.startswith("v1/chat-response/")
    assert all(value not in key for value in ("tenant-a", "user-a", "response-1457"))
    assert load_generated_response_for_record(
        storage,
        metadata,
        _owner_record(),
    ) == payload["content"]
    assert load_generated_response_for_record(
        storage,
        metadata,
        _owner_record("user-b"),
    ) is None
    assert delete_generated_response_for_record(
        storage,
        metadata,
        _owner_record(),
    ) is True
    assert delete_generated_response_for_record(
        storage,
        metadata,
        _owner_record(),
    ) is False


def test_generated_response_s3_rejects_corruption_outage_and_invalid_owner(
    monkeypatch,
) -> None:
    object_store, client = _object_store()
    storage = S3GeneratedResponseStorage(object_store)
    payload = build_generated_response_payload(
        response_id="response-1457",
        content="private",
    )
    metadata = generated_response_storage_metadata(payload)
    save_generated_response_for_record(storage, payload, _owner_record())
    key = next(iter(client.objects))
    client.objects[key]["body"] = b"tampered"
    with pytest.raises(GeneratedResponseStorageError) as corrupted:
        load_generated_response_for_record(storage, metadata, _owner_record())
    assert corrupted.value.error_code == "ae.generated_response_integrity_failed"

    client.failure = ClientFailure(503)
    with pytest.raises(GeneratedResponseStorageError) as unavailable:
        load_generated_response_for_record(storage, metadata, _owner_record())
    assert unavailable.value.retryable is True
    client.failure = None

    with pytest.raises(GeneratedResponseStorageError):
        save_generated_response_for_record(storage, payload, {})
    monkeypatch.setattr(
        "nex_ae_api.generated_response_storage.MAX_GENERATED_RESPONSE_BYTES", 2
    )
    with pytest.raises(GeneratedResponseStorageError):
        save_generated_response_for_record(storage, payload, _owner_record())


def test_generated_response_s3_maps_publish_delete_and_key_failures(
    monkeypatch,
) -> None:
    object_store, client = _object_store()
    storage = S3GeneratedResponseStorage(object_store)
    payload = build_generated_response_payload(
        response_id="response-errors",
        content="private",
    )
    metadata = generated_response_storage_metadata(payload)
    client.failure = ClientFailure(503)
    with pytest.raises(GeneratedResponseStorageError) as publish:
        save_generated_response_for_record(storage, payload, _owner_record())
    assert publish.value.retryable is True

    client.failure = None
    save_generated_response_for_record(storage, payload, _owner_record())
    client.failure = ClientFailure(503)
    with pytest.raises(GeneratedResponseStorageError) as deletion:
        delete_generated_response_for_record(storage, metadata, _owner_record())
    assert deletion.value.retryable is True
    client.failure = None

    with pytest.raises(GeneratedResponseStorageError):
        storage._key(tenant_id="", subject_id="user-a", response_id="response")

    def fail_get(**_kwargs):
        raise ObjectStorageError("OBJECT_STORAGE_OTHER", "private detail")

    monkeypatch.setattr(object_store, "get_bytes", fail_get)
    with pytest.raises(GeneratedResponseStorageError) as generic:
        load_generated_response_for_record(storage, metadata, _owner_record())
    assert generic.value.error_code == "ae.generated_response_storage_invalid"
    assert "private detail" not in generic.value.detail


def test_rendered_artifact_s3_round_trip_uses_opaque_metadata_reference() -> None:
    object_store, client = _object_store()
    storage = S3RenderedArtifactStorage(object_store)
    payload = b"private artifact"
    artifact_file = _artifact_file(payload)

    assert artifact_file["file_name"] == "private-customer-report.pdf"
    assert "private-customer-report" not in artifact_file["storage_ref"]
    assert storage.save_rendered_artifact_file(artifact_file, payload) == artifact_file[
        "storage_ref"
    ]
    key = next(iter(client.objects))
    assert artifact_file["storage_ref"] == f"ae://artifacts/{key}"
    assert key.startswith("v1/artifact/")
    assert all(value not in key for value in ("tenant-a", "user-a", "artifact-1457"))
    assert storage.get_rendered_artifact_file(artifact_file) == payload
    assert storage.delete_rendered_artifact_file(artifact_file) is True
    assert storage.delete_rendered_artifact_file(artifact_file) is False


def test_rendered_artifact_s3_validates_payload_metadata_and_utf8(
    monkeypatch,
) -> None:
    object_store, client = _object_store()
    storage = S3RenderedArtifactStorage(object_store)
    artifact_file = _artifact_file()

    with pytest.raises(ArtifactHandoffError) as wrong_size:
        storage.save_rendered_artifact_file(artifact_file, b"wrong")
    assert wrong_size.value.status_code == 409
    with pytest.raises(ArtifactHandoffError):
        storage.save_rendered_artifact_file(artifact_file, object())  # type: ignore[arg-type]
    with pytest.raises(ArtifactHandoffError):
        storage.get_rendered_artifact_file(
            {**artifact_file, "storage_ref": "ae://artifacts/legacy/file.pdf"}
        )
    with pytest.raises(ArtifactHandoffError):
        storage.get_rendered_artifact_file(
            {**artifact_file, "file_size_bytes": -1}
        )

    markdown = b"valid markdown"
    markdown_file = {
        **_artifact_file(markdown),
        "format": "MD",
        "mime_type": "text/markdown",
        "storage_ref": _artifact_file(markdown)["storage_ref"].removesuffix(".pdf")
        + ".md",
    }
    storage.save_rendered_artifact_file(markdown_file, markdown)
    key = markdown_file["storage_ref"].removeprefix("ae://artifacts/")
    client.objects[key]["body"] = b"\xff"
    invalid_digest = hashlib.sha256(b"\xff").hexdigest()
    client.objects[key]["head"]["ContentLength"] = 1
    client.objects[key]["head"]["Metadata"] = {"sha256": invalid_digest}
    invalid_file = {
        **markdown_file,
        "file_hash": invalid_digest,
        "file_size_bytes": 1,
    }
    with pytest.raises(ArtifactHandoffError) as encoding:
        storage.get_markdown(invalid_file)
    assert encoding.value.error_code == "ae.artifact_storage_integrity_failed"

    client.failure = ClientFailure(503)
    with pytest.raises(ArtifactHandoffError) as unavailable:
        storage.get_rendered_artifact_file(invalid_file)
    assert unavailable.value.retryable is True
    monkeypatch.setattr(
        "nex_ae_api.artifacts.MAX_RENDERED_ARTIFACT_BYTES", 0
    )
    with pytest.raises(ArtifactHandoffError):
        storage.get_rendered_artifact_file(invalid_file)


def test_rendered_artifact_s3_maps_missing_publish_delete_and_markdown_failures(
) -> None:
    object_store, client = _object_store()
    storage = S3RenderedArtifactStorage(object_store)
    payload = b"private artifact"
    artifact_file = _artifact_file(payload)
    markdown_file = {
        **artifact_file,
        "format": "MD",
        "mime_type": "text/markdown",
        "storage_ref": artifact_file["storage_ref"].removesuffix(".pdf") + ".md",
    }
    assert storage.get_markdown(markdown_file) is None
    with pytest.raises(ArtifactHandoffError):
        storage.save_markdown(markdown_file, object())  # type: ignore[arg-type]

    client.failure = ClientFailure(503)
    with pytest.raises(ArtifactHandoffError) as publish:
        storage.save_rendered_artifact_file(artifact_file, payload)
    assert publish.value.retryable is True

    client.failure = None
    storage.save_rendered_artifact_file(artifact_file, payload)
    client.failure = ClientFailure(503)
    with pytest.raises(ArtifactHandoffError) as deletion:
        storage.delete_rendered_artifact_file(artifact_file)
    assert deletion.value.retryable is True


def test_ae_private_storage_builders_select_s3_and_fail_closed(monkeypatch) -> None:
    object_store, _client = _object_store()
    monkeypatch.setattr(
        "nex_ae_api.generated_response_storage.build_ae_private_object_store",
        lambda _env: object_store,
    )
    monkeypatch.setattr(
        "nex_ae_api.artifacts.build_ae_private_object_store",
        lambda _env: object_store,
    )
    env = {
        "NEX_AE_PRIVATE_STORAGE_MODE": "S3",
        "NEX_AE_OBJECT_STORAGE_BACKEND": "S3",
        "NEX_AE_OBJECT_STORAGE_ENDPOINT": "https://object.example.test",
        "NEX_AE_OBJECT_STORAGE_ACCESS_KEY": "ae-access-key",
        "NEX_AE_OBJECT_STORAGE_SECRET_KEY": "ae-secret-key-long",
    }
    assert isinstance(
        build_default_generated_response_storage(env),
        S3GeneratedResponseStorage,
    )
    assert isinstance(
        build_default_rendered_artifact_storage(env),
        S3RenderedArtifactStorage,
    )
    with pytest.raises(GeneratedResponseStorageError):
        build_default_generated_response_storage(
            {"NEX_AE_PRIVATE_STORAGE_MODE": "FILESYSTEM"}
        )
    with pytest.raises(ArtifactHandoffError):
        build_default_rendered_artifact_storage(
            {"NEX_AE_PRIVATE_STORAGE_MODE": "FILESYSTEM"}
        )
    with pytest.raises(GeneratedResponseStorageError):
        build_default_generated_response_storage(
            {"NEX_AE_PRIVATE_STORAGE_MODE": "invalid"}
        )


def test_ae_private_object_store_configuration_guards(monkeypatch) -> None:
    object_store, _client = _object_store()
    monkeypatch.setattr(
        "nex_ae_api.private_object_store.build_s3_client",
        lambda _settings: object_store.client,
    )
    env = {
        "NEX_AE_PRIVATE_STORAGE_MODE": "S3",
        "NEX_AE_OBJECT_STORAGE_BACKEND": "S3",
        "NEX_AE_OBJECT_STORAGE_ENDPOINT": "https://object.example.test",
        "NEX_AE_OBJECT_STORAGE_ACCESS_KEY": "ae-access-key",
        "NEX_AE_OBJECT_STORAGE_SECRET_KEY": "ae-secret-key-long",
    }
    assert build_ae_private_object_store(env).settings.bucket == "nex-ae-private"
    assert ae_private_storage_mode({}) is None
    assert ae_private_storage_mode({"NEX_AE_PRIVATE_STORAGE_MODE": "filesystem"}) == (
        "FILESYSTEM"
    )
    with pytest.raises(AePrivateObjectStorageError):
        build_ae_private_object_store({})
    with pytest.raises(AePrivateObjectStorageError):
        build_ae_private_object_store({"NEX_AE_PRIVATE_STORAGE_MODE": "S3"})
    with pytest.raises(AePrivateObjectStorageError):
        build_ae_private_object_store(
            {**env, "NEX_AE_OBJECT_STORAGE_ALLOW_INSECURE": "maybe"}
        )
    with pytest.raises(AePrivateObjectStorageError) as forbidden:
        build_ae_private_object_store(
            {
                **env,
                "NEX_AE_OBJECT_STORAGE_ENDPOINT": "http://rustfs:9000",
                "NEX_AE_OBJECT_STORAGE_ALLOW_INSECURE": "true",
                "NEX_RUNTIME_PROFILE": "production",
            }
        )
    assert forbidden.value.error_code == "ae.private_object_storage_insecure_forbidden"
    allowed = build_ae_private_object_store(
        {
            **env,
            "NEX_AE_OBJECT_STORAGE_ENDPOINT": "http://rustfs:9000",
            "NEX_AE_OBJECT_STORAGE_ALLOW_INSECURE": "true",
            "NEX_RUNTIME_PROFILE": "protected_test",
        }
    )
    assert allowed.settings.endpoint_url == "http://rustfs:9000"
    assert str(forbidden.value) == forbidden.value.detail
