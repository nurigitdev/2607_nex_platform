from __future__ import annotations

import hashlib
import io
import json

import pytest

import run_s146_object_storage_lifecycle as lifecycle_script
from nex_runtime.object_storage import (
    ObjectMetadata,
    ObjectStorageError,
    ObjectStorageSettings,
    S3ObjectStore,
)
from nex_runtime.object_storage_lifecycle import (
    ObjectLifecycleError,
    PrivateBucketLifecyclePolicy,
    assess_purge_admission,
    bootstrap_private_bucket,
    lifecycle_configuration,
    mark_versions_purge_eligible,
    restore_object_version,
)


class ClientFailure(Exception):
    def __init__(self, status: int, code: str = "") -> None:
        self.response = {
            "ResponseMetadata": {"HTTPStatusCode": status},
            "Error": {"Code": code},
        }


class FakeLifecycleClient:
    def __init__(self, *, bucket_exists: bool = False) -> None:
        self.bucket_exists = bucket_exists
        self.versioning = {}
        self.encryption = {}
        self.lifecycle = {}
        self.failures: dict[str, Exception] = {}
        self.tags: dict[tuple[str, str], list[dict[str, str]]] = {}
        self.source_versions: dict[tuple[str, str], dict] = {}
        self.current: dict[str, dict] = {}
        self.version_counter = 0

    def _fail(self, operation: str) -> None:
        if operation in self.failures:
            raise self.failures[operation]

    def head_bucket(self, **_kwargs):
        self._fail("head_bucket")
        if not self.bucket_exists:
            raise ClientFailure(404, "NoSuchBucket")
        return {}

    def create_bucket(self, **_kwargs):
        self._fail("create_bucket")
        self.bucket_exists = True
        return {}

    def put_bucket_versioning(self, *, VersioningConfiguration, **_kwargs):
        self._fail("put_bucket_versioning")
        self.versioning = dict(VersioningConfiguration)
        return {}

    def get_bucket_versioning(self, **_kwargs):
        return dict(self.versioning)

    def put_bucket_encryption(self, *, ServerSideEncryptionConfiguration, **_kwargs):
        self.encryption = dict(ServerSideEncryptionConfiguration)
        return {}

    def get_bucket_encryption(self, **_kwargs):
        return {"ServerSideEncryptionConfiguration": self.encryption}

    def put_bucket_lifecycle_configuration(self, *, LifecycleConfiguration, **_kwargs):
        self.lifecycle = dict(LifecycleConfiguration)
        return {}

    def get_bucket_lifecycle_configuration(self, **_kwargs):
        return dict(self.lifecycle)

    def get_object_tagging(self, *, Key, VersionId, **_kwargs):
        self._fail("get_object_tagging")
        return {"TagSet": list(self.tags.get((Key, VersionId), []))}

    def put_object_tagging(self, *, Key, VersionId, Tagging, **_kwargs):
        self._fail("put_object_tagging")
        self.tags[(Key, VersionId)] = list(Tagging["TagSet"])
        return {}

    def head_object(self, *, Key, **_kwargs):
        self._fail("head_object")
        if Key not in self.current:
            raise ClientFailure(404, "NoSuchKey")
        return dict(self.current[Key]["head"])

    def put_object(self, *, Key, Body, ContentType, Metadata, ServerSideEncryption, **_kwargs):
        self._fail("put_object")
        self.version_counter += 1
        version_id = f"restored-{self.version_counter}"
        self.current[Key] = {
            "body": Body,
            "head": {
                "ContentLength": len(Body),
                "ContentType": ContentType,
                "Metadata": dict(Metadata),
                "ServerSideEncryption": ServerSideEncryption,
                "VersionId": version_id,
            },
        }
        return {"VersionId": version_id}

    def get_object(self, *, Key, VersionId=None, **_kwargs):
        self._fail("get_object")
        if VersionId is not None:
            response = dict(self.source_versions[(Key, VersionId)])
            response["Body"] = io.BytesIO(response["payload"])
            response.pop("payload")
            return response
        current = self.current[Key]
        return {"Body": io.BytesIO(current["body"])}

    def delete_object(self, **_kwargs):
        return {"VersionId": "delete-marker"}


