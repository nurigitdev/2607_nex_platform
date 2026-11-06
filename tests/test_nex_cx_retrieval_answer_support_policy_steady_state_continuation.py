from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_cx.retrieval_answer_support_policy_steady_state_operations import (
    POLICY_PATH_ENV,
    WINDOW_EVENT_TYPE,
    PolicySteadyStateOperationsError,
    _ensure_window_open,
    build_installed_policy_steady_state_operations_source,
    validate_policy_steady_state_operations_policy,
)
from nex_runtime import InMemoryOperationalEventStore
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_policy_cutover_operations import _emitter
from test_nex_cx_retrieval_answer_support_policy_steady_state_operations import (
    NOW,
    _policy,
    _runtime,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = (
    ROOT / "services/nex-cx/nex_cx/data/"
    "answer_support_policy_steady_state_continuation.v1.json"
)


def test_continuation_policy_is_bound_to_pap_review() -> None:
    policy = _continuation_policy()

    assert validate_policy_steady_state_operations_policy(policy) == policy
    assert policy["source_review"]["decision_receipt_hash"] == (
        "sha256:adf95c82d9c5d3ec0adec71c93231f7ed9a50e68ffd94c7e2420a0ffce7985fd"
    )
    assert validate_policy_steady_state_operations_policy(_policy()) == _policy()

    for mutate in (
        lambda value: value["source_review"].update(decision_status="REJECTED"),
        lambda value: value.update(
            status="APPROVED_FOR_CONTROLLED_STEADY_STATE_OPERATIONS"
        ),
        lambda value: value.update(policy_schema_version="wrong"),
    ):
        drift = deepcopy(policy)
        mutate(drift)
        _rehash(drift)
        with pytest.raises(PolicySteadyStateOperationsError):
            validate_policy_steady_state_operations_policy(drift)


def test_continuation_opens_isolated_receipt_bound_window() -> None:
    events, steady = _runtime()
    source = build_installed_policy_steady_state_operations_source(
        environ={POLICY_PATH_ENV: str(POLICY_PATH)},
        store=events,
        emitter=_emitter(events),
        runtime_snapshot=steady.snapshot,
    )

    snapshot = source.snapshot(generated_at=NOW)

    assert snapshot["operations_status"] == "MONITORING"
    assert snapshot["policy"]["policy_hash"] == _continuation_policy()["policy_hash"]
    assert (
        snapshot["policy"]["continuation_receipt_hash"]
        == (_continuation_policy()["source_review"]["decision_receipt_hash"])
    )
    assert snapshot["window"]["window_id"] != _policy()["steady_state_window_id"]
    window = events.list_events(event_type=WINDOW_EVENT_TYPE)[0]
    assert (
        window["details"]["continuation_receipt_hash"]
        == (_continuation_policy()["source_review"]["decision_receipt_hash"])
    )


def test_continuation_window_binding_drift_fails_closed() -> None:
    events, steady = _runtime()
    policy = _continuation_policy()
    source = build_installed_policy_steady_state_operations_source(
        environ={POLICY_PATH_ENV: str(POLICY_PATH)},
        store=events,
        emitter=_emitter(events),
        runtime_snapshot=steady.snapshot,
    )
    assert source.snapshot(generated_at=NOW)["window"]["window_state"] == "OPEN"

    event = events.list_events(event_type=WINDOW_EVENT_TYPE)[0]
    event["details"]["continuation_receipt_hash"] = "sha256:" + "0" * 64
    drifted = InMemoryOperationalEventStore(events={event["event_id"]: event})
    with pytest.raises(PolicySteadyStateOperationsError):
        _ensure_window_open(
            emitter=_emitter(drifted),
            store=drifted,
            policy=policy,
            runtime=steady.snapshot(),
        )


def test_canonical_compose_selects_continuation_policy() -> None:
    compose = (ROOT / "deployment/compose/canonical-platform.override.yaml").read_text(
        encoding="utf-8"
    )
    assert (
        "NEX_CX_ANSWER_SUPPORT_STEADY_STATE_OPERATIONS_PATH: "
        "/app/services/nex-cx/nex_cx/data/"
        "answer_support_policy_steady_state_continuation.v1.json"
    ) in compose


def _continuation_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _rehash(policy: dict) -> None:
    policy.pop("policy_hash", None)
    policy["policy_hash"] = semantic_sha256_hash_ref(policy)
