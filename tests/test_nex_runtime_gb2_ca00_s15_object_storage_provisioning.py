from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from nex_runtime import object_storage_provisioning as provisioning
from nex_runtime.object_storage_lifecycle import BucketBootstrapReceipt
from nex_runtime.object_storage_provisioning import (
    OBJECT_STORAGE_OWNER_SPECS,
    ObjectStorageOwnerCredential,
    ObjectStorageProvisioningError,
    provision_object_storage_environment,
    verify_object_storage_runtime_readiness,
)

NOW = "2026-10-28T13:00:00Z"


class Denied(Exception):
    def __init__(self, status: int = 403) -> None:
        self.response = {"ResponseMetadata": {"HTTPStatusCode": status}}


class OwnerClient:
    def __init__(self, bucket: str, *, failure: Exception | None = None) -> None:
        self.bucket = bucket
        self.failure = failure
        self.calls: list[str] = []

    def head_bucket(self, *, Bucket):
        self.calls.append(Bucket)
        if self.failure is not None:
            raise self.failure
        if Bucket != self.bucket:
            raise Denied()
        return {}


class RootClient:
    pass


class Iam:
    def __init__(self, *, mutate=None, raises: bool = False) -> None:
        self.mutate = mutate
        self.raises = raises
        self.calls: list[dict] = []

    def provision_bucket_owner(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError("private IAM detail")
        result = {
            "schema_version": "rustfs_bucket_owner_provision.v1",
            "status": "PROVISIONED",
            "policy_name": kwargs["policy_name"],
            "bucket_scope_count": 1,
            "root_credential_reused": False,
        }
        return self.mutate(result) if self.mutate else result


def credentials():
    return tuple(
        ObjectStorageOwnerCredential(
            owner=spec.owner,
            access_key=f"{spec.evidence_alias}-access-key",
            secret_key=f"{spec.evidence_alias}-private-secret-value",
        )
        for spec in OBJECT_STORAGE_OWNER_SPECS
    )


def clients():
    return {spec.owner: OwnerClient(spec.bucket) for spec in OBJECT_STORAGE_OWNER_SPECS}


def bootstrap(_client, *, bucket):
    return BucketBootstrapReceipt(
        bucket=bucket,
        created=True,
        versioning_enabled=True,
        encryption_algorithm="AES256",
        lifecycle_rule_count=3,
        policy_digest="a" * 64,
    )


def test_provisions_source_backed_buckets_iam_and_runtime_readiness() -> None:
    iam = Iam()
    owner_clients = clients()

    result = provision_object_storage_environment(
        RootClient(),
        iam,
        owner_clients=owner_clients,
        credentials=credentials(),
        bucket_bootstrap=bootstrap,
        checked_at="2026-10-28T22:00:00+09:00",
    )
    serialized = json.dumps(result, sort_keys=True)

    assert result["status"] == "PASS"
    assert result["owner_count"] == result["bucket_count"] == 2
    assert result["owner_identity_count"] == 2
    assert result["readiness_status"] == "READY"
    assert result["cross_bucket_denied"] == {
        "ae_to_cx_denied": True,
        "cx_to_ae_denied": True,
    }
    assert all(item["ready"] for item in result["dependency_readiness"])
    assert all(item["checked_at"] == NOW for item in result["dependency_readiness"])
    assert [call["bucket"] for call in iam.calls] == [
        "nex-ae-private",
        "nex-cx-private",
    ]
    assert "private-secret-value" not in serialized
    assert "https://" not in serialized
    assert "nex-wa" not in serialized


def test_restart_readiness_rechecks_owner_access_and_isolation() -> None:
    owner_clients = clients()
    first = verify_object_storage_runtime_readiness(owner_clients, checked_at=NOW)
    restarted = verify_object_storage_runtime_readiness(owner_clients)

    assert first["status"] == restarted["status"] == "READY"
    assert (
        first["dependency_readiness"][0]["evidence_hash"]
        == restarted["dependency_readiness"][0]["evidence_hash"]
    )
    assert all(len(client.calls) == 4 for client in owner_clients.values())


def test_owner_order_and_credential_repr_are_deterministic_and_secret_free() -> None:
    reversed_result = verify_object_storage_runtime_readiness(
        clients(),
        owner_specs=tuple(reversed(OBJECT_STORAGE_OWNER_SPECS)),
        checked_at=NOW,
    )
    credential = credentials()[0]

    assert [
        item["dependency_id"] for item in reversed_result["dependency_readiness"]
    ] == [
        "object-storage:ae",
        "object-storage:cx",
    ]
    assert "access-key" not in repr(credential)
    assert "private-secret-value" not in repr(credential)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (Denied(403), "owner readiness failed"),
        (RuntimeError("private endpoint"), "owner readiness failed"),
    ],
)
def test_owner_readiness_failure_is_sanitized(failure, message) -> None:
    owner_clients = clients()
    owner_clients["nex-ae-api"].failure = failure

    with pytest.raises(ObjectStorageProvisioningError, match=message) as raised:
        verify_object_storage_runtime_readiness(owner_clients, checked_at=NOW)

    assert "private endpoint" not in str(raised.value)


