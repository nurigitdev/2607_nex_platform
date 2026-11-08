from __future__ import annotations

from copy import deepcopy

import pytest
from nex_cx.retrieval_answer_support_limited_operations import (
    DEFAULT_EXTENDED_POLICY_PATH,
    DEFAULT_POLICY_PATH,
    LIMITED_OPERATIONS_MODE_ENV,
    LIMITED_OPERATIONS_POLICY_PATH_ENV,
    WINDOW_EVENT_TYPE,
    LimitedShadowOperationsError,
    LimitedShadowOperationsRuntime,
    OperationalLimitedShadowSource,
    _ensure_extended_window_open,
    _window_opened_at,
    build_installed_limited_shadow_operations_runtime,
    load_limited_operations_policy,
    validate_extended_operations_authorization,
    validate_limited_operations_policy,
)
from nex_cx.retrieval_observability import OperationalAnswerSupportShadowSink
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_limited_operations import (
    FakeGenerationClient,
    RecordingSink,
    _controlled,
    _event_dependencies,
    _observation,
)


def test_extended_policy_and_operator_receipt_are_integrity_bound() -> None:
    policy = load_limited_operations_policy(DEFAULT_EXTENDED_POLICY_PATH)
    receipt = _decision_receipt()

    normalized = validate_extended_operations_authorization(policy, receipt)

    assert policy["maximum_provider_samples"] == 30
    assert normalized["receipt_hash"] == receipt["receipt_hash"]
    assert policy["continuation_authorization"]["decision_receipt_hash"] == (
        receipt["receipt_hash"]
    )

    receipt_drift = deepcopy(receipt)
    receipt_drift["continuation_executed"] = True
    with pytest.raises(LimitedShadowOperationsError) as raised:
        validate_extended_operations_authorization(policy, receipt_drift)
    assert raised.value.error_code == "CX_LIMITED_SHADOW_AUTHORIZATION_INTEGRITY"

    with pytest.raises(LimitedShadowOperationsError):
        validate_extended_operations_authorization(
            load_limited_operations_policy(DEFAULT_POLICY_PATH), receipt
        )


def test_fresh_extended_window_excludes_prior_events_and_caps_at_thirty() -> None:
    events, state_store, emitter = _event_dependencies()
    client = FakeGenerationClient()
    sink = OperationalAnswerSupportShadowSink(emitter)
    initial_controlled = _controlled(client, state_store, emitter, sink)
    initial_runtime = build_installed_limited_shadow_operations_runtime(
        environ=_operations_env(DEFAULT_POLICY_PATH),
        controlled_runtime=initial_controlled,
        store=events,
        outcome_sink=sink,
    )
    assert initial_runtime is not None
    assert initial_runtime.observe(**_observation(1))["status"] == "OBSERVED"
    assert initial_runtime.observe(**_observation(2))["status"] == "OBSERVED"

    extended_controlled = _controlled(client, state_store, emitter, sink)
    extended = build_installed_limited_shadow_operations_runtime(
        environ=_operations_env(DEFAULT_EXTENDED_POLICY_PATH),
        controlled_runtime=extended_controlled,
        store=events,
        outcome_sink=sink,
    )
    assert extended is not None
    assert extended.snapshot()["window"]["provider_sample_count"] == 0

    for index in range(101, 131):
        assert extended.observe(**_observation(index))["status"] == "OBSERVED"
    assert client.calls == 32
    assert extended.snapshot()["window"] == {
        "window_id": "s20qpad-extended-limited-shadow-window-v1",
        "policy_hash": policy_hash(),
        "minimum_operator_review_samples": 30,
        "maximum_provider_samples": 30,
        "provider_sample_count": 30,
        "remaining_provider_samples": 0,
        "sample_cap_reached": True,
    }

    restarted = build_installed_limited_shadow_operations_runtime(
        environ=_operations_env(DEFAULT_EXTENDED_POLICY_PATH),
        controlled_runtime=_controlled(client, state_store, emitter, sink),
        store=events,
        outcome_sink=sink,
    )
    assert restarted is not None
    assert restarted.observe(**_observation(131))["skip_reason"] == (
        "LIMITED_WINDOW_COMPLETE"
    )
    assert client.calls == 32
    markers = events.list_events(
        service_id="nex-cx", event_type=WINDOW_EVENT_TYPE, limit=500
    )
    assert len(markers) == 1


def test_extended_source_without_window_marker_remains_disabled() -> None:
    events, state_store, emitter = _event_dependencies()
    controlled = _controlled(
        FakeGenerationClient(),
        state_store,
        emitter,
        OperationalAnswerSupportShadowSink(emitter),
    )
    source = OperationalLimitedShadowSource(
        store=events,
        policy=load_limited_operations_policy(DEFAULT_EXTENDED_POLICY_PATH),
        runtime_snapshot=controlled.snapshot,
    )

    snapshot = source.snapshot()

    assert snapshot["operations_status"] == "DISABLED"
    assert snapshot["window"]["provider_sample_count"] == 0


def test_window_marker_rejects_same_id_with_different_policy() -> None:
    events, _state_store, _emitter = _event_dependencies()
    policy = load_limited_operations_policy(DEFAULT_EXTENDED_POLICY_PATH)
    first = _ensure_extended_window_open(store=events, policy=policy)
    second = _ensure_extended_window_open(store=events, policy=policy)
    assert first == second

    drift = deepcopy(policy)
    drift["continuation_authorization"]["decision_receipt_hash"] = (
        "sha256:" + "f" * 64
    )
    _rehash(drift)
    drift = validate_limited_operations_policy(drift)
    with pytest.raises(LimitedShadowOperationsError) as raised:
        _ensure_extended_window_open(store=events, policy=drift)
    assert raised.value.error_code == "CX_LIMITED_SHADOW_WINDOW_BINDING_DRIFT"


