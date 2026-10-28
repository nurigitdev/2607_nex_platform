from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from .dependency_readiness import (
    DependencyReadinessRequirement,
    normalize_dependency_readiness,
)
from .object_storage import OBJECT_STORAGE_OWNERS, S3Client
from .object_storage_lifecycle import (
    BucketBootstrapReceipt,
    ObjectLifecycleClient,
    bootstrap_private_bucket,
)

OBJECT_STORAGE_PROVISIONING_SCHEMA_VERSION = "object_storage_provisioning.v1"
OBJECT_STORAGE_RUNTIME_READINESS_SCHEMA_VERSION = (
    "object_storage_runtime_readiness.v1"
)
_OWNER = re.compile(r"^nex-(?:ae-api|cx)$")
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_POLICY = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ObjectStorageProvisioningError(ValueError):
    pass


@dataclass(frozen=True)
class ObjectStorageOwnerSpec:
    owner: str
    bucket: str
    policy_name: str
    dependency_id: str
    evidence_alias: str


@dataclass(frozen=True)
class ObjectStorageOwnerCredential:
    owner: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)


class RustfsIamProvisioner(Protocol):
    def provision_bucket_owner(
        self,
        *,
        access_key: str,
        secret_key: str,
        bucket: str,
        policy_name: str,
    ) -> Mapping[str, Any]: ...


BucketBootstrap = Callable[..., BucketBootstrapReceipt]


OBJECT_STORAGE_OWNER_SPECS = (
    ObjectStorageOwnerSpec(
        owner="nex-ae-api",
        bucket="nex-ae-private",
        policy_name="nex-ae-private-rw",
        dependency_id="object-storage:ae",
        evidence_alias="ae",
    ),
    ObjectStorageOwnerSpec(
        owner="nex-cx",
        bucket="nex-cx-private",
        policy_name="nex-cx-private-rw",
        dependency_id="object-storage:cx",
        evidence_alias="cx",
    ),
)


def provision_object_storage_environment(
    root_client: ObjectLifecycleClient,
    iam: RustfsIamProvisioner,
    *,
    owner_clients: Mapping[str, S3Client],
    credentials: Sequence[ObjectStorageOwnerCredential],
    owner_specs: Sequence[ObjectStorageOwnerSpec] = OBJECT_STORAGE_OWNER_SPECS,
    bucket_bootstrap: BucketBootstrap = bootstrap_private_bucket,
    checked_at: str | None = None,
) -> dict[str, Any]:
    """Provision private buckets and identities, then prove runtime isolation."""

    specs = _validate_specs(owner_specs)
    credential_by_owner = _credential_inventory(credentials, specs)
    _validate_owner_clients(owner_clients, specs)

    bucket_receipts = []
    iam_receipts = []
    for spec in specs:
        try:
            bucket_receipt = bucket_bootstrap(root_client, bucket=spec.bucket)
            bucket_evidence = bucket_receipt.evidence()
        except Exception:  # noqa: BLE001 - sanitize storage implementation detail
            raise ObjectStorageProvisioningError(
                f"Object-storage bucket provisioning failed for owner: {spec.owner}"
            ) from None
        _validate_bucket_evidence(bucket_evidence)
        bucket_receipts.append(bucket_evidence)

        credential = credential_by_owner[spec.owner]
        try:
            iam_receipt = iam.provision_bucket_owner(
                access_key=credential.access_key,
                secret_key=credential.secret_key,
                bucket=spec.bucket,
                policy_name=spec.policy_name,
            )
        except Exception:  # noqa: BLE001 - sanitize storage implementation detail
            raise ObjectStorageProvisioningError(
                f"Object-storage IAM provisioning failed for owner: {spec.owner}"
            ) from None
        iam_receipts.append(_iam_evidence(iam_receipt, spec=spec))

    runtime = verify_object_storage_runtime_readiness(
        owner_clients,
        owner_specs=specs,
        checked_at=checked_at,
    )
    return {
        "schema_version": OBJECT_STORAGE_PROVISIONING_SCHEMA_VERSION,
        "status": "PASS",
        "owner_count": len(specs),
        "bucket_count": len(bucket_receipts),
        "owner_identity_count": len(iam_receipts),
        "bucket_receipts": bucket_receipts,
        "iam_receipts": iam_receipts,
        "cross_bucket_denied": runtime["cross_bucket_denied"],
        "dependency_readiness": runtime["dependency_readiness"],
        "readiness_status": runtime["readiness_status"],
        "root_credential_reused_by_service": False,
        "secret_included": False,
        "endpoint_included": False,
    }


