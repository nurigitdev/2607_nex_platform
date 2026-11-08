from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_canonical_profile import (
    FEATURE_FIELDS,
    FEATURE_WEIGHTS,
)
from nex_cx.retrieval_answer_support_collection import (
    build_answer_support_generation_payload,
    normalize_answer_support_generation_result,
    validate_answer_support_request_profile,
)
from nex_cx.retrieval_answer_support_runtime_readiness import (
    ACTIVATION_STATUS,
    READINESS_DECISION,
    RUNTIME_PROFILE_SCHEMA_VERSION,
    RUNTIME_READINESS_MANIFEST_SCHEMA_VERSION,
)
from nex_cx.retrieval_answer_support_signal import (
    build_answer_support_package_features,
    build_answer_support_request,
    validate_answer_support_signal_design,
)


ANSWER_SUPPORT_SHADOW_OUTCOME_SCHEMA_VERSION = (
    "cx_answer_support_shadow_outcome.v1"
)
ANSWER_SUPPORT_SHADOW_POLICY_ID = "cx_answer_support_shadow_runtime_v1"
SHADOW_ELIGIBLE_PURPOSES = frozenset({"grounded_answer", "document_generation"})


class AnswerSupportGenerationClient(Protocol):
    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...


class AnswerSupportShadowOutcomeSink(Protocol):
    def record(self, outcome: Mapping[str, Any]) -> None: ...


class AnswerSupportShadowRuntimeError(ValueError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        provider_called: bool = False,
    ) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.provider_called = provider_called