def test_cross_owner_probe_fails_closed_for_access_or_unknown_error() -> None:
    class Permissive(OwnerClient):
        def head_bucket(self, *, Bucket):
            self.calls.append(Bucket)
            return {}

    owner_clients = clients()
    owner_clients["nex-ae-api"] = Permissive("nex-ae-private")
    with pytest.raises(ObjectStorageProvisioningError, match="isolation"):
        verify_object_storage_runtime_readiness(owner_clients, checked_at=NOW)

    owner_clients = clients()
    original = owner_clients["nex-ae-api"]

    class Unknown(OwnerClient):
        def head_bucket(self, *, Bucket):
            if Bucket == self.bucket:
                return {}
            raise Denied(500)

    owner_clients["nex-ae-api"] = Unknown(original.bucket)
    with pytest.raises(ObjectStorageProvisioningError, match="probe failed") as raised:
        verify_object_storage_runtime_readiness(owner_clients, checked_at=NOW)
    assert "500" not in str(raised.value)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda values: values[:1], "owner coverage"),
        (
            lambda values: (*values, values[0]),
            "owner coverage",
        ),
        (
            lambda values: (
                replace(values[0], access_key="short"),
                values[1],
            ),
            "credential is invalid",
        ),
        (
            lambda values: (
                replace(values[0], secret_key="short"),
                values[1],
            ),
            "credential is invalid",
        ),
    ],
)
def test_credential_inventory_fails_closed(mutation, message) -> None:
    with pytest.raises(ObjectStorageProvisioningError, match=message):
        provision_object_storage_environment(
            RootClient(),
            Iam(),
            owner_clients=clients(),
            credentials=mutation(credentials()),
            bucket_bootstrap=bootstrap,
            checked_at=NOW,
        )


@pytest.mark.parametrize(
    ("specs", "message"),
    [
        (OBJECT_STORAGE_OWNER_SPECS[:1], "owner inventory"),
        (
            (
                replace(OBJECT_STORAGE_OWNER_SPECS[0], owner="nex-wa"),
                OBJECT_STORAGE_OWNER_SPECS[1],
            ),
            "owner inventory",
        ),
        (
            (
                replace(OBJECT_STORAGE_OWNER_SPECS[0], bucket="bad"),
                OBJECT_STORAGE_OWNER_SPECS[1],
            ),
            "specification",
        ),
        (
            (
                replace(OBJECT_STORAGE_OWNER_SPECS[0], evidence_alias="bad"),
                OBJECT_STORAGE_OWNER_SPECS[1],
            ),
            "metadata",
        ),
    ],
)
def test_owner_spec_inventory_rejects_drift_and_wa(specs, message) -> None:
    with pytest.raises(ObjectStorageProvisioningError, match=message):
        verify_object_storage_runtime_readiness(
            clients(), owner_specs=specs, checked_at=NOW
        )


def test_source_owner_inventory_drift_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        provisioning,
        "OBJECT_STORAGE_OWNERS",
        {"nex-cx": ("NEX_CX", "changed"), "nex-ae-api": ("NEX_AE", "nex-ae-private")},
    )
    with pytest.raises(ObjectStorageProvisioningError, match="source owner"):
        verify_object_storage_runtime_readiness(clients(), checked_at=NOW)


def test_runtime_client_coverage_and_timestamp_fail_closed() -> None:
    with pytest.raises(ObjectStorageProvisioningError, match="client owner coverage"):
        verify_object_storage_runtime_readiness(
            {"nex-ae-api": clients()["nex-ae-api"]}, checked_at=NOW
        )
    for value in ("bad", "2026-10-28T13:00:00", None):
        if value is None:
            assert provisioning._checked_at(value).endswith("Z")
        else:
            with pytest.raises(ObjectStorageProvisioningError, match="timestamp"):
                provisioning._checked_at(value)


@pytest.mark.parametrize(
    ("bucket_factory", "iam", "message"),
    [
        (
            lambda _client, *, bucket: (_ for _ in ()).throw(
                RuntimeError("private bucket detail")
            ),
            Iam(),
            "bucket provisioning failed",
        ),
        (
            bootstrap,
            Iam(raises=True),
            "IAM provisioning failed",
        ),
        (
            lambda _client, *, bucket: type(
                "Receipt", (), {"evidence": lambda self: {"status": "bad"}}
            )(),
            Iam(),
            "bucket provisioning evidence",
        ),
        (
            bootstrap,
            Iam(mutate=lambda value: {**value, "bucket_scope_count": 2}),
            "IAM provisioning evidence",
        ),
    ],
)
def test_provisioning_sanitizes_and_rejects_invalid_receipts(
    bucket_factory, iam, message
) -> None:
    with pytest.raises(ObjectStorageProvisioningError, match=message) as raised:
        provision_object_storage_environment(
            RootClient(),
            iam,
            owner_clients=clients(),
            credentials=credentials(),
            bucket_bootstrap=bucket_factory,
            checked_at=NOW,
        )
    assert "private" not in str(raised.value).lower()


def test_demo_and_s146_runners_consume_canonical_object_storage_operation() -> None:
    root = Path(provisioning.__file__).resolve().parents[3]
    demo = (
        root / "scripts/deployment/run_canonical_platform_installed_acceptance.py"
    ).read_text(encoding="utf-8")
    protected = (
        root / "scripts/smoke/run_s146_object_storage_acceptance.py"
    ).read_text(encoding="utf-8")

    assert "provision_object_storage_environment(" in demo
    assert "iam.provision_bucket_owner(" not in demo
    assert "provision_object_storage_environment(" in protected
    assert "def _cross_bucket_isolation(" not in protected
