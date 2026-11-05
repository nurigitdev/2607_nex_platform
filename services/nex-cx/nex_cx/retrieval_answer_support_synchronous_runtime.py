from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_shadow_runtime import (
    AnswerSupportGenerationClient,
    AnswerSupportShadowOutcomeSink,
    AnswerSupportShadowRuntime,
)

DESIGN_SCHEMA_VERSION = "cx_answer_support_sync_runtime_e2e_design.v1"
RECEIPT_SCHEMA_VERSION = "cx_answer_support_sync_runtime_e2e_receipt.v1"
MANIFEST_SCHEMA_VERSION = "cx_answer_support_sync_runtime_e2e_manifest.v1"
PROGRESS_EVENT_SCHEMA_VERSION = "cx_answer_support_sync_progress_event.v1"
POLICY_SCHEMA_VERSION = "cx_answer_support_interactive_slo_runtime_policy.v1"
ACCEPTED_DECISION = "SYNCHRONOUS_RUNTIME_E2E_ACCEPTED_PENDING_OPERATOR_ACTIVATION"
REJECTED_DECISION = "SYNCHRONOUS_RUNTIME_E2E_REJECTED_RETAIN_CURRENT_POLICY"

_SOURCE_FIELDS = {
    "artifact_evidence_hash",
    "case_set_hash",
    "interactive_slo_decision_receipt_document_hash",
    "interactive_slo_decision_receipt_hash",
    "interactive_slo_design_hash",
    "interactive_slo_manifest_hash",
    "provider_binding_hash",
    "readiness_manifest_hash",
    "request_profile_hash",
    "runtime_profile_hash",
    "selected_policy_hash",
    "signal_design_hash",
}
_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "acceptance_policy",
    "safety",
}
_EXPECTED_ACCEPTANCE_POLICY = {
    "sample_count": 30,
    "maximum_concurrency": 4,
    "maximum_provider_errors": 0,
    "maximum_admission_rejections": 0,
    "prompt_acceptance_feedback_p95_latency_ms": 2_000,
    "generation_provider_p95_latency_ms": 15_000,
    "interactive_final_response_e2e_p95_latency_ms": 20_000,
    "request_timeout_ms": 60_000,
    "overload_probe_required": True,
    "overload_must_be_retryable": True,
}
_EXPECTED_SAFETY = {
    "database_call_permitted": False,
    "holdout_access_permitted": False,
    "runtime_activation_permitted": False,
    "production_cutover_permitted": False,
}
_EXPECTED_RUNTIME_POLICY = {
    "execution_mode": "SYNCHRONOUS",
    "maximum_in_flight_provider_requests": 4,
    "admission_strategy": "BOUNDED_SEMAPHORE",
    "overload_behavior": "DEFER_OR_REJECT_RETRYABLE",
    "generation_request_timeout_ms": 60_000,
    "reasoning_mode": "DISABLED",
    "selection_status": "SELECTED_PENDING_E2E_ACCEPTANCE",
}
_EXPECTED_SLO_PROFILE = {
    "prompt_acceptance_feedback_p95_latency_ms": 2_000,
    "generation_provider_p95_latency_ms": 15_000,
    "interactive_final_response_e2e_p95_latency_ms": 20_000,
    "background_provider_p95_latency_ms": 45_000,
    "request_timeout_ms": 60_000,
}


class AnswerSupportProgressSink(Protocol):
    def record(self, event: Mapping[str, Any]) -> None: ...


class SynchronousRuntimeAcceptanceError(ValueError):
    def __init__(
        self, error_code: str, detail: str, *, retryable: bool = False
    ) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable


