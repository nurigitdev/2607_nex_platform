from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


DEFAULT_MAX_ATTEMPTS = {
    "embedding": 3,
    "reranking": 3,
    "generation": 2,
}
MAX_ATTEMPTS_ENV = {
    "embedding": "NEX_MO_EMBEDDING_MAX_ATTEMPTS",
    "reranking": "NEX_MO_RERANKER_MAX_ATTEMPTS",
    "generation": "NEX_MO_GENERATION_MAX_ATTEMPTS",
}
BASE_DELAY_ENV = "NEX_MO_RETRY_BASE_DELAY_SECONDS"
MAX_DELAY_ENV = "NEX_MO_RETRY_MAX_DELAY_SECONDS"
RETRY_AFTER_MAX_ENV = "NEX_MO_RETRY_AFTER_MAX_SECONDS"
DEFAULT_BASE_DELAY_SECONDS = 0.25
DEFAULT_MAX_DELAY_SECONDS = 2.0
DEFAULT_RETRY_AFTER_MAX_SECONDS = 5.0
GENERATION_AMBIGUOUS_FAILURE_KINDS = frozenset(
    {
        "timeout",
        "read_timeout",
        "write_timeout",
        "pool_timeout",
        "malformed_response",
    }
)


class RetryableFailureView(Protocol):
    failure_kind: str
    retryable: bool


@dataclass(frozen=True)
class ProviderRetryPolicy:
    capability: str
    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float
    retry_after_max_seconds: float

    def __post_init__(self) -> None:
        if self.capability not in DEFAULT_MAX_ATTEMPTS:
            raise ValueError(f"Unsupported provider capability: {self.capability}")
        if self.max_attempts < 1 or self.max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5.")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be non-negative.")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must be >= base_delay_seconds.")
        if self.retry_after_max_seconds < 0:
            raise ValueError("retry_after_max_seconds must be non-negative.")

    def to_safe_summary(self) -> dict[str, object]:
        return {
            "capability": self.capability,
            "max_attempts": self.max_attempts,
            "base_delay_seconds": self.base_delay_seconds,
            "max_delay_seconds": self.max_delay_seconds,
            "retry_after_max_seconds": self.retry_after_max_seconds,
            "generation_ambiguous_replay_blocked": self.capability == "generation",
        }


@dataclass(frozen=True)
class ProviderRetryDecision:
    retry: bool
    reason: str
    attempt_number: int
    max_attempts: int

    def to_safe_summary(self) -> dict[str, object]:
        return {
            "retry": self.retry,
            "reason": self.reason,
            "attempt_number": self.attempt_number,
            "max_attempts": self.max_attempts,
        }


def build_provider_retry_policy(
    capability: str,
    environ: Mapping[str, str] | None = None,
) -> ProviderRetryPolicy:
    env = environ or {}
    if capability not in DEFAULT_MAX_ATTEMPTS:
        raise ValueError(f"Unsupported provider capability: {capability}")
    return ProviderRetryPolicy(
        capability=capability,
        max_attempts=_bounded_int(
            env,
            MAX_ATTEMPTS_ENV[capability],
            DEFAULT_MAX_ATTEMPTS[capability],
            minimum=1,
            maximum=5,
        ),
        base_delay_seconds=_non_negative_float(
            env,
            BASE_DELAY_ENV,
            DEFAULT_BASE_DELAY_SECONDS,
        ),
        max_delay_seconds=_non_negative_float(
            env,
            MAX_DELAY_ENV,
            DEFAULT_MAX_DELAY_SECONDS,
        ),
        retry_after_max_seconds=_non_negative_float(
            env,
            RETRY_AFTER_MAX_ENV,
            DEFAULT_RETRY_AFTER_MAX_SECONDS,
        ),
    )


def decide_provider_retry(
    policy: ProviderRetryPolicy,
    failure: RetryableFailureView,
    *,
    attempt_number: int,
) -> ProviderRetryDecision:
    if attempt_number < 1:
        raise ValueError("attempt_number must be positive.")
    if not failure.retryable:
        reason = "failure_not_retryable"
    elif attempt_number >= policy.max_attempts:
        reason = "attempt_budget_exhausted"
    elif (
        policy.capability == "generation"
        and failure.failure_kind in GENERATION_AMBIGUOUS_FAILURE_KINDS
    ):
        reason = "generation_ambiguous_replay_blocked"
    else:
        return ProviderRetryDecision(
            retry=True,
            reason="transient_failure_within_budget",
            attempt_number=attempt_number,
            max_attempts=policy.max_attempts,
        )
    return ProviderRetryDecision(
        retry=False,
        reason=reason,
        attempt_number=attempt_number,
        max_attempts=policy.max_attempts,
    )


def _bounded_int(
    env: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = env.get(key)
    value = default if raw in {None, ""} else int(raw)
    if value < minimum or value > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}.")
    return value


def _non_negative_float(
    env: Mapping[str, str],
    key: str,
    default: float,
) -> float:
    raw = env.get(key)
    value = default if raw in {None, ""} else float(raw)
    if value < 0:
        raise ValueError(f"{key} must be non-negative.")
    return value