def _settings() -> ObjectStorageSettings:
    return ObjectStorageSettings(
        owner="nex-cx",
        endpoint_url="https://object.example.test",
        bucket="nex-cx-private",
        access_key="access-key",
        secret_key="secret-key-value",
    )


def _restore_source(client: FakeLifecycleClient, payload: bytes = b"private"):
    key = "v1/text/aa/owner/content.utf8"
    version_id = "source-version-1"
    digest = hashlib.sha256(payload).hexdigest()
    client.source_versions[(key, version_id)] = {
        "payload": payload,
        "ContentLength": len(payload),
        "ContentType": "text/plain; charset=utf-8",
        "Metadata": {"sha256": digest},
        "ServerSideEncryption": "AES256",
    }
    return key, version_id, digest


def test_lifecycle_configuration_is_hold_aware_and_bounded():
    config = lifecycle_configuration()
    rules = {rule["ID"]: rule for rule in config["Rules"]}
    purge = rules["purge-eligible-noncurrent-versions"]
    assert purge["Filter"]["Tag"] == {
        "Key": "nex-purge",
        "Value": "eligible",
    }
    assert purge["NoncurrentVersionExpiration"]["NoncurrentDays"] == 30
    assert rules["abort-incomplete-multipart"]["AbortIncompleteMultipartUpload"] == {
        "DaysAfterInitiation": 7
    }
    assert rules["remove-expired-delete-markers"]["Expiration"] == {
        "ExpiredObjectDeleteMarker": True
    }

    for policy in (
        PrivateBucketLifecyclePolicy(0, 7),
        PrivateBucketLifecyclePolicy(30, 0),
        PrivateBucketLifecyclePolicy(True, 7),
    ):
        with pytest.raises(ObjectLifecycleError) as captured:
            lifecycle_configuration(policy)
        assert captured.value.code == "BUCKET_LIFECYCLE_INVALID"


def test_bucket_bootstrap_creates_applies_and_verifies_policy():
    client = FakeLifecycleClient()
    receipt = bootstrap_private_bucket(client, bucket="nex-cx-private")
    assert receipt.created is True
    assert receipt.versioning_enabled is True
    assert receipt.encryption_algorithm == "AES256"
    assert receipt.lifecycle_rule_count == 3
    evidence = receipt.evidence()
    assert evidence["status"] == "VERIFIED"
    assert "nex-cx-private" not in json.dumps(evidence)

    existing = bootstrap_private_bucket(client, bucket="nex-cx-private")
    assert existing.created is False
    assert existing.policy_digest == receipt.policy_digest


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("versioning", "BUCKET_VERSIONING_INVALID"),
        ("encryption", "BUCKET_ENCRYPTION_INVALID"),
        ("lifecycle", "BUCKET_LIFECYCLE_INVALID"),
    ],
)
def test_bucket_bootstrap_rejects_policy_readback_drift(mutation, code):
    client = FakeLifecycleClient(bucket_exists=True)
    if mutation == "versioning":
        client.get_bucket_versioning = lambda **kwargs: {"Status": "Suspended"}
    elif mutation == "encryption":
        client.get_bucket_encryption = lambda **kwargs: {
            "ServerSideEncryptionConfiguration": {"Rules": []}
        }
    else:
        client.get_bucket_lifecycle_configuration = lambda **kwargs: {"Rules": []}
    with pytest.raises(ObjectLifecycleError) as captured:
        bootstrap_private_bucket(client, bucket="nex-cx-private")
    assert captured.value.code == code