class BoundedSynchronousGenerationClient:
    """Bound one synchronous generation client without retaining private payloads."""

    def __init__(
        self,
        delegate: AnswerSupportGenerationClient,
        *,
        progress_sink: AnswerSupportProgressSink,
        maximum_in_flight: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if (
            isinstance(maximum_in_flight, bool)
            or not isinstance(maximum_in_flight, int)
            or maximum_in_flight < 1
        ):
            raise ValueError("maximum_in_flight must be a positive integer")
        self._delegate = delegate
        self._progress_sink = progress_sink
        self._maximum_in_flight = maximum_in_flight
        self._clock = clock
        self._semaphore = BoundedSemaphore(maximum_in_flight)
        self._lock = Lock()
        self._received: dict[str, float] = {}
        self._in_flight = 0
        self._peak_in_flight = 0
        self._admitted = 0
        self._rejected = 0
        self._completed = 0
        self._failed = 0
        self._progress_failures = 0
        self._feedback_latencies_ms: list[float] = []
        self._provider_latencies_ms: list[float] = []

    def begin_request(self, request_id: str) -> None:
        request_key = _required_identity(request_id, "request_id")
        with self._lock:
            if request_key in self._received:
                raise SynchronousRuntimeAcceptanceError(
                    "cx.answer_support_sync.duplicate_request",
                    "The synchronous answer-support request is already in flight.",
                )
            self._received[request_key] = self._clock()

    def finish_request(self, request_id: str) -> None:
        with self._lock:
            self._received.pop(request_id, None)

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        request_key = _required_identity(request_id, "request_id")
        trace_key = _required_identity(trace_id, "trace_id")
        now = self._clock()
        with self._lock:
            received_at = self._received.pop(request_key, now)
        feedback_ms = _milliseconds(now - received_at)
        if not self._semaphore.acquire(blocking=False):
            with self._lock:
                self._rejected += 1
            self._best_effort_event(
                _progress_event(
                    event_type="REQUEST_REJECTED",
                    request_id=request_key,
                    trace_id=trace_key,
                    elapsed_ms=feedback_ms,
                    retryable=True,
                )
            )
            raise SynchronousRuntimeAcceptanceError(
                "cx.answer_support_sync.capacity_exhausted",
                "The synchronous answer-support capacity is exhausted.",
                retryable=True,
            )

        with self._lock:
            self._in_flight += 1
            self._peak_in_flight = max(self._peak_in_flight, self._in_flight)
            self._admitted += 1
            self._feedback_latencies_ms.append(feedback_ms)
        try:
            self._progress_sink.record(
                _progress_event(
                    event_type="REQUEST_ADMITTED",
                    request_id=request_key,
                    trace_id=trace_key,
                    elapsed_ms=feedback_ms,
                    retryable=False,
                )
            )
        except Exception as exc:
            with self._lock:
                self._failed += 1
                self._progress_failures += 1
            self._release()
            raise SynchronousRuntimeAcceptanceError(
                "cx.answer_support_sync.progress_unavailable",
                "The synchronous answer-support progress sink is unavailable.",
                retryable=True,
            ) from exc

        provider_started = self._clock()
        try:
            response = self._delegate.create_generation(
                payload,
                request_id=request_key,
                trace_id=trace_key,
            )
        except Exception:
            provider_ms = _milliseconds(self._clock() - provider_started)
            with self._lock:
                self._failed += 1
                self._provider_latencies_ms.append(provider_ms)
            self._best_effort_event(
                _progress_event(
                    event_type="REQUEST_FAILED",
                    request_id=request_key,
                    trace_id=trace_key,
                    elapsed_ms=provider_ms,
                    retryable=True,
                )
            )
            raise
        else:
            provider_ms = _milliseconds(self._clock() - provider_started)
            with self._lock:
                self._completed += 1
                self._provider_latencies_ms.append(provider_ms)
            self._best_effort_event(
                _progress_event(
                    event_type="REQUEST_COMPLETED",
                    request_id=request_key,
                    trace_id=trace_key,
                    elapsed_ms=provider_ms,
                    retryable=False,
                )
            )
            return response
        finally:
            self._release()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "maximum_in_flight": self._maximum_in_flight,
                "in_flight": self._in_flight,
                "peak_in_flight": self._peak_in_flight,
                "admitted_count": self._admitted,
                "rejected_count": self._rejected,
                "completed_count": self._completed,
                "failed_count": self._failed,
                "progress_failure_count": self._progress_failures,
                "feedback_latencies_ms": list(self._feedback_latencies_ms),
                "provider_latencies_ms": list(self._provider_latencies_ms),
                "pending_request_count": len(self._received),
            }

    def _release(self) -> None:
        with self._lock:
            self._in_flight -= 1
        self._semaphore.release()

    def _best_effort_event(self, event: Mapping[str, Any]) -> None:
        try:
            self._progress_sink.record(event)
        except Exception:  # noqa: BLE001 - completion telemetry is best effort
            with self._lock:
                self._progress_failures += 1


@dataclass(frozen=True)
class BoundedSynchronousAnswerSupportRuntime:
    delegate: AnswerSupportShadowRuntime
    generation_client: BoundedSynchronousGenerationClient

    def observe(
        self,
        *,
        query_text: str,
        evidence_items: Sequence[Mapping[str, Any]],
        primary_package: Mapping[str, Any],
        access_context: CxAccessContext,
    ) -> Mapping[str, Any]:
        package_id = primary_package.get("retrieval_package_id")
        request_id = (
            f"s20qps-{package_id}"
            if isinstance(package_id, str) and package_id
            else f"s20qps-{access_context.request_id}"
        )
        self.generation_client.begin_request(request_id)
        try:
            return self.delegate.observe(
                query_text=query_text,
                evidence_items=evidence_items,
                primary_package=primary_package,
                access_context=access_context,
            )
        finally:
            self.generation_client.finish_request(request_id)


