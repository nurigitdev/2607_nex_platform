from __future__ import annotations

from nex_cx.retrieval_answer_support_runtime_composition import (
    build_installed_answer_support_runtime_composition,
)
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter


class _GenerationClient:
    def create_generation(self, payload, *, request_id, trace_id):
        raise AssertionError("composition construction must not call the provider")

    @staticmethod
    def snapshot():
        return {
            "provider_latencies_ms": [],
            "feedback_latencies_ms": [],
            "request_count": 0,
            "failure_count": 0,
        }


def _dependencies():
    store = InMemoryOperationalEventStore()
    return store, OperationalEventEmitter(service_id="nex-cx", store=store)


def test_composition_preserves_disabled_product_runtime() -> None:
    store, emitter = _dependencies()

    runtime = build_installed_answer_support_runtime_composition(
        environ={},
        generation_client=_GenerationClient(),
        emitter=emitter,
        store=store,
    )

    assert runtime.primary_policy is None
    assert runtime.policy_cutover is None
    assert runtime.steady_state_policy is None
    assert runtime.retrieval_shadow_observer is None
    assert runtime.safe_snapshot() == {
        "primary_policy_installed": False,
        "steady_state_policy_installed": False,
        "cutover_policy_installed": False,
        "shadow_observer_installed": False,
        "selected_policy_hash": None,
        "steady_state_state": None,
        "steady_state_reason_code": None,
        "cutover_state": None,
        "cutover_reason_code": None,
    }


def test_composition_installs_canonical_controlled_steady_state_runtime() -> None:
    store, emitter = _dependencies()

    runtime = build_installed_answer_support_runtime_composition(
        environ={
            "NEX_CX_ANSWER_SUPPORT_POLICY_MODE": "CONTROLLED",
            "NEX_CX_ANSWER_SUPPORT_STEADY_STATE_MODE": "CONTROLLED",
        },
        generation_client=_GenerationClient(),
        emitter=emitter,
        store=store,
    )
    snapshot = runtime.safe_snapshot()

    assert runtime.primary_policy is runtime.steady_state_policy
    assert runtime.policy_cutover is not None
    assert runtime.retrieval_shadow_observer is None
    assert snapshot["primary_policy_installed"] is True
    assert snapshot["steady_state_policy_installed"] is True
    assert snapshot["cutover_policy_installed"] is True
    assert snapshot["selected_policy_hash"] == (
        "sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb"
    )
    assert snapshot["steady_state_state"] == "ACTIVE"
    assert snapshot["cutover_state"] == "ACTIVE"