@dataclass(frozen=True)
class AnswerSupportShadowRuntime:
    readiness_manifest: Mapping[str, Any]
    signal_design: Mapping[str, Any]
    request_profile: Mapping[str, Any]
    generation_client: AnswerSupportGenerationClient
    outcome_sink: AnswerSupportShadowOutcomeSink
    runtime_provider_binding: Mapping[str, Any] | None = None

    def observe(
        self,
        *,
        query_text: str,
        evidence_items: Sequence[Mapping[str, Any]],
        primary_package: Mapping[str, Any],
        access_context: CxAccessContext,
    ) -> dict[str, Any]:
        """Evaluate one package without changing or blocking its primary decision."""
        started = perf_counter()
        package_id = _optional_text(primary_package.get("retrieval_package_id"))
        primary_status = _optional_text(primary_package.get("status"))
        purpose = _optional_text(primary_package.get("purpose"))
        try:
            configuration = validate_answer_support_shadow_configuration(
                self.readiness_manifest,
                signal_design=self.signal_design,
                request_profile=self.request_profile,
            )
            outcome = self._evaluate(
                configuration=configuration,
                query_text=query_text,
                evidence_items=evidence_items,
                package_id=package_id,
                primary_status=primary_status,
                purpose=purpose,
                access_context=access_context,
                started=started,
            )
        except Exception as exc:
            outcome = _failure_outcome(
                exc,
                package_id=package_id,
                primary_status=primary_status,
                purpose=purpose,
                request_id=access_context.request_id,
                trace_id=access_context.trace_id,
                elapsed_ms=_elapsed_ms(started),
            )
        try:
            self.outcome_sink.record(outcome)
        except Exception:
            # Shadow telemetry must never change the primary retrieval result.
            pass
        return outcome

    def _evaluate(
        self,
        *,
        configuration: Mapping[str, Any],
        query_text: str,
        evidence_items: Sequence[Mapping[str, Any]],
        package_id: str | None,
        primary_status: str | None,
        purpose: str | None,
        access_context: CxAccessContext,
        started: float,
    ) -> dict[str, Any]:
        profile = configuration["candidate_profile"]
        expected_binding = _runtime_provider_binding(
            profile["provider_binding"],
            self.runtime_provider_binding,
        )
        base = _outcome_base(
            package_id=package_id,
            primary_status=primary_status,
            purpose=purpose,
            request_id=access_context.request_id,
            trace_id=access_context.trace_id,
            profile=profile,
        )
        if purpose not in SHADOW_ELIGIBLE_PURPOSES:
            return _finish_outcome(
                {
                    **base,
                    "status": "SKIPPED",
                    "shadow_decision": "NOT_EVALUATED",
                    "skip_reason": "PURPOSE_NOT_ELIGIBLE",
                    "provider_called": False,
                    "elapsed_ms": _elapsed_ms(started),
                }
            )
        candidates = _private_candidates(evidence_items)
        if not candidates:
            return _finish_outcome(
                {
                    **base,
                    "status": "SKIPPED",
                    "shadow_decision": "NOT_READY",
                    "skip_reason": "NO_AUTHORIZED_EVIDENCE",
                    "provider_called": False,
                    "elapsed_ms": _elapsed_ms(started),
                }
            )

        shadow_request_id = f"s20qps-{package_id or access_context.request_id}"
        request = build_answer_support_request(
            request_id=shadow_request_id,
            query_text=query_text,
            candidates=candidates,
            design=self.signal_design,
            permission_filtered=True,
            owner_scope_enforced=True,
        )
        payload = build_answer_support_generation_payload(
            request,
            profile=self.request_profile,
        )
        try:
            result = self.generation_client.create_generation(
                payload,
                request_id=shadow_request_id,
                trace_id=access_context.trace_id,
            )
        except Exception as exc:
            raise AnswerSupportShadowRuntimeError(
                "cx.answer_support_shadow.provider_unavailable",
                "The shadow generation provider is unavailable.",
                provider_called=True,
            ) from exc
        try:
            evidence = normalize_answer_support_generation_result(
                request=request,
                result=result,
                design=self.signal_design,
                profile=self.request_profile,
                artifact_revision=expected_binding["model_revision"],
            )
        except (TypeError, ValueError) as exc:
            raise AnswerSupportShadowRuntimeError(
                "cx.answer_support_shadow.provider_response_invalid",
                "The shadow generation response violates the admitted contract.",
                provider_called=True,
            ) from exc
        if evidence["provider_binding"] != expected_binding:
            raise AnswerSupportShadowRuntimeError(
                "cx.answer_support_shadow.provider_binding_drift",
                "The shadow provider binding does not match the admitted profile.",
                provider_called=True,
            )
        feature_projection = build_answer_support_package_features(evidence)
        score = score_answer_support_shadow_features(feature_projection)
        threshold = float(profile["threshold"])
        shadow_ready = score >= threshold
        primary_ready = primary_status == "READY"
        usage = _safe_usage(result.get("usage"))
        return _finish_outcome(
            {
                **base,
                "status": "OBSERVED",
                "shadow_decision": "READY" if shadow_ready else "LOW_CONFIDENCE",
                "shadow_score": score,
                "threshold": threshold,
                "primary_shadow_agree": primary_ready == shadow_ready,
                "provider_binding": dict(evidence["provider_binding"]),
                "request_hash": evidence["request_hash"],
                "evidence_hash": evidence["evidence_hash"],
                "feature_hash": semantic_sha256_hash_ref(feature_projection),
                "candidate_count": feature_projection["candidate_count"],
                "provider_called": True,
                "usage": usage,
                "elapsed_ms": _elapsed_ms(started),
            }
        )


