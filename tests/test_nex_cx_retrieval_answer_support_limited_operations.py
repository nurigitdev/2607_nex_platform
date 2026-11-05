from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_controlled_activation import (
    ACTIVATION_BUNDLE_PATH_ENV,
    ACTIVATION_MODE_ENV,
    DEFAULT_ACTIVATION_BUNDLE_PATH,
    ROLLED_BACK,
    OperationalAnswerSupportProgressSink,
    OperationalRuntimeActivationStateStore,
    build_activation_state,
    build_installed_controlled_answer_support_runtime,
)
from nex_cx.retrieval_answer_support_limited_operations import (
    DEFAULT_POLICY_PATH,
    LIMITED_OPERATIONS_MODE_ENV,
    LIMITED_OPERATIONS_POLICY_PATH_ENV,
    OPERATIONS_PATH,
    LimitedShadowOperationsError,
    OperationalLimitedShadowSource,
    _activation_projection,
    _hash_ref,
    _outcome_projection,
    _progress_projection,
    _safe_number,
    _safe_runtime_projection,
    build_installed_limited_shadow_operations_runtime,
    load_limited_operations_policy,
    register_limited_shadow_operations_routes,
    validate_limited_operations_policy,
)
from nex_cx.retrieval_observability import OperationalAnswerSupportShadowSink
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    issue_mock_service_token,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
PRIVATE_TEXT = "private evidence must not appear"


