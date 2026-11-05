from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import ceil
from threading import Lock
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_shadow_runtime import (
    AnswerSupportShadowRuntime,
)

SHADOW_CANARY_POLICY_SCHEMA_VERSION = "cx_answer_support_shadow_canary_policy.v1"
SHADOW_CANARY_APPROVAL_SCHEMA_VERSION = (
    "cx_answer_support_shadow_canary_operator_approval.v1"
)
SHADOW_CANARY_SNAPSHOT_SCHEMA_VERSION = (
    "cx_answer_support_shadow_canary_snapshot.v1"
)
SHADOW_CANARY_APPROVAL_SCOPE = "SHADOW_CANARY_EXECUTION_ONLY"

_POLICY_FIELDS = {
    "policy_schema_version",
    "policy_id",
    "status",
    "maximum_provider_calls",
    "maximum_concurrency",
    "maximum_provider_failures",
    "maximum_error_rate",
    "maximum_single_latency_ms",
    "maximum_p95_latency_ms",
    "maximum_total_tokens",
    "disagreement_is_observation_only",
    "fallback_policy",
    "user_visible",
    "runtime_activation_permitted",
    "production_cutover_permitted",
}
_APPROVAL_FIELDS = {
    "approval_schema_version",
    "status",
    "scope",
    "operator_id",
    "approved_at",
    "expires_at",
    "policy_hash",
    "manifest_hash",
    "profile_hash",
    "provider_binding_hash",
    "maximum_provider_calls",
    "runtime_activation_approved",
    "production_cutover_approved",
    "approval_hash",
}
_IMMEDIATE_STOP_ERRORS = frozenset(
    {
        "cx.answer_support_shadow.configuration_invalid",
        "cx.answer_support_shadow.contract_invalid",
        "cx.answer_support_shadow.permission_drift",
        "cx.answer_support_shadow.provider_binding_drift",
        "cx.answer_support_shadow.provider_response_invalid",
    }
)


class AnswerSupportShadowCanaryError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_shadow_canary_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the bounded, shadow-only canary policy and attach its hash."""
    normalized = dict(policy)
    supplied_hash = normalized.pop("policy_hash", None)
    if set(normalized) != _POLICY_FIELDS:
        raise _error("policy_fields")
    if (
        normalized.get("policy_schema_version") != SHADOW_CANARY_POLICY_SCHEMA_VERSION
        or normalized.get("status") != "FROZEN_LIMITED_LIVE_CANARY"
        or normalized.get("maximum_concurrency") != 1
        or normalized.get("maximum_provider_failures") != 0
        or normalized.get("disagreement_is_observation_only") is not True
        or normalized.get("fallback_policy")
        != "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY"
        or normalized.get("user_visible") is not False
        or normalized.get("runtime_activation_permitted") is not False
        or normalized.get("production_cutover_permitted") is not False
    ):
        raise _error("policy_boundary")
    _required_text(normalized.get("policy_id"), "policy_id")
    _positive_int(normalized.get("maximum_provider_calls"), "maximum_provider_calls")
    _positive_int(
        normalized.get("maximum_single_latency_ms"), "maximum_single_latency_ms"
    )
    _positive_int(
        normalized.get("maximum_p95_latency_ms"), "maximum_p95_latency_ms"
    )
    _positive_int(normalized.get("maximum_total_tokens"), "maximum_total_tokens")
    failure_rate = normalized.get("maximum_error_rate")
    if isinstance(failure_rate, bool) or not isinstance(failure_rate, (int, float)):
        raise _error("policy_error_rate")
    if float(failure_rate) != 0.0:
        raise _error("policy_error_rate")
    normalized["maximum_error_rate"] = float(failure_rate)
    calculated_hash = semantic_sha256_hash_ref(normalized)
    if supplied_hash is not None and validate_hash_ref(supplied_hash) != calculated_hash:
        raise _error("policy_integrity")
    normalized["policy_hash"] = calculated_hash
    return normalized


def build_shadow_canary_operator_approval(
    *,
    operator_id: str,
    policy: Mapping[str, Any],
    manifest_hash: str,
    profile_hash: str,
    provider_binding: Mapping[str, Any],
    approved_at: str,
    expires_at: str,
) -> dict[str, Any]:
    """Build an integrity-bound approval that permits only the bounded canary."""
    normalized_policy = validate_shadow_canary_policy(policy)
    approval = {
        "approval_schema_version": SHADOW_CANARY_APPROVAL_SCHEMA_VERSION,
        "status": "APPROVED",
        "scope": SHADOW_CANARY_APPROVAL_SCOPE,
        "operator_id": _required_text(operator_id, "operator_id"),
        "approved_at": _timestamp(approved_at, "approved_at").isoformat().replace(
            "+00:00", "Z"
        ),
        "expires_at": _timestamp(expires_at, "expires_at").isoformat().replace(
            "+00:00", "Z"
        ),
        "policy_hash": normalized_policy["policy_hash"],
        "manifest_hash": validate_hash_ref(manifest_hash),
        "profile_hash": validate_hash_ref(profile_hash),
        "provider_binding_hash": semantic_sha256_hash_ref(dict(provider_binding)),
        "maximum_provider_calls": normalized_policy["maximum_provider_calls"],
        "runtime_activation_approved": False,
        "production_cutover_approved": False,
    }
    if _timestamp(approval["expires_at"], "expires_at") <= _timestamp(
        approval["approved_at"], "approved_at"
    ):
        raise _error("approval_window")
    approval["approval_hash"] = semantic_sha256_hash_ref(approval)
    return approval


def validate_shadow_canary_operator_approval(
    approval: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    manifest_hash: str,
    profile_hash: str,
    provider_binding: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Admit an unexpired approval whose complete execution scope is exact."""
    if set(approval) != _APPROVAL_FIELDS:
        raise _error("approval_fields")
    normalized = dict(approval)
    approval_hash = validate_hash_ref(normalized.pop("approval_hash", None))
    if semantic_sha256_hash_ref(normalized) != approval_hash:
        raise _error("approval_integrity")
    normalized_policy = validate_shadow_canary_policy(policy)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if (
        normalized.get("approval_schema_version")
        != SHADOW_CANARY_APPROVAL_SCHEMA_VERSION
        or normalized.get("status") != "APPROVED"
        or normalized.get("scope") != SHADOW_CANARY_APPROVAL_SCOPE
        or normalized.get("policy_hash") != normalized_policy["policy_hash"]
        or normalized.get("manifest_hash") != validate_hash_ref(manifest_hash)
        or normalized.get("profile_hash") != validate_hash_ref(profile_hash)
        or normalized.get("provider_binding_hash")
        != semantic_sha256_hash_ref(dict(provider_binding))
        or normalized.get("maximum_provider_calls")
        != normalized_policy["maximum_provider_calls"]
        or normalized.get("runtime_activation_approved") is not False
        or normalized.get("production_cutover_approved") is not False
    ):
        raise _error("approval_scope")
    _required_text(normalized.get("operator_id"), "operator_id")
    approved_at = _timestamp(normalized.get("approved_at"), "approved_at")
    expires_at = _timestamp(normalized.get("expires_at"), "expires_at")
    if not approved_at <= current < expires_at:
        raise _error("approval_expired")
    normalized["approval_hash"] = approval_hash
    return normalized