def verify_object_storage_runtime_readiness(
    owner_clients: Mapping[str, S3Client],
    *,
    owner_specs: Sequence[ObjectStorageOwnerSpec] = OBJECT_STORAGE_OWNER_SPECS,
    checked_at: str | None = None,
) -> dict[str, Any]:
    """Verify owner reachability and authorization without retaining payloads."""

    specs = _validate_specs(owner_specs)
    _validate_owner_clients(owner_clients, specs)
    timestamp = _checked_at(checked_at)

    for spec in specs:
        try:
            owner_clients[spec.owner].head_bucket(Bucket=spec.bucket)
        except Exception:  # noqa: BLE001 - sanitize provider/credential details
            raise ObjectStorageProvisioningError(
                f"Object-storage owner readiness failed for owner: {spec.owner}"
            ) from None

    isolation: dict[str, bool] = {}
    for source in specs:
        for target in specs:
            if source.owner == target.owner:
                continue
            denied = _head_bucket_denied(
                owner_clients[source.owner], target.bucket, owner=source.owner
            )
            key = f"{source.evidence_alias}_to_{target.evidence_alias}_denied"
            isolation[key] = denied
    if not isolation or not all(isolation.values()):
        raise ObjectStorageProvisioningError(
            "Object-storage cross-owner isolation verification failed"
        )

    readiness = [
        normalize_dependency_readiness(
            DependencyReadinessRequirement(
                dependency_id=spec.dependency_id,
                dependency_type="OBJECT_STORAGE",
                owner=spec.owner,
                required=True,
            ),
            configured=True,
            provisioned=True,
            reachable=True,
            authorized=True,
            checked_at=timestamp,
        ).to_projection()
        for spec in specs
    ]
    return {
        "schema_version": OBJECT_STORAGE_RUNTIME_READINESS_SCHEMA_VERSION,
        "status": "READY",
        "readiness_status": "READY",
        "owner_count": len(specs),
        "cross_bucket_denied": isolation,
        "dependency_readiness": readiness,
        "raw_secret_values_included": False,
        "private_payloads_included": False,
        "object_keys_included": False,
        "endpoints_included": False,
    }


def _validate_specs(
    owner_specs: Sequence[ObjectStorageOwnerSpec],
) -> tuple[ObjectStorageOwnerSpec, ...]:
    specs = tuple(owner_specs)
    expected = {
        "nex-ae-api": "nex-ae-private",
        "nex-cx": "nex-cx-private",
    }
    source_backed = {
        owner: bucket for owner, (_prefix, bucket) in OBJECT_STORAGE_OWNERS.items()
    }
    if source_backed != {"nex-cx": expected["nex-cx"], "nex-ae-api": expected["nex-ae-api"]}:
        raise ObjectStorageProvisioningError(
            "Object-storage source owner inventory drift"
        )
    if len(specs) != 2 or {spec.owner for spec in specs} != set(expected):
        raise ObjectStorageProvisioningError("Object-storage owner inventory is invalid")
    aliases = {spec.evidence_alias for spec in specs}
    dependencies = {spec.dependency_id for spec in specs}
    if aliases != {"ae", "cx"} or dependencies != {
        "object-storage:ae",
        "object-storage:cx",
    }:
        raise ObjectStorageProvisioningError("Object-storage owner metadata is invalid")
    for spec in specs:
        if (
            not _OWNER.fullmatch(spec.owner)
            or spec.bucket != expected[spec.owner]
            or not _BUCKET.fullmatch(spec.bucket)
            or not _POLICY.fullmatch(spec.policy_name)
        ):
            raise ObjectStorageProvisioningError(
                "Object-storage owner specification is invalid"
            )
    return tuple(sorted(specs, key=lambda item: item.evidence_alias))


