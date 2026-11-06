from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_cx.retrieval_answer_support_controlled_activation import (
    OperationalAnswerSupportProgressSink,
)
from nex_cx.retrieval_answer_support_policy_cutover import (
    ACTIVE,
    CUTOVER_MODE_CONTROLLED,
    CUTOVER_MODE_ENV,
    ROLLED_BACK,
    OperationalPolicyCutoverStateStore,
    build_installed_answer_support_policy_cutover,
)
from nex_cx.retrieval_answer_support_policy_steady_state import (
    DEFAULT_AUTHORIZATION_PATH,
    STEADY_STATE_EVENT_TYPE,
    STEADY_STATE_MODE_CONTROLLED,
    STEADY_STATE_MODE_ENV,
    AnswerSupportPolicySteadyStateError,
    OperationalSteadyStateStateStore,
    _hash_ref,
    _mapping,
    _required_text,
    build_installed_answer_support_policy_steady_state,
    build_steady_state_state,
    load_steady_state_authorization,
    validate_steady_state_authorization,
    validate_steady_state_state,
)
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_policy_cutover import (
    FakeGenerationClient,
    RecordingOutcomeSink,
    _application,
    _package,
)


def test_authorization_binds_exact_pam_receipt_and_profile() -> None:
    authorization = load_steady_state_authorization(DEFAULT_AUTHORIZATION_PATH)

    assert authorization["status"] == (
        "APPROVED_FOR_CONTROLLED_STEADY_STATE_OPERATIONS"
    )
    assert authorization["decision_receipt"]["steady_state_operations_approved"]
    assert authorization["operations_profile"]["review_sample_interval"] == 12
    assert authorization["operations_profile"]["maximum_concurrency"] == 4

    for field in (
        "authorization_hash",
        "cutover_authorization_hash",
        "activation_bundle_hash",
        "selected_policy_hash",
        "sustained_policy_hash",
    ):
        drift = deepcopy(authorization)
        drift[field] = "sha256:" + "0" * 64
        with pytest.raises(AnswerSupportPolicySteadyStateError):
            validate_steady_state_authorization(drift)


def test_runtime_is_disabled_by_default_and_requires_cutover_delegate() -> None:
    state_store, _events = _steady_state_store()
    assert (
        build_installed_answer_support_policy_steady_state(
            environ={}, delegate=None, state_store=state_store
        )
        is None
    )
    with pytest.raises(AnswerSupportPolicySteadyStateError):
        build_installed_answer_support_policy_steady_state(
            environ={STEADY_STATE_MODE_ENV: "UNKNOWN"},
            delegate=None,
            state_store=state_store,
        )
    with pytest.raises(AnswerSupportPolicySteadyStateError) as raised:
        build_installed_answer_support_policy_steady_state(
            environ={STEADY_STATE_MODE_ENV: STEADY_STATE_MODE_CONTROLLED},
            delegate=None,
            state_store=state_store,
        )
    assert raised.value.error_code == "CX_ANSWER_SUPPORT_STEADY_STATE_BINDING_DRIFT"


def test_active_runtime_preserves_cutover_result_and_restart_state() -> None:
    events = InMemoryOperationalEventStore()
    cutover = _cutover(events, FakeGenerationClient())
    steady_store = _steady_store(events)
    runtime = _steady(cutover, steady_store)

    result = runtime.apply(**_application(_package()))
    snapshot = runtime.snapshot()

    assert result["status"] == "READY"
    assert snapshot["cutover_state"] == ACTIVE
    assert snapshot["steady_state_state"] == ACTIVE
    assert snapshot["steady_state_operations_active"] is True
    assert snapshot["production_cutover"] is False
    assert len(events.list_events(event_type=STEADY_STATE_EVENT_TYPE)) == 1

    restarted_cutover = _cutover(events, FakeGenerationClient())
    restarted = _steady(restarted_cutover, steady_store)
    assert restarted.snapshot()["steady_state_state"] == ACTIVE
    assert len(events.list_events(event_type=STEADY_STATE_EVENT_TYPE)) == 1