def build_bounded_synchronous_answer_support_runtime(
    *,
    policy: Mapping[str, Any],
    readiness_manifest: Mapping[str, Any],
    signal_design: Mapping[str, Any],
    request_profile: Mapping[str, Any],
    generation_client: AnswerSupportGenerationClient,
    progress_sink: AnswerSupportProgressSink,
    outcome_sink: AnswerSupportShadowOutcomeSink,
    clock: Callable[[], float] = monotonic,
) -> BoundedSynchronousAnswerSupportRuntime:
    normalized_policy = validate_synchronous_runtime_policy(policy)
    gateway = BoundedSynchronousGenerationClient(
        generation_client,
        progress_sink=progress_sink,
        maximum_in_flight=normalized_policy["runtime_policy"][
            "maximum_in_flight_provider_requests"
        ],
        clock=clock,
    )
    return BoundedSynchronousAnswerSupportRuntime(
        delegate=AnswerSupportShadowRuntime(
            readiness_manifest=readiness_manifest,
            signal_design=signal_design,
            request_profile=request_profile,
            generation_client=gateway,
            outcome_sink=outcome_sink,
        ),
        generation_client=gateway,
    )


def validate_synchronous_runtime_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(_mapping(policy, "selected_policy"))
    supplied_hash = _hash_ref(normalized.pop("policy_hash", None), "policy_hash")
    if (
        normalized.get("policy_schema_version") != POLICY_SCHEMA_VERSION
        or normalized.get("status") != "SELECTED_PENDING_E2E_ACCEPTANCE"
        or dict(_mapping(normalized.get("slo_profile"), "slo_profile"))
        != _EXPECTED_SLO_PROFILE
        or dict(_mapping(normalized.get("runtime_policy"), "runtime_policy"))
        != _EXPECTED_RUNTIME_POLICY
        or normalized.get("fallback_policy")
        != "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY"
        or normalized.get("runtime_activation_permitted") is not False
        or normalized.get("production_cutover_permitted") is not False
    ):
        raise _invalid("selected_policy")
    if semantic_sha256_hash_ref(normalized) != supplied_hash:
        raise _integrity("selected_policy")
    normalized["policy_hash"] = supplied_hash
    return normalized


def validate_synchronous_runtime_e2e_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(_mapping(design, "design"))
    supplied_hash = normalized.pop("design_hash", None)
    _exact(normalized, _DESIGN_FIELDS, "design")
    if (
        normalized.get("design_schema_version") != DESIGN_SCHEMA_VERSION
        or normalized.get("status") != "FROZEN_PRE_ACCEPTANCE"
        or not _text(normalized.get("design_id"))
    ):
        raise _invalid("design_identity")
    source = _exact(normalized.get("source_binding"), _SOURCE_FIELDS, "source")
    normalized["source_binding"] = {
        key: _hash_ref(source.get(key), key) for key in sorted(_SOURCE_FIELDS)
    }
    if dict(_mapping(normalized.get("acceptance_policy"), "acceptance_policy")) != (
        _EXPECTED_ACCEPTANCE_POLICY
    ):
        raise _invalid("acceptance_policy")
    if dict(_mapping(normalized.get("safety"), "safety")) != _EXPECTED_SAFETY:
        raise _invalid("safety")
    calculated = semantic_sha256_hash_ref(normalized)
    if (
        supplied_hash is not None
        and _hash_ref(supplied_hash, "design_hash") != calculated
    ):
        raise _integrity("design")
    normalized["design_hash"] = calculated
    return normalized


