from __future__ import annotations

from dataclasses import dataclass

from nex_ae_api.mo_generation_client import AeMoGenerationClientError
from nex_ae_api.semantic_candidate_evidence import SemanticCandidateEvidenceError
from nex_ae_api.semantic_candidates import SemanticCandidateStageError

_PROVIDER_FAILURES = {
    "PROVIDER_NOT_READY": (
        503,
        "MO generation route is not ready.",
    ),
    "PROVIDER_TIMEOUT": (
        504,
        "MO generation request timed out after bounded technical retry.",
    ),
    "PROVIDER_RATE_LIMIT": (
        429,
        "MO generation capacity is temporarily rate limited.",
    ),
    "PROVIDER_SERVER_ERROR": (
        502,
        "MO generation failed after bounded technical retry.",
    ),
    "PROVIDER_RESPONSE_INVALID": (
        502,
        "MO generation returned an invalid bounded response.",
    ),
}

_CANDIDATE_FAILURES = frozenset(
    {
        "CANDIDATE_JSON_INVALID",
        "CANDIDATE_SCHEMA_INVALID",
        "CANDIDATE_AUTHORITY_VIOLATION",
        "CANDIDATE_PRIVATE_DATA_VIOLATION",
        "CANDIDATE_CAPABILITY_UNKNOWN",
        "CANDIDATE_DEPENDENCY_INVALID",
        "CANDIDATE_BOUNDS_EXCEEDED",
        "CANDIDATE_PLAN_INVALID",
        "CANDIDATE_LOW_CONFIDENCE",
        "PROMPT_INJECTION_OR_POLICY_BLOCK",
        "SEMANTIC_CALIBRATION_REQUIRED",
    }
)

_REPLAN_FAILURES = frozenset(
    {
        "CANDIDATE_JSON_INVALID",
        "CANDIDATE_SCHEMA_INVALID",
        "CANDIDATE_CAPABILITY_UNKNOWN",
        "CANDIDATE_DEPENDENCY_INVALID",
        "CANDIDATE_BOUNDS_EXCEEDED",
        "CANDIDATE_PLAN_INVALID",
    }
)


@dataclass(frozen=True)
class SemanticCandidateFailureProjection:
    semantic_stage: str
    category: str
    status_code: int
    error_code: str
    detail: str
    directive: str
    retryable: bool
    retry_after_seconds: float | None = None

    def to_wire(self) -> dict[str, object]:
        projection: dict[str, object] = {
            "schema_version": "p65.semantic_candidate_failure.v1",
            "semantic_stage": self.semantic_stage,
            "category": self.category,
            "status_code": self.status_code,
            "error_code": self.error_code,
            "detail": self.detail,
            "directive": self.directive,
            "retryable": self.retryable,
            "raw_prompt_included": False,
            "provider_response_included": False,
            "provider_endpoint_included": False,
            "provider_private_data_included": False,
            "hidden_reasoning_included": False,
        }
        if self.retry_after_seconds is not None:
            projection["retry_after_seconds"] = self.retry_after_seconds
        return projection


def project_semantic_candidate_failure(
    exc: Exception,
    *,
    semantic_stage: str,
) -> SemanticCandidateFailureProjection | None:
    if isinstance(exc, AeMoGenerationClientError):
        definition = _PROVIDER_FAILURES.get(exc.error_code)
        if definition is None:
            return None
        status_code, detail = definition
        retryable = bool(exc.retryable)
        return SemanticCandidateFailureProjection(
            semantic_stage=semantic_stage,
            category="PROVIDER",
            status_code=status_code,
            error_code=exc.error_code,
            detail=detail,
            directive="RETRY_PROVIDER" if retryable else "BLOCKED",
            retryable=retryable,
            retry_after_seconds=(
                _bounded_retry_after(exc.retry_after_seconds)
                if exc.error_code == "PROVIDER_RATE_LIMIT"
                else None
            ),
        )
    if isinstance(exc, SemanticCandidateStageError):
        if exc.error_code not in _CANDIDATE_FAILURES:
            return None
        if exc.error_code == "CANDIDATE_LOW_CONFIDENCE":
            directive = {
                "INTENT": "CLARIFICATION_REQUIRED",
                "CONTEXT": "CONTEXT_REFRESH_REQUIRED",
                "PLAN": "REPLAN_REQUIRED",
            }.get(semantic_stage, "BLOCKED")
        else:
            directive = (
                "REPLAN_REQUIRED" if exc.error_code in _REPLAN_FAILURES else "BLOCKED"
            )
        return SemanticCandidateFailureProjection(
            semantic_stage=semantic_stage,
            category="CANDIDATE",
            status_code=(
                503 if exc.error_code == "SEMANTIC_CALIBRATION_REQUIRED" else 422
            ),
            error_code=exc.error_code,
            detail="Generated semantic candidate failed deterministic admission.",
            directive=directive,
            retryable=False,
        )
    if isinstance(exc, SemanticCandidateEvidenceError):
        return SemanticCandidateFailureProjection(
            semantic_stage=semantic_stage,
            category="PERSISTENCE",
            status_code=503 if exc.retryable else 409,
            error_code="SEMANTIC_ADMISSION_FAILED",
            detail="Semantic candidate evidence could not be admitted.",
            directive="RETRY_PERSISTENCE" if exc.retryable else "BLOCKED",
            retryable=bool(exc.retryable),
        )
    return None


def _bounded_retry_after(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    selected = float(value)
    return selected if 0 <= selected <= 300 else None
