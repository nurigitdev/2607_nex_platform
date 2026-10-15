from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)

from nex_ae_api.nsl_read_backends import (
    SqlAlchemyNSLBackendRunRepository,
    validate_nsl_backend_run,
)
from nex_ae_api.nsl_step_executions import (
    SqlAlchemyNSLStepExecutionRepository,
    validate_nsl_step_execution_binding,
)
from nex_ae_api.skill_artifacts import validate_verified_skill_artifact

NSL_RESULT_SUMMARY_SCHEMA_VERSION = "1.0"
NSL_READ_RESULT_CONTRACT_REF = "contract://nex/ae/nsl-read-result/v1"
_TERMINAL_RUNTIME_STATUSES = frozenset(
    {
        "COMPLETED",
        "FAILED",
        "TOOL_ERROR",
        "VALIDATION_ERROR",
        "LIMIT_EXCEEDED",
        "CANCELLED",
    }
)
_OUTCOME_BY_RUNTIME_STATUS = {
    "COMPLETED": "SUCCEEDED",
    "FAILED": "FAILED",
    "TOOL_ERROR": "FAILED",
    "VALIDATION_ERROR": "BLOCKED",
    "LIMIT_EXCEEDED": "FAILED",
    "CANCELLED": "CANCELLED",
}
_FAILURE_RUNTIME_STATUSES = frozenset(
    {"FAILED", "TOOL_ERROR", "VALIDATION_ERROR", "LIMIT_EXCEEDED"}
)


@dataclass(frozen=True)
class NSLResultIntegrationError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class StepExecutionOutcome:
    state: Literal["SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"]
    result_contract_ref: str
    result_payload: Mapping[str, Any]
    artifact_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    error_ref: str | None
    business_operation_id: str
    started_at: str
    completed_at: str
    external_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class NSLResultIntegration:
    summary_ref: str
    summary_hash: str
    summary: dict[str, Any]
    binding: dict[str, Any]
    outcome: StepExecutionOutcome