def test_bucket_bootstrap_rejects_malformed_and_changed_policy_readback():
    malformed = FakeLifecycleClient(bucket_exists=True)
    malformed.get_bucket_lifecycle_configuration = lambda **kwargs: {"Rules": {}}
    with pytest.raises(ObjectLifecycleError) as rules:
        bootstrap_private_bucket(malformed, bucket="nex-cx-private")
    assert rules.value.code == "BUCKET_LIFECYCLE_INVALID"

    changed = FakeLifecycleClient(bucket_exists=True)

    def changed_lifecycle(**kwargs):
        config = lifecycle_configuration()
        config["Rules"][0]["Status"] = "Disabled"
        return config

    changed.get_bucket_lifecycle_configuration = changed_lifecycle
    with pytest.raises(ObjectLifecycleError) as field:
        bootstrap_private_bucket(changed, bucket="nex-cx-private")
    assert field.value.code == "BUCKET_LIFECYCLE_INVALID"

    malformed_encryption = FakeLifecycleClient(bucket_exists=True)
    malformed_encryption.get_bucket_encryption = lambda **kwargs: {
        "ServerSideEncryptionConfiguration": {
            "Rules": [{"ApplyServerSideEncryptionByDefault": "AES256"}, "bad"]
        }
    }
    with pytest.raises(ObjectLifecycleError) as encryption:
        bootstrap_private_bucket(malformed_encryption, bucket="nex-cx-private")
    assert encryption.value.code == "BUCKET_ENCRYPTION_INVALID"


@pytest.mark.parametrize(
    ("failure", "code", "retryable"),
    [
        ({"head_bucket": ClientFailure(403)}, "BUCKET_READINESS_FAILED", False),
        ({"create_bucket": ClientFailure(503)}, "BUCKET_CREATE_FAILED", True),
        ({"put_bucket_versioning": ClientFailure(503)}, "BUCKET_POLICY_APPLY_FAILED", True),
    ],
)
def test_bucket_bootstrap_maps_client_failures(failure, code, retryable):
    client = FakeLifecycleClient()
    client.failures = failure
    with pytest.raises(ObjectLifecycleError) as captured:
        bootstrap_private_bucket(client, bucket="nex-cx-private")
    assert captured.value.code == code
    assert captured.value.retryable is retryable


def test_bucket_bootstrap_rejects_invalid_bucket():
    with pytest.raises(ObjectLifecycleError) as captured:
        bootstrap_private_bucket(FakeLifecycleClient(), bucket="Bad/Bucket")
    assert captured.value.code == "BUCKET_NAME_INVALID"


def test_purge_admission_requires_every_guard():
    blocked = assess_purge_admission(
        active_reference_count=2,
        legal_hold=True,
        purge_decision_recorded=False,
        rollback_window_elapsed=False,
    )
    assert blocked.admitted is False
    assert blocked.reason_codes == (
        "active_references_present",
        "legal_hold_active",
        "purge_decision_missing",
        "rollback_window_open",
    )
    assert blocked.evidence()["destructive_delete_performed"] is False
    admitted = assess_purge_admission(
        active_reference_count=0,
        legal_hold=False,
        purge_decision_recorded=True,
        rollback_window_elapsed=True,
    )
    assert admitted.admitted is True
    with pytest.raises(ObjectLifecycleError) as invalid:
        assess_purge_admission(
            active_reference_count=-1,
            legal_hold=False,
            purge_decision_recorded=True,
            rollback_window_elapsed=True,
        )
    assert invalid.value.code == "PURGE_REFERENCE_COUNT_INVALID"
    with pytest.raises(ObjectLifecycleError):
        assess_purge_admission(
            active_reference_count="0",  # type: ignore[arg-type]
            legal_hold=False,
            purge_decision_recorded=True,
            rollback_window_elapsed=True,
        )


def test_purge_tagging_preserves_tags_and_discloses_no_versions():
    client = FakeLifecycleClient(bucket_exists=True)
    key = "v1/text/aa/owner/content.utf8"
    client.tags[(key, "version-1")] = [{"Key": "classification", "Value": "private"}]
    admission = assess_purge_admission(
        active_reference_count=0,
        legal_hold=False,
        purge_decision_recorded=True,
        rollback_window_elapsed=True,
    )
    receipt = mark_versions_purge_eligible(
        client,
        bucket="nex-cx-private",
        key=key,
        version_ids=("version-1", "version-2"),
        admission=admission,
    )
    assert receipt.version_count == 2
    assert client.tags[(key, "version-1")] == [
        {"Key": "classification", "Value": "private"},
        {"Key": "nex-purge", "Value": "eligible"},
    ]
    assert "version-1" not in json.dumps(receipt.evidence())