def test_extended_policy_semantic_drift_fails_closed() -> None:
    policy = load_limited_operations_policy(DEFAULT_EXTENDED_POLICY_PATH)
    for mutate in (
        lambda value: value.update(maximum_provider_samples=31),
        lambda value: value["continuation_authorization"].update(
            maximum_concurrency=5
        ),
        lambda value: value.update(
            window_id=value["continuation_authorization"]["source_window_id"]
        ),
    ):
        drift = deepcopy(policy)
        mutate(drift)
        _rehash(drift)
        with pytest.raises(LimitedShadowOperationsError):
            validate_limited_operations_policy(drift)

    slo_drift = deepcopy(policy)
    slo_drift["operational_slo"]["maximum_provider_failures"] = 1
    _rehash(slo_drift)
    with pytest.raises(LimitedShadowOperationsError):
        validate_limited_operations_policy(slo_drift)

    authorization_drift = deepcopy(policy)
    authorization_drift["continuation_authorization"].pop("approved_scope")
    _rehash(authorization_drift)
    with pytest.raises(LimitedShadowOperationsError):
        validate_limited_operations_policy(authorization_drift)


def test_receipt_fields_and_semantic_boundary_fail_closed() -> None:
    policy = load_limited_operations_policy(DEFAULT_EXTENDED_POLICY_PATH)
    missing = _decision_receipt()
    missing.pop("manifest_hash")
    with pytest.raises(LimitedShadowOperationsError):
        validate_extended_operations_authorization(policy, missing)

    rebound = _decision_receipt()
    rebound["status"] = "FAIL"
    rebound.pop("receipt_hash")
    rebound["receipt_hash"] = semantic_sha256_hash_ref(rebound)
    with pytest.raises(LimitedShadowOperationsError):
        validate_extended_operations_authorization(policy, rebound)


def test_window_projection_ignores_malformed_or_unbound_markers() -> None:
    policy = load_limited_operations_policy(DEFAULT_EXTENDED_POLICY_PATH)
    assert _window_opened_at(
        [
            {"details": "bad", "created_at": "2026-11-05T00:00:00Z"},
            {
                "details": {
                    "window_state": "OPEN",
                    "window_id": "another-window",
                },
                "created_at": "2026-11-05T00:00:01Z",
            },
        ],
        policy,
    ) is None


def test_non_provider_outcome_releases_reserved_sample() -> None:
    events, _state_store, _emitter = _event_dependencies()
    policy = load_limited_operations_policy(DEFAULT_POLICY_PATH)

    class Delegate:
        def snapshot(self):
            return {
                "activation_bundle_hash": policy["activation_bundle_hash"],
                "activation_state": "ACTIVE",
                "generation_client": {},
            }

        def observe(self, **_kwargs):
            return {"status": "SKIPPED", "provider_called": False}

    source = OperationalLimitedShadowSource(
        store=events,
        policy=policy,
        runtime_snapshot=Delegate().snapshot,
    )
    runtime = LimitedShadowOperationsRuntime(
        Delegate(),  # type: ignore[arg-type]
        source=source,
        policy=policy,
        outcome_sink=RecordingSink(),
    )

    assert runtime.observe(**_observation(1))["provider_called"] is False
    assert runtime._allocated_provider_samples == 0


def _operations_env(path) -> dict[str, str]:
    return {
        LIMITED_OPERATIONS_MODE_ENV: "enabled",
        LIMITED_OPERATIONS_POLICY_PATH_ENV: str(path),
    }


def policy_hash() -> str:
    return load_limited_operations_policy(DEFAULT_EXTENDED_POLICY_PATH)["policy_hash"]


def _rehash(policy: dict) -> None:
    policy.pop("policy_hash", None)
    policy["policy_hash"] = semantic_sha256_hash_ref(policy)


def _decision_receipt() -> dict:
    return {
        "approved_scope": "SECOND_BOUNDED_ANSWER_SUPPORT_SHADOW_WINDOW",
        "continuation_approved": True,
        "continuation_executed": False,
        "decided_at": "2026-11-05T11:34:32.100165Z",
        "decision": "CONTINUE_LIMITED_SHADOW_OBSERVATION_APPROVED",
        "decision_status": "APPROVED_NOT_EXECUTED",
        "design_hash": (
            "sha256:f92c6d8e96b194383b19f9a9308696a"
            "2e29a833e2838be8c04dab492653477f9"
        ),
        "manifest_hash": (
            "sha256:d8046c1d300da14fc74bf8c1d13cd6d0"
            "5c9908c836a2b70937bb60c095bb9c99"
        ),
        "next_window": {
            "execution_permitted": False,
            "fresh_window_policy_required": True,
            "maximum_concurrency": 4,
            "maximum_provider_samples": 30,
        },
        "operator_decision_hash": (
            "sha256:bb7c3a3c077fa3471c2b84e83ad1a698"
            "e9246aa2662b96ae7b1468376a7ac510"
        ),
        "production_cutover_permitted": False,
        "receipt_hash": (
            "sha256:fae6534f558766d59f5eab53084cbc9e4"
            "79f0de619bc30529ccba611f89988af"
        ),
        "receipt_schema_version": (
            "cx_answer_support_limited_shadow_operator_review_receipt.v1"
        ),
        "source_evidence_hash": (
            "sha256:1a57b1194a2c01438fd14e7aa92b7fcb"
            "44d11da45af9ba1362c68dba2184ea92"
        ),
        "source_report_document_hash": (
            "sha256:0934fe6ca79cfadeee615fd03b10770e6"
            "31bb7f5991153a940f29407d7307e34"
        ),
        "status": "PASS",
        "user_visible_decision_change_permitted": False,
    }