def build_nsl_result_summary(
    *,
    binding: Mapping[str, Any],
    artifact: Mapping[str, Any],
    backend_run: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_binding = validate_nsl_step_execution_binding(binding)
    normalized_artifact = validate_verified_skill_artifact(artifact)
    normalized_run = validate_nsl_backend_run(backend_run)
    _require_lineage(normalized_binding, normalized_artifact, normalized_run)
    if (
        normalized_run["isolation_status"] != "COMPLETED"
        or normalized_run["runtime_result_envelope"] is None
    ):
        raise _invalid(
            "An isolated backend failure cannot produce an NSLResultSummary."
        )
    envelope = normalized_run["runtime_result_envelope"]
    runtime = envelope["runtime_result"]
    status = runtime["status"]
    if status not in _TERMINAL_RUNTIME_STATUSES:
        raise _invalid("NSLResultSummary requires a terminal runtime status.")
    error_code, error_ref = _bounded_error(
        runtime.get("error"),
        runtime_status=status,
        nsl_execution_id=normalized_binding["nsl_execution_id"],
        attempt_no=normalized_run["attempt_no"],
    )
    if status == "COMPLETED" and (error_code is not None or error_ref is not None):
        raise _invalid("Completed NSL result cannot carry terminal error evidence.")
    result_ref = None
    result_hash = None
    if status == "COMPLETED":
        result_ref = _runtime_result_ref(
            normalized_binding["nsl_execution_id"], normalized_run["attempt_no"]
        )
        result_hash = semantic_sha256_hash_ref(envelope)
    summary = {
        "schema_version": NSL_RESULT_SUMMARY_SCHEMA_VERSION,
        "nsl_execution_id": normalized_binding["nsl_execution_id"],
        "business_operation_id": normalized_binding["business_operation_id"],
        "skill_id": normalized_artifact["skill_id"],
        "skill_version": normalized_artifact["skill_version"],
        "skill_semantic_hash": normalized_artifact["skill_semantic_hash"],
        "verified_artifact_ref": normalized_artifact["artifact_ref"],
        "package_hash": normalized_artifact["package_hash"],
        "trust_evidence_ref": normalized_artifact["trust_evidence"]["evidence_ref"],
        "execution_status": status,
        "completeness": runtime["completeness"],
        "result_ref": result_ref,
        "result_hash": result_hash,
        "evidence_refs": _refs(
            [
                *normalized_run["evidence_refs"],
                normalized_artifact["trust_evidence"]["evidence_ref"],
            ],
            128,
        ),
        "resource_summary": dict(runtime["resources"]),
        "error_code": error_code,
        "error_ref": error_ref,
        "pre_write_eligibility": None,
        "commit_state": None,
        "verification_status": None,
        "retry_safety": None,
        "completed_at": normalized_run["completed_at"],
    }
    return validate_nsl_result_summary(summary)


def validate_nsl_result_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping("NSLResultSummary", value)
    fields = {
        "schema_version",
        "nsl_execution_id",
        "business_operation_id",
        "skill_id",
        "skill_version",
        "skill_semantic_hash",
        "verified_artifact_ref",
        "package_hash",
        "trust_evidence_ref",
        "execution_status",
        "completeness",
        "result_ref",
        "result_hash",
        "evidence_refs",
        "resource_summary",
        "error_code",
        "error_ref",
        "pre_write_eligibility",
        "commit_state",
        "verification_status",
        "retry_safety",
        "completed_at",
    }
    if set(summary) != fields or summary.get("schema_version") != "1.0":
        raise _invalid("NSLResultSummary fields or schema version are invalid.")
    nsl_id = _uuid("nsl_execution_id", summary["nsl_execution_id"])
    business_id = _uuid("business_operation_id", summary["business_operation_id"])
    if nsl_id == business_id:
        raise _invalid("NSL and business operation identities must remain distinct.")
    for field in ("skill_id", "skill_version"):
        _text(field, summary[field], 256)
    for field in ("skill_semantic_hash", "package_hash"):
        _hash(field, summary[field])
    for field in ("verified_artifact_ref", "trust_evidence_ref"):
        _ref(field, summary[field])
    status = summary["execution_status"]
    if status not in _TERMINAL_RUNTIME_STATUSES:
        raise _invalid("NSLResultSummary execution status is invalid.")
    if summary["completeness"] not in {"COMPLETE", "PARTIAL", "UNKNOWN"}:
        raise _invalid("NSLResultSummary completeness is invalid.")
    refs = _refs(summary["evidence_refs"], 128)
    if refs != summary["evidence_refs"]:
        raise _invalid("NSLResultSummary evidence refs must be canonical.")
    resources = summary["resource_summary"]
    resource_fields = {
        "tool_calls",
        "loop_iterations",
        "emitted_rows",
        "max_collection_size_seen",
    }
    if not isinstance(resources, Mapping) or set(resources) != resource_fields:
        raise _invalid("NSLResultSummary resource summary is invalid.")
    for field in resource_fields:
        _bounded_int(field, resources[field], 0, 2_147_483_647)
    for field in (
        "pre_write_eligibility",
        "commit_state",
        "verification_status",
        "retry_safety",
    ):
        if summary[field] is not None:
            raise _invalid("READ summary cannot carry WRITE lifecycle fields.")
    _timestamp("completed_at", summary["completed_at"])
    error_code = _optional_text("error_code", summary["error_code"], 256)
    error_ref = _optional_ref("error_ref", summary["error_ref"])
    if status == "COMPLETED":
        _ref("result_ref", summary["result_ref"])
        _hash("result_hash", summary["result_hash"])
        if error_code is not None or error_ref is not None:
            raise _invalid("Completed NSLResultSummary cannot carry an error.")
    else:
        if summary["result_ref"] is not None or summary["result_hash"] is not None:
            raise _invalid("Unsuccessful NSLResultSummary cannot carry a result.")
        if status in _FAILURE_RUNTIME_STATUSES and (
            error_code is None or error_ref is None
        ):
            raise _invalid("Failed NSLResultSummary requires bounded error evidence.")
    return summary


def build_step_execution_outcome(
    *,
    summary: Mapping[str, Any],
    binding: Mapping[str, Any],
    result_contract_ref: str = NSL_READ_RESULT_CONTRACT_REF,
) -> StepExecutionOutcome:
    normalized_summary = validate_nsl_result_summary(summary)
    normalized_binding = validate_nsl_step_execution_binding(binding)
    if (
        normalized_binding["nsl_execution_id"] != normalized_summary["nsl_execution_id"]
        or normalized_binding["business_operation_id"]
        != normalized_summary["business_operation_id"]
        or normalized_binding["skill_id"] != normalized_summary["skill_id"]
        or normalized_binding["exact_skill_version"]
        != normalized_summary["skill_version"]
        or normalized_binding["skill_semantic_hash"]
        != normalized_summary["skill_semantic_hash"]
    ):
        raise _invalid("StepExecutionOutcome summary and binding lineage differ.")
    summary_ref = _summary_ref(normalized_summary["nsl_execution_id"])
    summary_hash = semantic_sha256_hash_ref(normalized_summary)
    if normalized_binding["state"] in {
        "SUCCEEDED",
        "FAILED",
        "BLOCKED",
        "CANCELLED",
    } and (
        normalized_binding["result_summary_ref"] != summary_ref
        or normalized_binding["result_summary_hash"] != summary_hash
        or normalized_binding["completed_at"] != normalized_summary["completed_at"]
    ):
        raise _invalid("Terminal binding does not match NSLResultSummary evidence.")
    started_at = normalized_binding["invocation_started_at"]
    if started_at is None:
        raise _invalid("StepExecutionOutcome requires invocation start evidence.")
    state = _OUTCOME_BY_RUNTIME_STATUS[normalized_summary["execution_status"]]
    return StepExecutionOutcome(
        state=state,  # type: ignore[arg-type]
        result_contract_ref=_ref("result_contract_ref", result_contract_ref),
        result_payload={
            "nsl_result_summary_ref": summary_ref,
            "nsl_execution_id": normalized_summary["nsl_execution_id"],
            "execution_status": normalized_summary["execution_status"],
        },
        artifact_refs=(normalized_summary["verified_artifact_ref"],),
        evidence_refs=tuple(normalized_summary["evidence_refs"]),
        error_ref=normalized_summary["error_ref"],
        business_operation_id=normalized_summary["business_operation_id"],
        started_at=started_at,
        completed_at=normalized_summary["completed_at"],
    )


def to_p5_executor_outcome(outcome: StepExecutionOutcome) -> object:
    from nex_ae_api.step_executors import P5ExecutorOutcome

    return P5ExecutorOutcome(
        state=outcome.state,
        result_contract_ref=outcome.result_contract_ref,
        result_payload=outcome.result_payload,
        external_refs=outcome.external_refs,
        artifact_refs=outcome.artifact_refs,
        evidence_refs=outcome.evidence_refs,
        error_ref=outcome.error_ref,
        business_operation_id=outcome.business_operation_id,
        started_at=outcome.started_at,
        completed_at=outcome.completed_at,
    )


class NSLResultIntegrationService:
    def __init__(
        self,
        *,
        bindings: SqlAlchemyNSLStepExecutionRepository,
        artifacts: object,
        runs: SqlAlchemyNSLBackendRunRepository,
    ) -> None:
        if not all(
            callable(getattr(bindings, method, None))
            for method in ("get", "mark_result_terminal")
        ):
            raise _dependency("NSL result integration requires a binding repository.")
        if not callable(getattr(artifacts, "get", None)):
            raise _dependency("NSL result integration requires an artifact repository.")
        if not callable(getattr(runs, "get", None)):
            raise _dependency(
                "NSL result integration requires a backend-run repository."
            )
        self._bindings = bindings
        self._artifacts = artifacts
        self._runs = runs

    def finalize_bound(
        self,
        *,
        tenant_id: str,
        executable_step_id: str,
        attempt_no: int,
        result_contract_ref: str = NSL_READ_RESULT_CONTRACT_REF,
    ) -> NSLResultIntegration:
        bundle = self._bindings.get(
            tenant_id=tenant_id, executable_step_id=executable_step_id
        )
        if bundle is None:
            raise NSLResultIntegrationError(
                "ae.nsl_result_binding_not_found",
                "NSL result integration requires a durable binding.",
            )
        binding = bundle["binding"]
        artifact = self._artifacts.get(
            tenant_id=tenant_id, artifact_ref=binding["verified_artifact_ref"]
        )
        if artifact is None:
            raise NSLResultIntegrationError(
                "ae.nsl_result_artifact_not_found",
                "NSL result integration requires its verified artifact.",
            )
        run = self._runs.get(
            tenant_id=tenant_id,
            nsl_execution_id=binding["nsl_execution_id"],
            attempt_no=attempt_no,
        )
        if run is None:
            raise NSLResultIntegrationError(
                "ae.nsl_result_backend_run_not_found",
                "NSL result integration requires terminal backend evidence.",
            )
        summary = build_nsl_result_summary(
            binding=binding, artifact=artifact, backend_run=run
        )
        summary_ref = _summary_ref(summary["nsl_execution_id"])
        summary_hash = semantic_sha256_hash_ref(summary)
        terminal = self._bindings.mark_result_terminal(
            tenant_id=tenant_id,
            executable_step_id=executable_step_id,
            state=_OUTCOME_BY_RUNTIME_STATUS[summary["execution_status"]],
            result_summary_ref=summary_ref,
            result_summary_hash=summary_hash,
            completed_at=summary["completed_at"],
        )["binding"]
        outcome = build_step_execution_outcome(
            summary=summary,
            binding=terminal,
            result_contract_ref=result_contract_ref,
        )
        return NSLResultIntegration(
            summary_ref=summary_ref,
            summary_hash=summary_hash,
            summary=summary,
            binding=terminal,
            outcome=outcome,
        )


def _require_lineage(
    binding: Mapping[str, Any],
    artifact: Mapping[str, Any],
    backend_run: Mapping[str, Any],
) -> None:
    pairs = (
        (binding["tenant_id"], backend_run["tenant_id"]),
        (binding["executable_step_id"], backend_run["executable_step_id"]),
        (binding["nsl_execution_id"], backend_run["nsl_execution_id"]),
        (binding["business_operation_id"], backend_run["business_operation_id"]),
        (binding["skill_id"], artifact["skill_id"]),
        (binding["exact_skill_version"], artifact["skill_version"]),
        (binding["skill_semantic_hash"], artifact["skill_semantic_hash"]),
        (binding["verified_artifact_ref"], artifact["artifact_ref"]),
        (binding["verified_artifact_hash"], artifact["artifact_hash"]),
    )
    if any(left != right for left, right in pairs):
        raise _invalid("NSL result lineage does not match its durable authorities.")


def _bounded_error(
    value: object,
    *,
    runtime_status: str,
    nsl_execution_id: str,
    attempt_no: int,
) -> tuple[str | None, str | None]:
    if runtime_status == "COMPLETED":
        if value is not None:
            return "NSL_COMPLETED_WITH_ERROR", _runtime_error_ref(
                nsl_execution_id, attempt_no
            )
        return None, None
    code = None
    if isinstance(value, Mapping):
        candidate = value.get("code")
        if isinstance(candidate, str) and candidate.strip():
            code = candidate.strip()[:256]
    if runtime_status in _FAILURE_RUNTIME_STATUSES and code is None:
        code = f"NSL_{runtime_status}"
    if code is None:
        return None, None
    return code, _runtime_error_ref(nsl_execution_id, attempt_no)


def _summary_ref(nsl_execution_id: str) -> str:
    return f"AE:NSL_RESULT_SUMMARY:{nsl_execution_id}"


def _runtime_result_ref(nsl_execution_id: str, attempt_no: int) -> str:
    return f"AE:NSL_RUNTIME_RESULT:{nsl_execution_id}:{attempt_no}"


def _runtime_error_ref(nsl_execution_id: str, attempt_no: int) -> str:
    return f"AE:NSL_RUNTIME_ERROR:{nsl_execution_id}:{attempt_no}"


def _mapping(name: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{name} must be an object.")
    try:
        return json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{name} must be canonical JSON.") from exc


def _refs(value: object, maximum: int) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("Evidence refs must be an array.")
    refs = [_ref("evidence_ref", item) for item in value]
    if len(refs) > maximum or len(set(refs)) != len(refs):
        raise _invalid("Evidence refs must be bounded and unique.")
    return sorted(refs)


def _uuid(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be a UUID.")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID.") from exc
    if str(parsed) != value:
        raise _invalid(f"{field} must be a canonical UUID.")
    return value


def _hash(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a lowercase SHA-256 reference.") from exc


def _ref(field: str, value: object) -> str:
    return _text(field, value, 512)


def _optional_ref(field: str, value: object) -> str | None:
    return None if value is None else _ref(field, value)


def _text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _invalid(f"{field} must be a non-empty bounded string.")
    return value.strip()


def _optional_text(field: str, value: object, maximum: int) -> str | None:
    return None if value is None else _text(field, value, maximum)


def _timestamp(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an RFC3339 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC3339 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(f"{field} must include a timezone.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _bounded_int(field: str, value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _invalid(f"{field} must be between {minimum} and {maximum}.")
    return value


def _invalid(detail: str) -> NSLResultIntegrationError:
    return NSLResultIntegrationError("ae.nsl_result_invalid", detail)


def _dependency(detail: str) -> NSLResultIntegrationError:
    return NSLResultIntegrationError("ae.nsl_result_unavailable", detail)