def test_purge_tagging_rejects_unadmitted_invalid_and_client_failures():
    client = FakeLifecycleClient(bucket_exists=True)
    key = "v1/text/aa/owner/content.utf8"
    blocked = assess_purge_admission(
        active_reference_count=1,
        legal_hold=False,
        purge_decision_recorded=True,
        rollback_window_elapsed=True,
    )
    with pytest.raises(ObjectLifecycleError) as admission:
        mark_versions_purge_eligible(
            client,
            bucket="nex-cx-private",
            key=key,
            version_ids=("version-1",),
            admission=blocked,
        )
    assert admission.value.code == "PURGE_NOT_ADMITTED"

    allowed = assess_purge_admission(
        active_reference_count=0,
        legal_hold=False,
        purge_decision_recorded=True,
        rollback_window_elapsed=True,
    )
    for versions in ((), ("bad version",), ("version-1", "version-1")):
        with pytest.raises(ObjectLifecycleError):
            mark_versions_purge_eligible(
                client,
                bucket="nex-cx-private",
                key=key,
                version_ids=versions,
                admission=allowed,
            )
    client.failures["get_object_tagging"] = ClientFailure(503)
    with pytest.raises(ObjectLifecycleError) as unavailable:
        mark_versions_purge_eligible(
            client,
            bucket="nex-cx-private",
            key=key,
            version_ids=("version-1",),
            admission=allowed,
        )
    assert unavailable.value.code == "PURGE_TAGGING_FAILED"
    assert unavailable.value.retryable is True


@pytest.mark.parametrize(
    "tag_set",
    [
        {},
        ["bad"],
        [{"Key": 1, "Value": "value"}],
    ],
)
def test_purge_tagging_rejects_malformed_existing_tags(tag_set):
    client = FakeLifecycleClient(bucket_exists=True)
    client.get_object_tagging = lambda **kwargs: {"TagSet": tag_set}
    allowed = assess_purge_admission(
        active_reference_count=0,
        legal_hold=False,
        purge_decision_recorded=True,
        rollback_window_elapsed=True,
    )
    with pytest.raises(ObjectLifecycleError) as captured:
        mark_versions_purge_eligible(
            client,
            bucket="nex-cx-private",
            key="v1/text/aa/owner/content.utf8",
            version_ids=("version-1",),
            admission=allowed,
        )
    assert captured.value.code == "PURGE_TAG_SET_INVALID"
    assert captured.value.retryable is False


def test_purge_tagging_rejects_invalid_bucket_and_key():
    client = FakeLifecycleClient(bucket_exists=True)
    allowed = assess_purge_admission(
        active_reference_count=0,
        legal_hold=False,
        purge_decision_recorded=True,
        rollback_window_elapsed=True,
    )
    with pytest.raises(ObjectLifecycleError) as bucket:
        mark_versions_purge_eligible(
            client,
            bucket="bad/bucket",
            key="v1/text/aa/owner/content.utf8",
            version_ids=("version-1",),
            admission=allowed,
        )
    assert bucket.value.code == "BUCKET_NAME_INVALID"
    with pytest.raises(ObjectLifecycleError) as key:
        mark_versions_purge_eligible(
            client,
            bucket="nex-cx-private",
            key="../unsafe",
            version_ids=("version-1",),
            admission=allowed,
        )
    assert key.value.code == "OBJECT_KEY_INVALID"