def _credential_inventory(
    credentials: Sequence[ObjectStorageOwnerCredential],
    specs: Sequence[ObjectStorageOwnerSpec],
) -> dict[str, ObjectStorageOwnerCredential]:
    values = tuple(credentials)
    by_owner = {item.owner: item for item in values}
    if len(values) != len(by_owner) or set(by_owner) != {spec.owner for spec in specs}:
        raise ObjectStorageProvisioningError(
            "Object-storage credential owner coverage is invalid"
        )
    if any(
        len(item.access_key.strip()) < 8 or len(item.secret_key.strip()) < 16
        for item in values
    ):
        raise ObjectStorageProvisioningError("Object-storage credential is invalid")
    return by_owner


def _validate_owner_clients(
    owner_clients: Mapping[str, S3Client], specs: Sequence[ObjectStorageOwnerSpec]
) -> None:
    if set(owner_clients) != {spec.owner for spec in specs}:
        raise ObjectStorageProvisioningError(
            "Object-storage runtime client owner coverage is invalid"
        )


def _validate_bucket_evidence(evidence: Any) -> None:
    if (
        not isinstance(evidence, Mapping)
        or evidence.get("schema_version") != "private_bucket_bootstrap.v1"
        or evidence.get("status") != "VERIFIED"
        or not isinstance(evidence.get("created"), bool)
        or evidence.get("versioning_enabled") is not True
        or evidence.get("encryption_algorithm") != "AES256"
        or not isinstance(evidence.get("lifecycle_rule_count"), int)
        or evidence.get("lifecycle_rule_count") < 1
        or not isinstance(evidence.get("bucket_ref"), str)
        or _SHA256.fullmatch(evidence["bucket_ref"]) is None
        or not isinstance(evidence.get("policy_digest"), str)
        or _SHA256.fullmatch(evidence["policy_digest"]) is None
    ):
        raise ObjectStorageProvisioningError(
            "Object-storage bucket provisioning evidence is invalid"
        )


def _iam_evidence(
    receipt: Mapping[str, Any], *, spec: ObjectStorageOwnerSpec
) -> dict[str, Any]:
    if (
        not isinstance(receipt, Mapping)
        or receipt.get("schema_version") != "rustfs_bucket_owner_provision.v1"
        or receipt.get("status") != "PROVISIONED"
        or receipt.get("policy_name") != spec.policy_name
        or receipt.get("bucket_scope_count") != 1
        or receipt.get("root_credential_reused") is not False
    ):
        raise ObjectStorageProvisioningError(
            "Object-storage IAM provisioning evidence is invalid"
        )
    return {
        "schema_version": "rustfs_bucket_owner_provision.v1",
        "status": "PROVISIONED",
        "owner": spec.owner,
        "policy_name": spec.policy_name,
        "bucket_scope_count": 1,
        "root_credential_reused": False,
    }


def _head_bucket_denied(client: S3Client, bucket: str, *, owner: str) -> bool:
    try:
        client.head_bucket(Bucket=bucket)
    except Exception as exc:  # noqa: BLE001 - inspect status, never expose detail
        response = getattr(exc, "response", None)
        metadata = response.get("ResponseMetadata") if isinstance(response, Mapping) else None
        status = metadata.get("HTTPStatusCode") if isinstance(metadata, Mapping) else None
        if status == 403:
            return True
        raise ObjectStorageProvisioningError(
            f"Object-storage isolation probe failed for owner: {owner}"
        ) from None
    return False


def _checked_at(value: str | None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise ObjectStorageProvisioningError(
            "Object-storage readiness timestamp is invalid"
        ) from None
    if parsed.tzinfo is None:
        raise ObjectStorageProvisioningError(
            "Object-storage readiness timestamp is invalid"
        )
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