@dataclass
class AnswerSupportShadowCanary:
    """Bound a shadow evaluator to an approved live-call and stop-condition budget."""

    runtime: AnswerSupportShadowRuntime
    policy: Mapping[str, Any]
    approval: Mapping[str, Any]
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _provider_calls: int = field(default=0, init=False)
    _observed_count: int = field(default=0, init=False)
    _failed_count: int = field(default=0, init=False)
    _disagreement_count: int = field(default=0, init=False)
    _total_tokens: int = field(default=0, init=False)
    _latencies_ms: list[float] = field(default_factory=list, init=False, repr=False)
    _terminal_reason: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        profile = self.runtime.readiness_manifest.get("candidate_profile")
        if not isinstance(profile, Mapping):
            raise _error("runtime_profile")
        normalized_policy = validate_shadow_canary_policy(self.policy)
        normalized_approval = validate_shadow_canary_operator_approval(
            self.approval,
            policy=normalized_policy,
            manifest_hash=validate_hash_ref(
                self.runtime.readiness_manifest.get("manifest_hash")
            ),
            profile_hash=validate_hash_ref(profile.get("profile_hash")),
            provider_binding=_mapping(profile.get("provider_binding"), "provider_binding"),
            now=self.clock(),
        )
        self.policy = normalized_policy
        self.approval = normalized_approval

    def observe(
        self,
        *,
        query_text: str,
        evidence_items: Sequence[Mapping[str, Any]],
        primary_package: Mapping[str, Any],
        access_context: CxAccessContext,
    ) -> dict[str, Any]:
        with self._lock:
            if self._terminal_reason is not None:
                return self._not_executed("CANARY_HALTED")
            if self._provider_calls >= self.policy["maximum_provider_calls"]:
                return self._not_executed("CANARY_BUDGET_EXHAUSTED")
            outcome = self.runtime.observe(
                query_text=query_text,
                evidence_items=evidence_items,
                primary_package=primary_package,
                access_context=access_context,
            )
            self._record(outcome)
            return {**outcome, "canary_snapshot": self.snapshot()}

    def snapshot(self) -> dict[str, Any]:
        maximum_calls = int(self.policy["maximum_provider_calls"])
        error_rate = (
            self._failed_count / self._provider_calls
            if self._provider_calls
            else 0.0
        )
        status = "HALTED" if self._terminal_reason else "RUNNING"
        if self._provider_calls == maximum_calls and self._terminal_reason is None:
            status = "COMPLETED"
        snapshot = {
            "snapshot_schema_version": SHADOW_CANARY_SNAPSHOT_SCHEMA_VERSION,
            "status": status,
            "terminal_reason": self._terminal_reason,
            "policy_hash": self.policy["policy_hash"],
            "approval_hash": self.approval["approval_hash"],
            "provider_calls": self._provider_calls,
            "maximum_provider_calls": maximum_calls,
            "observed_count": self._observed_count,
            "failed_count": self._failed_count,
            "error_rate": round(error_rate, 12),
            "disagreement_count": self._disagreement_count,
            "disagreement_rate": round(
                self._disagreement_count / self._observed_count
                if self._observed_count
                else 0.0,
                12,
            ),
            "latency_sample_count": len(self._latencies_ms),
            "p95_latency_ms": _percentile_95(self._latencies_ms),
            "maximum_latency_ms": max(self._latencies_ms, default=0),
            "total_tokens": self._total_tokens,
            "user_visible": False,
            "runtime_activation_permitted": False,
            "production_cutover_permitted": False,
        }
        snapshot["snapshot_hash"] = semantic_sha256_hash_ref(snapshot)
        return snapshot

    def _record(self, outcome: Mapping[str, Any]) -> None:
        latency_missing = False
        if outcome.get("provider_called") is True:
            self._provider_calls += 1
            elapsed = outcome.get("elapsed_ms")
            if (
                isinstance(elapsed, (int, float))
                and not isinstance(elapsed, bool)
                and float(elapsed) >= 0.0
            ):
                self._latencies_ms.append(float(elapsed))
            else:
                latency_missing = True
            usage = outcome.get("usage")
            if isinstance(usage, Mapping):
                total = usage.get("total_tokens")
                if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
                    self._total_tokens += total
        if outcome.get("status") == "OBSERVED":
            self._observed_count += 1
            if outcome.get("primary_shadow_agree") is False:
                self._disagreement_count += 1
        elif outcome.get("status") == "FAILED":
            self._failed_count += 1

        error_code = outcome.get("error_code")
        if latency_missing:
            self._terminal_reason = "LATENCY_TELEMETRY_MISSING"
        elif error_code in _IMMEDIATE_STOP_ERRORS:
            self._terminal_reason = str(error_code)
        elif self._failed_count > int(self.policy["maximum_provider_failures"]):
            self._terminal_reason = "PROVIDER_FAILURE_BUDGET_EXCEEDED"
        elif self._latencies_ms and self._latencies_ms[-1] > int(
            self.policy["maximum_single_latency_ms"]
        ):
            self._terminal_reason = "SINGLE_LATENCY_BUDGET_EXCEEDED"
        elif self._total_tokens > int(self.policy["maximum_total_tokens"]):
            self._terminal_reason = "TOKEN_BUDGET_EXCEEDED"
        elif (
            self._provider_calls == int(self.policy["maximum_provider_calls"])
            and _percentile_95(self._latencies_ms)
            > int(self.policy["maximum_p95_latency_ms"])
        ):
            self._terminal_reason = "P95_LATENCY_BUDGET_EXCEEDED"

    def _not_executed(self, reason: str) -> dict[str, Any]:
        return {
            "outcome_schema_version": "cx_answer_support_shadow_outcome.v1",
            "mode": "SHADOW_CANARY",
            "status": "SKIPPED",
            "shadow_decision": "NOT_EVALUATED",
            "skip_reason": reason,
            "provider_called": False,
            "user_visible": False,
            "primary_decision_mutated": False,
            "runtime_activation_permitted": False,
            "production_cutover_permitted": False,
            "canary_snapshot": self.snapshot(),
        }


def _percentile_95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[max(0, ceil(len(ordered) * 0.95) - 1)], 3)


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise _error(f"{name}_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise _error(f"{name}_invalid") from exc
    return parsed.astimezone(UTC)


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _error(f"{name}_invalid")
    return value


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{name}_invalid")
    return value.strip()


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(f"{name}_invalid")
    return value


def _error(code: str) -> AnswerSupportShadowCanaryError:
    return AnswerSupportShadowCanaryError(
        f"cx.answer_support_shadow_canary.{code}",
        "The answer-support shadow canary admission is invalid.",
    )