def test_restore_version_republishes_and_verifies_current_object():
    client = FakeLifecycleClient(bucket_exists=True)
    key, version_id, digest = _restore_source(client)
    client.source_versions[(key, version_id)]["Metadata"] = {"Sha256": digest}
    store = S3ObjectStore(client, _settings())
    receipt = restore_object_version(
        client,
        store,
        key=key,
        version_id=version_id,
        expected_key_prefix="v1/text/aa/",
        expected_sha256=digest,
        expected_size_bytes=len(b"private"),
        expected_content_type="text/plain; charset=utf-8",
        max_size_bytes=100,
    )
    assert client.current[key]["body"] == b"private"
    assert receipt.sha256 == digest
    evidence = receipt.evidence()
    serialized = json.dumps(evidence)
    assert key not in serialized
    assert version_id not in serialized
    assert evidence["payload_disclosed"] is False


def test_restore_rejects_scope_metadata_active_and_source_corruption():
    client = FakeLifecycleClient(bucket_exists=True)
    key, version_id, digest = _restore_source(client)
    store = S3ObjectStore(client, _settings())
    base = dict(
        client=client,
        store=store,
        key=key,
        version_id=version_id,
        expected_key_prefix="v1/text/aa/",
        expected_sha256=digest,
        expected_size_bytes=7,
        expected_content_type="text/plain; charset=utf-8",
        max_size_bytes=100,
    )
    with pytest.raises(ObjectLifecycleError) as scope:
        restore_object_version(**{**base, "expected_key_prefix": "v1/text/bb/"})
    assert scope.value.code == "RESTORE_OWNER_SCOPE_INVALID"
    with pytest.raises(ObjectLifecycleError) as metadata:
        restore_object_version(**{**base, "expected_sha256": "bad"})
    assert metadata.value.code == "RESTORE_METADATA_INVALID"

    client.current[key] = {
        "body": b"active",
        "head": {
            "ContentLength": 6,
            "ContentType": "text/plain",
            "Metadata": {"sha256": hashlib.sha256(b"active").hexdigest()},
            "ServerSideEncryption": "AES256",
            "VersionId": "active-version",
        },
    }
    with pytest.raises(ObjectLifecycleError) as active:
        restore_object_version(**base)
    assert active.value.code == "RESTORE_ACTIVE_VERSION_CONFLICT"
    client.current.clear()

    client.source_versions[(key, version_id)]["Metadata"] = {"sha256": "0" * 64}
    with pytest.raises(ObjectLifecycleError) as corrupt:
        restore_object_version(**base)
    assert corrupt.value.code == "RESTORE_INTEGRITY_MISMATCH"


def test_restore_maps_source_and_publication_failures():
    client = FakeLifecycleClient(bucket_exists=True)
    key, version_id, digest = _restore_source(client)
    store = S3ObjectStore(client, _settings())
    args = dict(
        client=client,
        store=store,
        key=key,
        version_id=version_id,
        expected_key_prefix="v1/text/aa/",
        expected_sha256=digest,
        expected_size_bytes=7,
        expected_content_type="text/plain; charset=utf-8",
        max_size_bytes=100,
    )
    client.failures["get_object"] = ClientFailure(503)
    with pytest.raises(ObjectLifecycleError) as source:
        restore_object_version(**args)
    assert source.value.code == "RESTORE_SOURCE_READ_FAILED"
    assert source.value.retryable is True
    client.failures.clear()

    client.failures["put_object"] = ClientFailure(503)
    with pytest.raises(ObjectLifecycleError) as publish:
        restore_object_version(**args)
    assert publish.value.code == "RESTORE_PUBLICATION_FAILED"
    assert publish.value.retryable is True


