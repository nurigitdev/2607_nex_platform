from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .semantic_hashes import semantic_sha256_hash_ref

DEMO_EXTERNAL_DEPENDENCY_SCHEMA_VERSION = "p8_demo_external_dependencies.v1"
DEMO_PROVIDER_CAPABILITIES = ("embedding", "reranking", "generation")


class DemoExternalDependencyError(ValueError):
    pass


def admit_demo_external_dependencies(
    provider_evidence: Mapping[str, Any],
    object_storage_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    providers = _admit_providers(provider_evidence)
    object_storage = _admit_object_storage(object_storage_evidence)
    identity = {
        "providers": providers["model_identities"],
        "object_storage": {
            "backend": "rustfs-s3-compatible",
            "bucket_count": object_storage["bucket_count"],
            "managed_tls": object_storage["managed_tls"],
        },
    }
    return {
        "schema_version": DEMO_EXTERNAL_DEPENDENCY_SCHEMA_VERSION,
        "status": "PASS",
        "actual_provider_execution": True,
        "actual_rustfs_execution": True,
        "provider": providers,
        "object_storage": object_storage,
        "dependency_identity_digest": semantic_sha256_hash_ref(identity),
        "raw_secret_values_included": False,
        "provider_endpoints_included": False,
        "private_payloads_included": False,
        "next_slice": "P8-DEMO-S10",
    }


def _admit_providers(evidence: Mapping[str, Any]) -> dict[str, Any]:
    if evidence.get("status") != "PASS":
        raise DemoExternalDependencyError("Demo live provider preflight did not pass")
    canonical = _mapping(
        evidence.get("canonical_admission"),
        "Demo canonical provider admission evidence",
    )
    if (
        canonical.get("admission_status") != "ADMITTED"
        or canonical.get("readiness_status") != "READY"
        or canonical.get("profile") != "rag"
    ):
        raise DemoExternalDependencyError(
            "Demo canonical provider admission did not pass"
        )
    raw_checks = evidence.get("checks")
    if not isinstance(raw_checks, list):
        raise DemoExternalDependencyError("Demo live provider checks are invalid")
    checks: dict[str, Mapping[str, Any]] = {}
    for item in raw_checks:
        if not isinstance(item, Mapping):
            raise DemoExternalDependencyError("Demo live provider check is invalid")
        capability = item.get("capability")
        if not isinstance(capability, str) or capability in checks:
            raise DemoExternalDependencyError("Demo provider capability coverage is invalid")
        checks[capability] = item
    if tuple(checks) != DEMO_PROVIDER_CAPABILITIES:
        raise DemoExternalDependencyError("Demo provider capability coverage drift")

    model_identities = []
    for capability in DEMO_PROVIDER_CAPABILITIES:
        check = checks[capability]
        expected_models = check.get("expected_models")
        minimum_timeout = 30 if capability == "generation" else 10
        if (
            check.get("status") != "PASS"
            or check.get("configured") is not True
            or check.get("authorized") is not True
            or check.get("model_identity_admitted") is not True
            or check.get("bounded_request_succeeded") is not True
            or check.get("timeout_policy_valid") is not True
            or check.get("response_observed") is not True
            or not isinstance(expected_models, list)
            or not expected_models
            or any(
                not isinstance(model, str) or not model or model != model.strip()
                for model in expected_models
            )
            or not _minimum_number(check.get("timeout_seconds"), minimum_timeout)
        ):
            raise DemoExternalDependencyError(
                f"Demo {capability} provider admission failed"
            )
        model_identities.append(
            {
                "capability": capability,
                "expected_models": list(expected_models),
                "request_shape": str(check.get("request_shape") or ""),
                "timeout_seconds": float(check["timeout_seconds"]),
            }
        )
    return {
        "status": "PASS",
        "capability_count": len(model_identities),
        "model_identities": model_identities,
        "responses_observed": len(model_identities),
    }


def _admit_object_storage(evidence: Mapping[str, Any]) -> dict[str, Any]:
    rustfs = _mapping(evidence.get("rustfs"), "RustFS evidence")
    posture = _mapping(rustfs.get("container_posture"), "RustFS posture")
    tls = _mapping(rustfs.get("tls_route"), "RustFS TLS evidence")
    isolation = _mapping(
        rustfs.get("cross_bucket_denied"), "RustFS tenant isolation evidence"
    )
    cleanup = _mapping(evidence.get("cleanup"), "RustFS cleanup evidence")
    adapters = _mapping(evidence.get("adapters"), "RustFS adapter evidence")
    receipts = rustfs.get("bucket_receipts")
    if evidence.get("status") != "PASS" or not isinstance(receipts, list):
        raise DemoExternalDependencyError("Demo RustFS protected acceptance did not pass")
    if len(receipts) != 2 or any(
        not isinstance(receipt, Mapping)
        or receipt.get("status") != "VERIFIED"
        or receipt.get("versioning_enabled") is not True
        or receipt.get("encryption_algorithm") != "AES256"
        for receipt in receipts
    ):
        raise DemoExternalDependencyError("Demo RustFS bucket admission failed")
    required = (
        posture.get("health_status") == "healthy",
        posture.get("non_root_user") is True,
        posture.get("durable_volume_mounted") is True,
        tls.get("status") == "PASS",
        tls.get("managed_tls_verified") is True,
        isolation.get("ae_to_cx_denied") is True,
        isolation.get("cx_to_ae_denied") is True,
        rustfs.get("restart_recovery_verified") is True,
        adapters.get("status") == "PASS",
        adapters.get("postgres_payload_bytes_written") is False,
        cleanup.get("status") == "PASS",
        cleanup.get("named_volume_removed") is True,
        _mapping(evidence.get("decision"), "RustFS decision").get(
            "production_contacted"
        )
        is False,
    )
    if not all(required):
        raise DemoExternalDependencyError("Demo RustFS runtime boundary drift")
    return {
        "status": "PASS",
        "backend": "rustfs-s3-compatible",
        "bucket_count": len(receipts),
        "managed_tls": True,
        "owner_isolation": True,
        "restart_recovery": True,
        "zero_payload_bytes_in_postgres": True,
        "runtime_residue_retained": False,
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DemoExternalDependencyError(f"{label} is invalid")
    return value


def _minimum_number(value: object, minimum: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) >= minimum
    )
