from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

NSL_V02_PUBLIC_API_ADAPTER_SCHEMA_VERSION = "ae_nsl_v02_public_api_adapter.v1"
NSL_V02_REQUIRED_PUBLIC_SYMBOLS = (
    "ApprovalRequest",
    "ApprovalEvidence",
    "ApprovalSuspensionCoordinator",
    "ApprovalResumeCoordinator",
    "ResumeToken",
    "CheckpointPort",
    "ResumeCheckpointPort",
    "IdempotencyCoordinator",
    "WriteExecutionPort",
    "PostWriteVerificationPort",
    "RuntimePolicyPort",
    "WritePolicyRequest",
    "PolicyDecision",
    "PolicyEffect",
    "RuntimePreflightValidator",
)


@dataclass(frozen=True)
class NslV02PublicApiError(Exception):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class NslV02PublicApiAdapter:
    approval_request: Any
    approval_evidence: Any
    approval_suspension_coordinator: Any
    approval_resume_coordinator: Any
    resume_token: Any
    checkpoint_port: Any
    resume_checkpoint_port: Any
    idempotency_coordinator: Any
    write_execution_port: Any
    post_write_verification_port: Any
    runtime_policy_port: Any
    write_policy_request: Any
    policy_decision: Any
    policy_effect: Any
    runtime_preflight_validator: Any
    release_admission_hash: str
    api_contract_hash: str

    @property
    def schema_version(self) -> str:
        return NSL_V02_PUBLIC_API_ADAPTER_SCHEMA_VERSION

    def symbols(self) -> dict[str, Any]:
        return dict(
            zip(
                NSL_V02_REQUIRED_PUBLIC_SYMBOLS,
                (
                    self.approval_request,
                    self.approval_evidence,
                    self.approval_suspension_coordinator,
                    self.approval_resume_coordinator,
                    self.resume_token,
                    self.checkpoint_port,
                    self.resume_checkpoint_port,
                    self.idempotency_coordinator,
                    self.write_execution_port,
                    self.post_write_verification_port,
                    self.runtime_policy_port,
                    self.write_policy_request,
                    self.policy_decision,
                    self.policy_effect,
                    self.runtime_preflight_validator,
                ),
                strict=True,
            )
        )


def load_nsl_v02_public_api(
    readiness: Mapping[str, Any],
) -> NslV02PublicApiAdapter:
    release_hash = _validate_readiness(readiness)
    imported = _import_public_api()
    imported_names = tuple(getattr(symbol, "__name__", None) for symbol in imported)
    if imported_names != NSL_V02_REQUIRED_PUBLIC_SYMBOLS:
        raise NslV02PublicApiError(
            "ae.nsl_v02.public_api_mismatch",
            "Installed NSL v0.2 public API does not match the admitted surface.",
        )
    contract_hash = semantic_sha256_hash_ref(
        {
            "schema_version": NSL_V02_PUBLIC_API_ADAPTER_SCHEMA_VERSION,
            "package_version": "0.2.0",
            "release_admission_hash": release_hash,
            "public_api_symbols": list(NSL_V02_REQUIRED_PUBLIC_SYMBOLS),
        }
    )
    return NslV02PublicApiAdapter(*imported, release_hash, contract_hash)


def _validate_readiness(readiness: Mapping[str, Any]) -> str:
    if not isinstance(readiness, Mapping):
        raise NslV02PublicApiError(
            "ae.nsl_v02.readiness_invalid",
            "NSL v0.2 installed-package readiness must be an object.",
        )
    expected = {
        "schema_version": "nsl_installed_package_readiness.v2",
        "status": "PASS",
        "lock_schema_version": "nsl_wheel_lock.v2",
        "distribution": "nex-skill-language",
        "package_version": "0.2.0",
        "runtime_import_origin": "installed_distribution",
        "public_api_complete": True,
        "in_process_profile_admissible": True,
    }
    if any(readiness.get(key) != value for key, value in expected.items()):
        raise NslV02PublicApiError(
            "ae.nsl_v02.readiness_invalid",
            "NSL v0.2 public API requires exact passing package readiness.",
        )
    if tuple(readiness.get("public_api_symbols", ())) != (
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS
    ):
        raise NslV02PublicApiError(
            "ae.nsl_v02.public_api_not_admitted",
            "NSL v0.2 readiness does not admit the required public API.",
        )
    try:
        return validate_hash_ref(readiness.get("release_admission_hash"))
    except ValueError as exc:
        raise NslV02PublicApiError(
            "ae.nsl_v02.release_identity_invalid",
            "NSL v0.2 release admission identity is invalid.",
        ) from exc


def _import_public_api() -> tuple[Any, ...]:
    from nsl.api import (  # type: ignore[import-not-found]
        ApprovalEvidence,
        ApprovalRequest,
        ApprovalResumeCoordinator,
        ApprovalSuspensionCoordinator,
        CheckpointPort,
        IdempotencyCoordinator,
        PolicyDecision,
        PolicyEffect,
        PostWriteVerificationPort,
        ResumeCheckpointPort,
        ResumeToken,
        RuntimePolicyPort,
        RuntimePreflightValidator,
        WriteExecutionPort,
        WritePolicyRequest,
    )

    return (
        ApprovalRequest,
        ApprovalEvidence,
        ApprovalSuspensionCoordinator,
        ApprovalResumeCoordinator,
        ResumeToken,
        CheckpointPort,
        ResumeCheckpointPort,
        IdempotencyCoordinator,
        WriteExecutionPort,
        PostWriteVerificationPort,
        RuntimePolicyPort,
        WritePolicyRequest,
        PolicyDecision,
        PolicyEffect,
        RuntimePreflightValidator,
    )