def test_restore_maps_head_failure_and_rejects_unverified_publication():
    client = FakeLifecycleClient(bucket_exists=True)
    key, version_id, digest = _restore_source(client)
    store = S3ObjectStore(client, _settings())
    args = dict(
        client=client,
        store=store,
        key=key,
        version_id=version_id,
        expected_key_prefix="v1/text/aa/",
        expected_sha256=digest,
        expected_size_bytes=7,
        expected_content_type="text/plain; charset=utf-8",
        max_size_bytes=100,
    )
    client.failures["head_object"] = ObjectStorageError(
        "OBJECT_STORAGE_UNAVAILABLE", "private", retryable=True
    )
    with pytest.raises(ObjectLifecycleError) as head:
        restore_object_version(**args)
    assert head.value.code == "RESTORE_TARGET_READ_FAILED"
    client.failures.clear()

    class UnverifiedStore:
        settings = _settings()

        def head(self, key):
            return None

        def put_immutable(self, **kwargs):
            return ObjectMetadata(
                bucket="nex-cx-private",
                key=key,
                sha256=digest,
                size_bytes=7,
                content_type="text/plain; charset=utf-8",
                version_id=None,
                server_side_encryption="AES256",
            )

        def get_bytes(self, **kwargs):
            return b"private"

    with pytest.raises(ObjectLifecycleError) as verify:
        restore_object_version(**{**args, "store": UnverifiedStore()})
    assert verify.value.code == "RESTORE_VERIFICATION_FAILED"


@pytest.mark.parametrize("body_value", [b"private too long", "not-bytes"])
def test_restore_rejects_oversized_or_nonbyte_body(body_value):
    client = FakeLifecycleClient(bucket_exists=True)
    key, version_id, digest = _restore_source(client)

    class Body:
        def read(self, size):
            return body_value

    client.get_object = lambda **kwargs: {
        **client.source_versions[(key, version_id)],
        "Body": Body(),
    }
    client.source_versions[(key, version_id)].pop("payload")
    with pytest.raises(ObjectLifecycleError) as captured:
        restore_object_version(
            client,
            S3ObjectStore(client, _settings()),
            key=key,
            version_id=version_id,
            expected_key_prefix="v1/text/aa/",
            expected_sha256=digest,
            expected_size_bytes=7,
            expected_content_type="text/plain; charset=utf-8",
            max_size_bytes=7,
        )
    assert captured.value.code == "RESTORE_SIZE_MISMATCH"


def test_restore_maps_body_read_failure():
    client = FakeLifecycleClient(bucket_exists=True)
    key, version_id, digest = _restore_source(client)

    class BrokenBody:
        def read(self, size):
            raise OSError("private")

        def close(self):
            self.closed = True

    client.get_object = lambda **kwargs: {
        **client.source_versions[(key, version_id)],
        "Body": BrokenBody(),
    }
    with pytest.raises(ObjectLifecycleError) as captured:
        restore_object_version(
            client,
            S3ObjectStore(client, _settings()),
            key=key,
            version_id=version_id,
            expected_key_prefix="v1/text/aa/",
            expected_sha256=digest,
            expected_size_bytes=7,
            expected_content_type="text/plain; charset=utf-8",
            max_size_bytes=100,
        )
    assert captured.value.code == "RESTORE_SOURCE_READ_FAILED"


def _bootstrap_env() -> dict[str, str]:
    return {
        "NEX_OBJECT_STORAGE_BOOTSTRAP_ENDPOINT": "https://object.example.test",
        "NEX_OBJECT_STORAGE_BOOTSTRAP_ACCESS_KEY": "bootstrap-access",
        "NEX_OBJECT_STORAGE_BOOTSTRAP_SECRET_KEY": "bootstrap-secret-value",
    }


def test_lifecycle_runner_uses_bootstrap_credentials_and_redacts_evidence():
    client = FakeLifecycleClient()
    result = lifecycle_script.run_object_storage_lifecycle(
        owner="nex-cx",
        environ=_bootstrap_env(),
        client=client,
    )
    assert result["status"] == "PASS"
    serialized = json.dumps(result)
    assert "bootstrap-access" not in serialized
    assert "object.example.test" not in serialized