def test_snapshot_reads_delegate_state_once(monkeypatch) -> None:
    events = InMemoryOperationalEventStore()
    cutover = _cutover(events, FakeGenerationClient())
    runtime = _steady(cutover, _steady_store(events))
    original_snapshot = cutover.snapshot
    calls = 0

    def counted_snapshot():
        nonlocal calls
        calls += 1
        return original_snapshot()

    monkeypatch.setattr(cutover, "snapshot", counted_snapshot)

    assert runtime.snapshot()["steady_state_state"] == ACTIVE
    assert calls == 1


def test_delegate_rollback_dominates_and_is_restart_safe() -> None:
    events = InMemoryOperationalEventStore()
    cutover = _cutover(
        events, FakeGenerationClient(error=RuntimeError("provider failed"))
    )
    steady_store = _steady_store(events)
    runtime = _steady(cutover, steady_store)

    incumbent = _package()
    assert runtime.apply(**_application(incumbent)) == incumbent
    snapshot = runtime.snapshot()
    assert snapshot["cutover_state"] == ROLLED_BACK
    assert snapshot["steady_state_state"] == ROLLED_BACK
    assert snapshot["steady_state_operations_active"] is False
    assert snapshot["steady_state_reason_code"] == "PROVIDER_ERROR"

    restarted_cutover = _cutover(events, FakeGenerationClient())
    restarted = _steady(restarted_cutover, steady_store)
    assert restarted.snapshot()["steady_state_state"] == ROLLED_BACK
    assert restarted.apply(**_application(incumbent)) == incumbent


def test_binding_drift_and_state_tamper_fail_closed() -> None:
    events = InMemoryOperationalEventStore()
    cutover = _cutover(events, FakeGenerationClient())
    cutover._authorization["selected_policy_hash"] = "sha256:" + "1" * 64
    with pytest.raises(AnswerSupportPolicySteadyStateError):
        _steady(cutover, _steady_store(events))

    authorization = load_steady_state_authorization(DEFAULT_AUTHORIZATION_PATH)
    state = build_steady_state_state(
        authorization=authorization,
        steady_state_state=ACTIVE,
        reason_code="ACTIVATED",
    )
    state["production_cutover"] = True
    with pytest.raises(AnswerSupportPolicySteadyStateError):
        validate_steady_state_state(state)

    resealed = build_steady_state_state(
        authorization=authorization,
        steady_state_state=ACTIVE,
        reason_code="ACTIVATED",
    )
    resealed["selected_policy_hash"] = "sha256:" + "2" * 64
    unsigned = dict(resealed)
    unsigned.pop("state_hash")
    resealed["state_hash"] = semantic_sha256_hash_ref(unsigned)
    store = _steady_store(events)
    store.record_state(resealed)
    with pytest.raises(AnswerSupportPolicySteadyStateError):
        _steady(_cutover(events, FakeGenerationClient()), store)


def test_store_skips_unrelated_events_and_terminal_state_dominates() -> None:
    events = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=events)
    store = OperationalSteadyStateStateStore(emitter, events)
    authorization = load_steady_state_authorization(DEFAULT_AUTHORIZATION_PATH)
    auth_hash = authorization["authorization_hash"]
    malformed = emitter.emit(
        event_type=STEADY_STATE_EVENT_TYPE,
        severity="INFO",
        message="unrelated",
        details={},
    )
    events.events[malformed["event_id"]]["details"] = "bad"
    unrelated = build_steady_state_state(
        authorization=authorization,
        steady_state_state=ACTIVE,
        reason_code="OTHER",
    )
    unrelated["steady_state_receipt_hash"] = "sha256:" + "9" * 64
    emitter.emit(
        event_type=STEADY_STATE_EVENT_TYPE,
        severity="INFO",
        message="unrelated",
        details=unrelated,
    )
    assert store.current_state(auth_hash) is None
    store.record_state(
        build_steady_state_state(
            authorization=authorization,
            steady_state_state=ACTIVE,
            reason_code="ACTIVATED",
        )
    )
    store.record_state(
        build_steady_state_state(
            authorization=authorization,
            steady_state_state=ROLLED_BACK,
            reason_code="PROVIDER_ERROR",
        )
    )
    assert store.current_state(auth_hash)["steady_state_state"] == ROLLED_BACK