def validate_answer_support_shadow_configuration(
    manifest: Mapping[str, Any],
    *,
    signal_design: Mapping[str, Any],
    request_profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind shadow execution to the exact receipt-admitted runtime profile."""
    normalized_manifest = dict(_mapping(manifest, "readiness manifest"))
    manifest_hash = validate_hash_ref(normalized_manifest.pop("manifest_hash", None))
    if semantic_sha256_hash_ref(normalized_manifest) != manifest_hash:
        raise _configuration_error("manifest_integrity")
    profile = dict(
        _mapping(normalized_manifest.get("candidate_profile"), "candidate profile")
    )
    profile_hash = validate_hash_ref(profile.pop("profile_hash", None))
    if semantic_sha256_hash_ref(profile) != profile_hash:
        raise _configuration_error("profile_integrity")
    profile["profile_hash"] = profile_hash
    rollout = _mapping(normalized_manifest.get("rollout_boundary"), "rollout boundary")
    if (
        normalized_manifest.get("manifest_schema_version")
        != RUNTIME_READINESS_MANIFEST_SCHEMA_VERSION
        or normalized_manifest.get("status") != "PASS"
        or normalized_manifest.get("decision") != READINESS_DECISION
        or normalized_manifest.get("activation_status") != ACTIVATION_STATUS
        or normalized_manifest.get("holdout_reexecution_permitted") is not False
        or normalized_manifest.get("runtime_activation_permitted") is not False
        or normalized_manifest.get("production_cutover_permitted") is not False
        or profile.get("profile_schema_version") != RUNTIME_PROFILE_SCHEMA_VERSION
        or profile.get("status") != "READY_FOR_SHADOW"
        or profile.get("runtime_activation_permitted") is not False
        or rollout.get("first_stage") != "SHADOW"
        or rollout.get("shadow_decision_user_visible") is not False
        or rollout.get("fail_closed_on_binding_drift") is not True
    ):
        raise _configuration_error("readiness_boundary")

    normalized_request_profile = validate_answer_support_request_profile(
        request_profile
    )
    normalized_design = validate_answer_support_signal_design(signal_design)
    provider_binding = _mapping(profile.get("provider_binding"), "provider binding")
    if (
        normalized_request_profile["profile_hash"]
        != profile.get("request_profile_hash")
        or normalized_request_profile["profile_id"]
        != provider_binding.get("request_profile_id")
        or normalized_request_profile["provider_alias"]
        != provider_binding.get("provider_alias")
    ):
        raise _configuration_error("request_profile_binding")
    if set(profile.get("provider_binding", {})) != {
        "deployment_id",
        "model_revision",
        "provider_alias",
        "provider_type",
        "request_profile_id",
        "score_semantics_id",
    }:
        raise _configuration_error("provider_binding")
    if (
        profile.get("policy_id")
        != "cx_answer_support_contradiction_aware_ready_v2"
        or profile.get("profile_id") != "answer-support-contradiction-aware-v2"
        or profile.get("score_semantics")
        != "WEIGHTED_BOUNDED_ORDINAL_NOT_PROBABILITY"
        or profile.get("threshold_inclusive") is not True
        or not _bounded(profile.get("threshold"))
    ):
        raise _configuration_error("candidate_profile")
    normalized_manifest["manifest_hash"] = manifest_hash
    return {
        "manifest": normalized_manifest,
        "candidate_profile": profile,
        "request_profile": normalized_request_profile,
        "signal_design": normalized_design,
    }


def score_answer_support_shadow_features(
    feature_projection: Mapping[str, Any],
) -> float:
    values = _mapping(feature_projection.get("features"), "answer support features")
    source = {
        "direct_or_support_fraction": _score(values.get("direct_or_support_fraction")),
        "second_answer_support_score": _score(
            values.get("second_answer_support_score")
        ),
        "top_two_answer_support_mean": _score(
            values.get("top_two_answer_support_mean")
        ),
        "inverse_maximum_contradiction_score": 1.0
        - _score(values.get("maximum_contradiction_score")),
        "normalized_support_contradiction_margin": (
            _signed_score(values.get("support_contradiction_margin")) + 1.0
        )
        / 2.0,
    }
    return round(
        sum(source[field] * FEATURE_WEIGHTS[field] for field in FEATURE_FIELDS),
        12,
    )


def _private_candidates(
    evidence_items: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    if isinstance(evidence_items, (str, bytes)) or not isinstance(
        evidence_items, Sequence
    ):
        raise TypeError("shadow evidence items are invalid")
    candidates = []
    for item in evidence_items:
        row = _mapping(item, "shadow evidence item")
        permission = _mapping(row.get("permission_result"), "permission result")
        if permission.get("visible") is not True:
            raise AnswerSupportShadowRuntimeError(
                "cx.answer_support_shadow.permission_drift",
                "Shadow input contains evidence outside the authorized scope.",
            )
        candidates.append(
            {
                "candidate_id": _required_text(row.get("evidence_id"), "evidence_id"),
                "text": _required_text(row.get("text"), "evidence text"),
            }
        )
    return candidates


def _outcome_base(
    *,
    package_id: str | None,
    primary_status: str | None,
    purpose: str | None,
    request_id: str,
    trace_id: str,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "outcome_schema_version": ANSWER_SUPPORT_SHADOW_OUTCOME_SCHEMA_VERSION,
        "policy_id": ANSWER_SUPPORT_SHADOW_POLICY_ID,
        "mode": "SHADOW",
        "retrieval_package_id": package_id,
        "request_id": request_id,
        "trace_id": trace_id,
        "purpose": purpose,
        "primary_status": primary_status,
        "profile_id": profile["profile_id"],
        "profile_hash": profile["profile_hash"],
        "user_visible": False,
        "primary_decision_mutated": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }


def _failure_outcome(
    exc: Exception,
    *,
    package_id: str | None,
    primary_status: str | None,
    purpose: str | None,
    request_id: str,
    trace_id: str,
    elapsed_ms: float,
) -> dict[str, Any]:
    if isinstance(exc, AnswerSupportShadowRuntimeError):
        error_code = exc.error_code
        provider_called = exc.provider_called
    elif isinstance(exc, (TypeError, ValueError)):
        error_code = "cx.answer_support_shadow.contract_invalid"
        provider_called = False
    else:
        error_code = "cx.answer_support_shadow.provider_unavailable"
        provider_called = False
    return _finish_outcome(
        {
            "outcome_schema_version": ANSWER_SUPPORT_SHADOW_OUTCOME_SCHEMA_VERSION,
            "policy_id": ANSWER_SUPPORT_SHADOW_POLICY_ID,
            "mode": "SHADOW",
            "status": "FAILED",
            "shadow_decision": "NOT_READY",
            "retrieval_package_id": package_id,
            "request_id": request_id,
            "trace_id": trace_id,
            "purpose": purpose,
            "primary_status": primary_status,
            "error_code": error_code,
            "provider_called": provider_called,
            "elapsed_ms": elapsed_ms,
            "user_visible": False,
            "primary_decision_mutated": False,
            "runtime_activation_permitted": False,
            "production_cutover_permitted": False,
        }
    )


def _finish_outcome(outcome: dict[str, Any]) -> dict[str, Any]:
    outcome["outcome_hash"] = semantic_sha256_hash_ref(outcome)
    return outcome


def _runtime_provider_binding(
    calibrated_binding: Mapping[str, Any],
    override: Mapping[str, Any] | None,
) -> dict[str, Any]:
    calibrated = dict(calibrated_binding)
    if override is None:
        return calibrated
    runtime = dict(override)
    if set(runtime) != set(calibrated):
        raise ValueError("runtime provider binding fields do not match calibration")
    stable_fields = set(calibrated) - {"deployment_id"}
    if any(runtime.get(field) != calibrated.get(field) for field in stable_fields):
        raise ValueError("runtime provider binding changed calibrated semantics")
    if not str(runtime.get("deployment_id", "")).strip():
        raise ValueError("runtime provider deployment_id is required")
    return runtime


def _safe_usage(value: object) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        count = value.get(key)
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            result[key] = count
    return result or None


def _configuration_error(field: str) -> AnswerSupportShadowRuntimeError:
    return AnswerSupportShadowRuntimeError(
        "cx.answer_support_shadow.configuration_invalid",
        f"The answer-support shadow {field} is invalid.",
    )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _required_text(value: object, name: str) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise ValueError(f"{name} is invalid")
    return normalized


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _bounded(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and 0.0 <= float(value) <= 1.0
    )


def _score(value: object) -> float:
    if not _bounded(value):
        raise ValueError("answer support score is invalid")
    return float(value)


def _signed_score(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not -1.0 <= float(value) <= 1.0
    ):
        raise ValueError("answer support margin is invalid")
    return float(value)


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, (perf_counter() - started) * 1000.0), 3)