def test_lifecycle_runner_configuration_guards():
    with pytest.raises(ObjectLifecycleError) as owner:
        lifecycle_script.run_object_storage_lifecycle(
            owner="unknown", environ={}, client=FakeLifecycleClient()
        )
    assert owner.value.code == "BUCKET_OWNER_UNSUPPORTED"
    with pytest.raises(ObjectLifecycleError) as missing:
        lifecycle_script.run_object_storage_lifecycle(
            owner="nex-cx", environ={}, client=FakeLifecycleClient()
        )
    assert missing.value.code == "BUCKET_BOOTSTRAP_CONFIGURATION_INVALID"
    with pytest.raises(ObjectLifecycleError) as flag:
        lifecycle_script.run_object_storage_lifecycle(
            owner="nex-cx",
            environ={
                **_bootstrap_env(),
                "NEX_OBJECT_STORAGE_BOOTSTRAP_ALLOW_INSECURE": "maybe",
            },
            client=FakeLifecycleClient(),
        )
    assert flag.value.code == "BUCKET_BOOTSTRAP_CONFIGURATION_INVALID"
    with pytest.raises(ObjectLifecycleError) as insecure:
        lifecycle_script.run_object_storage_lifecycle(
            owner="nex-cx",
            environ={
                **_bootstrap_env(),
                "NEX_OBJECT_STORAGE_BOOTSTRAP_ENDPOINT": "http://rustfs:9000",
                "NEX_OBJECT_STORAGE_BOOTSTRAP_ALLOW_INSECURE": "true",
                "NEX_RUNTIME_PROFILE": "production",
            },
            client=FakeLifecycleClient(),
        )
    assert insecure.value.code == "BUCKET_BOOTSTRAP_INSECURE_FORBIDDEN"


def test_lifecycle_runner_allows_test_http_and_optional_settings():
    client = FakeLifecycleClient()
    result = lifecycle_script.run_object_storage_lifecycle(
        owner="nex-ae-api",
        environ={
            **_bootstrap_env(),
            "NEX_OBJECT_STORAGE_BOOTSTRAP_ENDPOINT": "http://rustfs:9000",
            "NEX_OBJECT_STORAGE_BOOTSTRAP_ALLOW_INSECURE": "true",
            "NEX_RUNTIME_PROFILE": "protected_test",
            "NEX_OBJECT_STORAGE_BOOTSTRAP_CA_BUNDLE": "/run/secrets/ca.pem",
            "NEX_AE_OBJECT_STORAGE_BUCKET": "custom-ae-private",
        },
        client=client,
    )
    assert result["status"] == "PASS"
    assert lifecycle_script._allow_insecure({}) is False


def test_lifecycle_runner_maps_readiness_and_client_failures(monkeypatch):
    class FinalReadinessFailure(FakeLifecycleClient):
        def __init__(self):
            super().__init__(bucket_exists=True)
            self.head_count = 0

        def head_bucket(self, **kwargs):
            self.head_count += 1
            if self.head_count > 1:
                raise ClientFailure(503)
            return {}

    with pytest.raises(ObjectLifecycleError) as readiness:
        lifecycle_script.run_object_storage_lifecycle(
            owner="nex-cx",
            environ=_bootstrap_env(),
            client=FinalReadinessFailure(),
        )
    assert readiness.value.code == "BUCKET_READINESS_FAILED"

    monkeypatch.setattr(
        lifecycle_script,
        "build_s3_client",
        lambda settings: (_ for _ in ()).throw(ImportError("private")),
    )
    with pytest.raises(ObjectLifecycleError) as client:
        lifecycle_script.run_object_storage_lifecycle(
            owner="nex-cx", environ=_bootstrap_env()
        )
    assert client.value.code == "BUCKET_CLIENT_UNAVAILABLE"


def test_lifecycle_cli_redacts_failures_and_returns_success(monkeypatch, capsys):
    monkeypatch.setattr(
        lifecycle_script,
        "run_object_storage_lifecycle",
        lambda **kwargs: {"status": "PASS"},
    )
    assert lifecycle_script.main(["--owner", "nex-cx"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    def fail(**kwargs):
        raise ObjectLifecycleError("LIFECYCLE_FAILED", "private detail", True)

    monkeypatch.setattr(lifecycle_script, "run_object_storage_lifecycle", fail)
    assert lifecycle_script.main(["--owner", "nex-cx"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["error_code"] == "LIFECYCLE_FAILED"
    assert "private detail" not in json.dumps(output)