class FakeGenerationClient:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        del request_id, trace_id
        self.calls += 1
        if self.error is not None:
            raise self.error
        request = json.loads(payload["messages"][1]["content"])
        return {
            "alias": "general-llm-default",
            "model_revision": "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a",
            "deployment_id": "dgx-qwen3-5-9b-9116",
            "provider_type": "vllm",
            "output": {
                "type": "text",
                "text": json.dumps(
                    {
                        "items": [
                            {
                                "candidate_id": row["candidate_id"],
                                "classification": "SUPPORTING_EVIDENCE",
                                "answer_support_score": 0.9,
                                "contradiction_score": 0.05,
                            }
                            for row in request["candidates"]
                        ]
                    }
                ),
            },
            "finish_reason": "STOP",
            "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        }


class RecordingSink:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.outcomes: list[dict[str, Any]] = []

    def record(self, outcome) -> None:
        if self.error is not None:
            raise self.error
        self.outcomes.append(deepcopy(dict(outcome)))


class FailingStore:
    def list_events(self, **_kwargs):
        raise RuntimeError("private database detail")


def test_policy_is_integrity_bound_and_rejects_drift_and_bad_files(tmp_path: Path) -> None:
    policy = _policy()
    assert validate_limited_operations_policy(policy)["policy_hash"] == (
        policy["policy_hash"]
    )

    drift = deepcopy(policy)
    drift["maximum_provider_samples"] = 13
    with pytest.raises(LimitedShadowOperationsError) as raised:
        validate_limited_operations_policy(drift)
    assert raised.value.error_code == "CX_LIMITED_SHADOW_POLICY_INTEGRITY"

    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    with pytest.raises(LimitedShadowOperationsError):
        load_limited_operations_policy(malformed)
    with pytest.raises(LimitedShadowOperationsError) as raised:
        load_limited_operations_policy(tmp_path / "missing.json")
    assert raised.value.error_code == "CX_LIMITED_SHADOW_POLICY_UNAVAILABLE"


def test_limited_window_caps_provider_calls_and_is_restart_safe() -> None:
    events, state_store, emitter = _event_dependencies()
    client = FakeGenerationClient()
    sink = OperationalAnswerSupportShadowSink(emitter)
    controlled = _controlled(client, state_store, emitter, sink)
    runtime = build_installed_limited_shadow_operations_runtime(
        environ=_limited_env(),
        controlled_runtime=controlled,
        store=events,
        outcome_sink=sink,
    )
    assert runtime is not None

    for index in range(1, 13):
        outcome = runtime.observe(**_observation(index))
        assert outcome["status"] == "OBSERVED"
    assert client.calls == 12
    snapshot = runtime.snapshot()
    assert snapshot["operations_status"] == "REVIEW_REQUIRED"
    assert snapshot["window"]["provider_sample_count"] == 12
    assert snapshot["window"]["remaining_provider_samples"] == 0
    assert snapshot["progress"]["completed_count"] == 12
    assert snapshot["outcomes"]["observed_count"] == 12

    skipped = runtime.observe(**_observation(13))
    assert skipped["skip_reason"] == "LIMITED_WINDOW_COMPLETE"
    assert skipped["provider_called"] is False
    assert client.calls == 12

    restarted_controlled = _controlled(client, state_store, emitter, sink)
    restarted = build_installed_limited_shadow_operations_runtime(
        environ=_limited_env(),
        controlled_runtime=restarted_controlled,
        store=events,
        outcome_sink=sink,
    )
    assert restarted is not None
    assert restarted.observe(**_observation(14))["status"] == "SKIPPED"
    assert client.calls == 12
    serialized = json.dumps(restarted.snapshot())
    assert PRIVATE_TEXT not in serialized


def test_ineligible_request_bypasses_window_reservation() -> None:
    events, state_store, emitter = _event_dependencies()
    client = FakeGenerationClient()
    sink = OperationalAnswerSupportShadowSink(emitter)
    runtime = build_installed_limited_shadow_operations_runtime(
        environ=_limited_env(),
        controlled_runtime=_controlled(client, state_store, emitter, sink),
        store=events,
        outcome_sink=sink,
    )
    assert runtime is not None
    request = _observation(1)
    request["primary_package"]["purpose"] = "search"
    outcome = runtime.observe(**request)
    assert outcome["status"] == "SKIPPED"
    assert outcome["skip_reason"] == "PURPOSE_NOT_ELIGIBLE"
    assert client.calls == 0
    assert runtime.snapshot()["window"]["provider_sample_count"] == 0


def test_disabled_invalid_mode_and_activation_binding_drift_fail_closed() -> None:
    events, state_store, emitter = _event_dependencies()
    sink = RecordingSink()
    controlled = _controlled(FakeGenerationClient(), state_store, emitter, sink)
    assert (
        build_installed_limited_shadow_operations_runtime(
            environ={},
            controlled_runtime=controlled,
            store=events,
            outcome_sink=sink,
        )
        is None
    )
    assert (
        build_installed_limited_shadow_operations_runtime(
            environ={LIMITED_OPERATIONS_MODE_ENV: "ENABLED"},
            controlled_runtime=None,
            store=events,
            outcome_sink=sink,
        )
        is None
    )
    with pytest.raises(LimitedShadowOperationsError):
        build_installed_limited_shadow_operations_runtime(
            environ={LIMITED_OPERATIONS_MODE_ENV: "bad"},
            controlled_runtime=controlled,
            store=events,
            outcome_sink=sink,
        )

    drift = _policy()
    drift["activation_bundle_hash"] = "sha256:" + "f" * 64
    _rehash(drift)
    source = OperationalLimitedShadowSource(
        store=events,
        policy=drift,
        runtime_snapshot=controlled.snapshot,
    )
    with pytest.raises(LimitedShadowOperationsError) as raised:
        subject_runtime(controlled, source, drift, sink)
    assert raised.value.error_code == "CX_LIMITED_SHADOW_ACTIVATION_BINDING_DRIFT"


def test_projection_reports_rollback_disabled_and_unavailable_source() -> None:
    events, state_store, _emitter = _event_dependencies()
    policy = _policy()
    source = OperationalLimitedShadowSource(
        store=events,
        policy=policy,
        runtime_snapshot=lambda: None,
    )
    disabled = source.snapshot(generated_at=NOW)
    assert disabled["operations_status"] == "DISABLED"
    assert disabled["activation"]["activation_state"] == "NOT_ACTIVATED"

    state_store.record_state(
        build_activation_state(
            bundle_hash=policy["activation_bundle_hash"],
            activation_state=ROLLED_BACK,
            reason_code="PROVIDER_ERROR",
        )
    )
    rolled_back = source.snapshot(generated_at=NOW)
    assert rolled_back["operations_status"] == "ROLLED_BACK"
    assert rolled_back["health_status"] == "DEGRADED"
    assert rolled_back["activation"]["reason_code"] == "PROVIDER_ERROR"

    failing = OperationalLimitedShadowSource(
        store=FailingStore(),  # type: ignore[arg-type]
        policy=policy,
        runtime_snapshot=lambda: None,
    )
    with pytest.raises(LimitedShadowOperationsError) as raised:
        failing.snapshot()
    assert raised.value.error_code == "CX_LIMITED_SHADOW_SOURCE_UNAVAILABLE"
    assert raised.value.retryable is True


def test_operations_route_is_ag_scope_protected_redacted_and_safe_on_failure() -> None:
    events, state_store, emitter = _event_dependencies()
    client = FakeGenerationClient()
    sink = OperationalAnswerSupportShadowSink(emitter)
    runtime = build_installed_limited_shadow_operations_runtime(
        environ=_limited_env(),
        controlled_runtime=_controlled(client, state_store, emitter, sink),
        store=events,
        outcome_sink=sink,
    )
    assert runtime is not None
    runtime.observe(**_observation(1))
    api = FastAPI()
    register_limited_shadow_operations_routes(api, source=runtime.source)
    http = TestClient(api)

    assert http.get(OPERATIONS_PATH).status_code == 401
    forbidden = http.get(
        OPERATIONS_PATH,
        headers={"Authorization": _authorization("nex-ae-api")},
    )
    assert forbidden.status_code == 403
    missing_scope = http.get(
        OPERATIONS_PATH,
        headers={"Authorization": _authorization(include_scope=False)},
    )
    assert missing_scope.status_code == 401
    response = http.get(
        OPERATIONS_PATH,
        headers={"Authorization": _authorization()},
    )
    assert response.status_code == 200
    assert response.json()["operations_status"] == "OBSERVING"
    assert response.json()["window"]["provider_sample_count"] == 1
    assert PRIVATE_TEXT not in response.text

    unavailable_api = FastAPI()
    register_limited_shadow_operations_routes(
        unavailable_api,
        source=OperationalLimitedShadowSource(
            store=FailingStore(),  # type: ignore[arg-type]
            policy=_policy(),
            runtime_snapshot=lambda: None,
        ),
    )
    unavailable = TestClient(unavailable_api).get(
        OPERATIONS_PATH,
        headers={"Authorization": _authorization()},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["retryable"] is True
    assert "private database detail" not in unavailable.text


def test_clock_policy_and_projection_helpers_reject_malformed_values() -> None:
    source = OperationalLimitedShadowSource(
        store=InMemoryOperationalEventStore(),
        policy=_policy(),
        runtime_snapshot=lambda: None,
    )
    with pytest.raises(LimitedShadowOperationsError):
        source.snapshot(generated_at=datetime(2026, 11, 5))  # noqa: DTZ001

    for mutate in (
        lambda value: value.pop("window_id"),
        lambda value: value.update(status="DRAFT"),
        lambda value: value.update(maximum_event_scan=100),
    ):
        policy = _policy()
        mutate(policy)
        if "policy_hash" in policy:
            _rehash(policy)
        with pytest.raises(LimitedShadowOperationsError):
            validate_limited_operations_policy(policy)


def test_projection_helpers_ignore_malformed_events_and_sanitize_values() -> None:
    policy = _policy()
    activation_events = [
        {"created_at": "2026-11-05T10:00:00Z", "details": "bad"},
        {
            "created_at": "2026-11-05T10:01:00Z",
            "details": {
                "activation_bundle_hash": "sha256:" + "0" * 64,
                "activation_state": "ACTIVE",
            },
        },
        {
            "created_at": "2026-11-05T10:02:00Z",
            "details": {
                "activation_bundle_hash": policy["activation_bundle_hash"],
                "activation_state": "ACTIVE",
                "reason_code": "OPERATOR_APPROVED",
            },
        },
    ]
    activation = _activation_projection(activation_events, policy)
    assert activation["activation_state"] == "ACTIVE"

    progress = _progress_projection(
        [
            {"created_at": "2026-11-05T09:59:00Z", "details": {}},
            {"created_at": "2026-11-05T10:03:00Z", "details": "bad"},
            {
                "created_at": "2026-11-05T10:04:00Z",
                "details": {"progress_event_type": "UNKNOWN"},
            },
            {
                "created_at": "2026-11-05T10:05:00Z",
                "details": {
                    "progress_event_type": "REQUEST_ADMITTED",
                    "elapsed_ms": 1.25,
                },
            },
            {
                "created_at": "2026-11-05T10:06:00Z",
                "details": {
                    "progress_event_type": "REQUEST_FAILED",
                    "elapsed_ms": 12,
                },
            },
        ],
        activation,
    )
    assert progress["admitted_count"] == 1
    assert progress["failed_count"] == 1
    assert progress["feedback_p95_latency_ms"] == 1.25
    assert progress["provider_p95_latency_ms"] == 12.0

    outcomes = _outcome_projection(
        [
            {"created_at": "2026-11-05T10:03:00Z", "details": "bad"},
            {
                "created_at": "2026-11-05T10:04:00Z",
                "details": {
                    "shadow_status": "UNKNOWN",
                    "provider_called": True,
                    "elapsed_ms": -1,
                },
            },
            {
                "created_at": "2026-11-05T10:05:00Z",
                "details": {
                    "shadow_status": "FAILED",
                    "provider_called": True,
                    "elapsed_ms": 15.5,
                    "primary_shadow_agree": False,
                },
            },
        ],
        activation,
    )
    assert outcomes["failed_count"] == 1
    assert outcomes["primary_shadow_disagreement_count"] == 1
    assert outcomes["e2e_p95_latency_ms"] == 15.5
    assert _safe_runtime_projection({"generation_client": "bad"}) == {
        "installed": True,
        "activation_state": None,
        "in_flight": 0,
        "peak_in_flight": 0,
    }
    assert _safe_number(True) is None
    assert _safe_number("1") is None
    with pytest.raises(LimitedShadowOperationsError):
        _hash_ref(None, "hash")
    with pytest.raises(LimitedShadowOperationsError):
        _hash_ref("not-a-hash", "hash")


def _controlled(client, state_store, emitter, sink):
    runtime = build_installed_controlled_answer_support_runtime(
        environ={
            ACTIVATION_MODE_ENV: "controlled",
            ACTIVATION_BUNDLE_PATH_ENV: str(DEFAULT_ACTIVATION_BUNDLE_PATH),
        },
        generation_client=client,
        progress_sink=OperationalAnswerSupportProgressSink(emitter),
        outcome_sink=sink,
        state_store=state_store,
    )
    assert runtime is not None
    return runtime


def subject_runtime(controlled, source, policy, sink):
    from nex_cx.retrieval_answer_support_limited_operations import (
        LimitedShadowOperationsRuntime,
    )

    return LimitedShadowOperationsRuntime(
        controlled,
        source=source,
        policy=policy,
        outcome_sink=sink,
    )


def _event_dependencies():
    events = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=events)
    state_store = OperationalRuntimeActivationStateStore(
        emitter=emitter,
        store=events,
    )
    return events, state_store, emitter


def _limited_env() -> dict[str, str]:
    return {
        LIMITED_OPERATIONS_MODE_ENV: "enabled",
        LIMITED_OPERATIONS_POLICY_PATH_ENV: str(DEFAULT_POLICY_PATH),
    }


def _observation(index: int) -> dict[str, Any]:
    return {
        "query_text": f"question-{index}",
        "evidence_items": [
            {
                "evidence_id": f"evidence-{index}",
                "text": PRIVATE_TEXT,
                "permission_result": {"visible": True},
            }
        ],
        "primary_package": {
            "retrieval_package_id": f"package-{index}",
            "status": "READY",
            "purpose": "grounded_answer",
        },
        "access_context": CxAccessContext(
            tenant_id="tenant-a",
            subject_id="subject-a",
            caller_service_id="nex-ae-api",
            scopes=("cx:retrieval:read",),
            request_id=f"request-{index}",
            trace_id=f"{index:032x}",
        ),
    }


def _authorization(
    service_id: str = "nex-ag", *, include_scope: bool = True
) -> str:
    scopes = ["service:call"]
    if include_scope:
        scopes.append("operations:read")
    token = issue_mock_service_token(
        service_id=service_id,
        audience="nex-cx",
        scopes=scopes,
    )
    return f"Bearer {token.access_token}"


def _policy() -> dict[str, Any]:
    return json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))


def _rehash(policy: dict[str, Any]) -> None:
    policy.pop("policy_hash", None)
    policy["policy_hash"] = semantic_sha256_hash_ref(policy)