def evaluate_synchronous_runtime_e2e_receipt(
    receipt: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    decision_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_design = validate_synchronous_runtime_e2e_design(design)
    source = normalized_design["source_binding"]
    _validate_decision_receipt(decision_receipt, source=source)
    normalized = dict(_mapping(receipt, "receipt"))
    receipt_hash = _hash_ref(normalized.pop("receipt_hash", None), "receipt_hash")
    if semantic_sha256_hash_ref(normalized) != receipt_hash:
        raise _integrity("receipt")
    if (
        normalized.get("receipt_schema_version") != RECEIPT_SCHEMA_VERSION
        or normalized.get("status") != "PASS"
        or normalized.get("design_hash") != normalized_design["design_hash"]
        or normalized.get("selected_policy_hash") != source["selected_policy_hash"]
        or normalized.get("source_binding") != source
        or normalized.get("database_calls") != 0
        or normalized.get("holdout_accessed") is not False
        or normalized.get("runtime_activation_permitted") is not False
        or normalized.get("production_cutover_permitted") is not False
    ):
        raise _invalid("receipt")
    execution = _mapping(normalized.get("execution"), "execution")
    metrics = _mapping(normalized.get("metrics"), "metrics")
    policy = normalized_design["acceptance_policy"]
    checks = {
        "sample_count_complete": execution.get("accepted_count")
        == policy["sample_count"],
        "provider_calls_exact": execution.get("provider_call_count")
        == policy["sample_count"],
        "maximum_concurrency_enforced": execution.get("maximum_in_flight")
        == policy["maximum_concurrency"],
        "peak_concurrency_observed": execution.get("peak_in_flight")
        == policy["maximum_concurrency"],
        "provider_errors_within_limit": execution.get("provider_error_count")
        <= policy["maximum_provider_errors"],
        "admission_rejections_within_limit": execution.get("rejected_count")
        <= policy["maximum_admission_rejections"],
        "progress_sink_healthy": execution.get("progress_failure_count") == 0,
        "feedback_samples_complete": metrics.get("feedback_sample_count")
        == policy["sample_count"],
        "provider_samples_complete": metrics.get("provider_sample_count")
        == policy["sample_count"],
        "e2e_samples_complete": metrics.get("e2e_sample_count")
        == policy["sample_count"],
        "feedback_p95_slo_met": _within(
            metrics.get("feedback_p95_latency_ms"),
            policy["prompt_acceptance_feedback_p95_latency_ms"],
        ),
        "provider_p95_slo_met": _within(
            metrics.get("provider_p95_latency_ms"),
            policy["generation_provider_p95_latency_ms"],
        ),
        "interactive_e2e_p95_slo_met": _within(
            metrics.get("e2e_p95_latency_ms"),
            policy["interactive_final_response_e2e_p95_latency_ms"],
        ),
        "overload_retryable_rejection_verified": execution.get(
            "overload_probe_retryable"
        )
        is policy["overload_must_be_retryable"],
        "database_not_called": True,
        "holdout_not_accessed": True,
        "runtime_activation_prohibited": True,
        "production_cutover_prohibited": True,
    }
    accepted = all(checks.values())
    manifest: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "decision": ACCEPTED_DECISION if accepted else REJECTED_DECISION,
        "design_hash": normalized_design["design_hash"],
        "source_receipt_hash": receipt_hash,
        "selected_policy_hash": source["selected_policy_hash"],
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "execution": dict(execution),
        "metrics": dict(metrics),
        "fallback_policy": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": "RUNTIME_ACTIVATION_OPERATOR_DECISION",
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def _validate_decision_receipt(
    receipt: Mapping[str, Any], *, source: Mapping[str, Any]
) -> None:
    normalized = dict(_mapping(receipt, "decision_receipt"))
    receipt_hash = _hash_ref(normalized.pop("receipt_hash", None), "receipt_hash")
    if (
        semantic_sha256_hash_ref(normalized) != receipt_hash
        or receipt_hash != source["interactive_slo_decision_receipt_hash"]
    ):
        raise _integrity("decision_receipt")
    normalized["receipt_hash"] = receipt_hash
    if (
        semantic_sha256_hash_ref(normalized)
        != source["interactive_slo_decision_receipt_document_hash"]
        or normalized.get("status") != "PASS"
        or normalized.get("selected_policy_hash") != source["selected_policy_hash"]
        or normalized.get("manifest_hash") != source["interactive_slo_manifest_hash"]
        or normalized.get("runtime_activation_permitted") is not False
        or normalized.get("production_cutover_permitted") is not False
    ):
        raise _invalid("decision_receipt")


def _progress_event(
    *,
    event_type: str,
    request_id: str,
    trace_id: str,
    elapsed_ms: float,
    retryable: bool,
) -> dict[str, Any]:
    event = {
        "event_schema_version": PROGRESS_EVENT_SCHEMA_VERSION,
        "event_type": event_type,
        "request_id": request_id,
        "trace_id": trace_id,
        "elapsed_ms": elapsed_ms,
        "retryable": retryable,
    }
    event["event_hash"] = semantic_sha256_hash_ref(event)
    return event


def _within(value: object, maximum: int) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and 0 <= value <= maximum
    )


def _milliseconds(seconds: float) -> float:
    return round(max(seconds, 0.0) * 1_000.0, 6)


def _required_identity(value: object, name: str) -> str:
    if not _text(value):
        raise _invalid(name)
    return str(value)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 200


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(name)
    return value


def _exact(value: object, expected: set[str], name: str) -> Mapping[str, Any]:
    mapping = _mapping(value, name)
    if set(mapping) != expected:
        raise _invalid(f"{name}_fields")
    return mapping


def _hash_ref(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise _invalid(name)
    try:
        validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(name) from exc
    return value


def _invalid(detail: str) -> SynchronousRuntimeAcceptanceError:
    return SynchronousRuntimeAcceptanceError(
        "SYNCHRONOUS_RUNTIME_ACCEPTANCE_INVALID", detail
    )


def _integrity(detail: str) -> SynchronousRuntimeAcceptanceError:
    return SynchronousRuntimeAcceptanceError(
        "SYNCHRONOUS_RUNTIME_ACCEPTANCE_INTEGRITY", detail
    )