def test_loading_and_primitive_guards_reject_malformed_values(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(AnswerSupportPolicySteadyStateError):
        load_steady_state_authorization(missing)
    malformed = tmp_path / "invalid.json"
    malformed.write_text("[]", encoding="utf-8")
    with pytest.raises(AnswerSupportPolicySteadyStateError):
        load_steady_state_authorization(malformed)

    authorization = load_steady_state_authorization(DEFAULT_AUTHORIZATION_PATH)
    extra = deepcopy(authorization)
    extra["extra"] = True
    unsigned = dict(extra)
    unsigned.pop("authorization_hash")
    extra["authorization_hash"] = semantic_sha256_hash_ref(unsigned)
    with pytest.raises(AnswerSupportPolicySteadyStateError):
        validate_steady_state_authorization(extra)

    bad_receipt = deepcopy(authorization)
    bad_receipt["decision_receipt"]["status"] = "FAIL"
    receipt = dict(bad_receipt["decision_receipt"])
    receipt.pop("receipt_hash")
    bad_receipt["decision_receipt"]["receipt_hash"] = semantic_sha256_hash_ref(
        receipt
    )
    outer = dict(bad_receipt)
    outer.pop("authorization_hash")
    bad_receipt["authorization_hash"] = semantic_sha256_hash_ref(outer)
    with pytest.raises(AnswerSupportPolicySteadyStateError):
        validate_steady_state_authorization(bad_receipt)

    stale_receipt_hash = deepcopy(authorization)
    stale_receipt_hash["decision_receipt"]["status"] = "FAIL"
    outer = dict(stale_receipt_hash)
    outer.pop("authorization_hash")
    stale_receipt_hash["authorization_hash"] = semantic_sha256_hash_ref(outer)
    with pytest.raises(AnswerSupportPolicySteadyStateError):
        validate_steady_state_authorization(stale_receipt_hash)

    stale_profile_hash = deepcopy(authorization)
    stale_profile_hash["operations_profile"]["status"] = "DRAFT"
    outer = dict(stale_profile_hash)
    outer.pop("authorization_hash")
    stale_profile_hash["authorization_hash"] = semantic_sha256_hash_ref(outer)
    with pytest.raises(AnswerSupportPolicySteadyStateError):
        validate_steady_state_authorization(stale_profile_hash)

    bad_receipt_fields = deepcopy(authorization)
    bad_receipt_fields["decision_receipt"]["extra"] = True
    outer = dict(bad_receipt_fields)
    outer.pop("authorization_hash")
    bad_receipt_fields["authorization_hash"] = semantic_sha256_hash_ref(outer)
    with pytest.raises(AnswerSupportPolicySteadyStateError):
        validate_steady_state_authorization(bad_receipt_fields)

    for call in (
        lambda: _mapping([], "mapping"),
        lambda: _hash_ref("bad"),
        lambda: _required_text(""),
    ):
        with pytest.raises(AnswerSupportPolicySteadyStateError):
            call()


def _cutover(events, client):
    emitter = OperationalEventEmitter(service_id="nex-cx", store=events)
    state_store = OperationalPolicyCutoverStateStore(emitter, events)
    runtime = build_installed_answer_support_policy_cutover(
        environ={CUTOVER_MODE_ENV: CUTOVER_MODE_CONTROLLED},
        generation_client=client,
        progress_sink=OperationalAnswerSupportProgressSink(emitter),
        outcome_sink=RecordingOutcomeSink(),
        state_store=state_store,
    )
    assert runtime is not None
    return runtime


def _steady_store(events):
    return OperationalSteadyStateStateStore(
        OperationalEventEmitter(service_id="nex-cx", store=events), events
    )


def _steady_state_store():
    events = InMemoryOperationalEventStore()
    return _steady_store(events), events


def _steady(cutover, state_store):
    runtime = build_installed_answer_support_policy_steady_state(
        environ={STEADY_STATE_MODE_ENV: STEADY_STATE_MODE_CONTROLLED},
        delegate=cutover,
        state_store=state_store,
    )
    assert runtime is not None
    return runtime
