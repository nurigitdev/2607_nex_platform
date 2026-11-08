from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_cx.retrieval_answer_support_interactive_slo_policy import (
    DECISION,
    InteractiveSloPolicyError,
    _hash_ref,
    _profile,
    _profiles,
    _timestamp,
    build_interactive_slo_operator_decision,
    decide_interactive_slo_runtime_policy,
    validate_interactive_slo_policy_design,
)
from nex_cx.retrieval_answer_support_sync_capacity import (
    evaluate_sync_capacity_receipt,
    validate_sync_capacity_design,
)
from nex_cx.retrieval_answer_support_sync_capacity_control import (
    evaluate_sync_capacity_control_receipt,
    validate_sync_capacity_control_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_sync_capacity_control import (
    _control_receipt,
)
from test_nex_cx_retrieval_answer_support_sync_capacity_control import (
    _fixtures as capacity_fixtures,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-11-05T08:00:00Z"


def test_interactive_slo_policy_selects_bounded_sync_c4_pending_acceptance() -> None:
    fixtures = _fixtures()
    operator = build_interactive_slo_operator_decision(
        operator_id="operator-one",
        decided_at=NOW,
        design=fixtures["design"],
        capacity_manifest=fixtures["capacity_manifest"],
        control_manifest=fixtures["control_manifest"],
    )
    manifest = decide_interactive_slo_runtime_policy(
        design=fixtures["design"],
        capacity_manifest=fixtures["capacity_manifest"],
        control_manifest=fixtures["control_manifest"],
        operator_decision=operator,
    )
    policy = manifest["selected_policy"]
    assert manifest["decision"] == DECISION
    assert policy["slo_profile"] == {
        "prompt_acceptance_feedback_p95_latency_ms": 2_000,
        "generation_provider_p95_latency_ms": 15_000,
        "interactive_final_response_e2e_p95_latency_ms": 20_000,
        "background_provider_p95_latency_ms": 45_000,
        "request_timeout_ms": 60_000,
    }
    assert policy["runtime_policy"]["execution_mode"] == "SYNCHRONOUS"
    assert policy["runtime_policy"]["maximum_in_flight_provider_requests"] == 4
    assert manifest["observed_capacity"]["selected_concurrency"] == 4
    assert (
        manifest["observed_capacity"]["maximum_fresh_provider_p95_latency_ms"]
        == 11_000.0
    )
    assert manifest["execution_mode_selected"] is True
    assert manifest["runtime_activation_permitted"] is False
    assert manifest["production_cutover_permitted"] is False
    assert len(manifest["pending_acceptance"]) == 3


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        (None, "status", "DRAFT"),
        ("slo_profile", "generation_provider_p95_latency_ms", 8_000),
        ("runtime_policy", "maximum_in_flight_provider_requests", 8),
        ("decision_policy", "maximum_provider_errors", 1),
        ("safety", "runtime_activation_permitted", True),
    ],
)
def test_policy_design_rejects_identity_and_policy_drift(
    section: str | None, field: str, value: object
) -> None:
    design = deepcopy(_fixtures()["design"])
    target = design if section is None else design[section]
    target[field] = value
    with pytest.raises(InteractiveSloPolicyError):
        validate_interactive_slo_policy_design(design)


def test_policy_design_accepts_matching_hash_and_rejects_stale_hash() -> None:
    design = deepcopy(_fixtures()["design"])
    normalized = validate_interactive_slo_policy_design(design)
    design["design_hash"] = normalized["design_hash"]
    assert (
        validate_interactive_slo_policy_design(design)["design_hash"]
        == design["design_hash"]
    )
    design["design_hash"] = "sha256:" + "f" * 64
    with pytest.raises(InteractiveSloPolicyError) as raised:
        validate_interactive_slo_policy_design(design)
    assert raised.value.error_code == "INTERACTIVE_SLO_POLICY_INTEGRITY"


def test_policy_rejects_manifest_tamper_control_drift_and_provider_slo_miss() -> None:
    fixtures = _fixtures()
    tampered = deepcopy(fixtures["capacity_manifest"])
    tampered["decision"] = "TAMPERED"
    with pytest.raises(InteractiveSloPolicyError) as raised:
        build_interactive_slo_operator_decision(
            operator_id="operator",
            decided_at=NOW,
            design=fixtures["design"],
            capacity_manifest=tampered,
            control_manifest=fixtures["control_manifest"],
        )
    assert raised.value.error_code == "INTERACTIVE_SLO_POLICY_INTEGRITY"

    control = deepcopy(fixtures["control_manifest"])
    control["observation"] = "MIXED_OR_INCONCLUSIVE"
    _rehash_manifest(control)
    design = _bind_manifest(fixtures["design"], control=control)
    with pytest.raises(InteractiveSloPolicyError):
        build_interactive_slo_operator_decision(
            operator_id="operator",
            decided_at=NOW,
            design=design,
            capacity_manifest=fixtures["capacity_manifest"],
            control_manifest=control,
        )

    capacity = deepcopy(fixtures["capacity_manifest"])
    capacity["profile_assessments"][2]["p95_latency_ms"] = 16_000.0
    capacity["profile_assessments"][2]["maximum_latency_ms"] = 16_500.0
    _rehash_manifest(capacity)
    design = _bind_manifest(fixtures["design"], capacity=capacity)
    with pytest.raises(InteractiveSloPolicyError):
        build_interactive_slo_operator_decision(
            operator_id="operator",
            decided_at=NOW,
            design=design,
            capacity_manifest=capacity,
            control_manifest=fixtures["control_manifest"],
        )


def test_policy_rejects_non_c4_selection_and_operator_decision_tamper() -> None:
    fixtures = _fixtures()
    capacity = deepcopy(fixtures["capacity_manifest"])
    capacity["profile_assessments"][1]["throughput_rps"] = 0.5
    _rehash_manifest(capacity)
    design = _bind_manifest(fixtures["design"], capacity=capacity)
    with pytest.raises(InteractiveSloPolicyError):
        build_interactive_slo_operator_decision(
            operator_id="operator",
            decided_at=NOW,
            design=design,
            capacity_manifest=capacity,
            control_manifest=fixtures["control_manifest"],
        )

    operator = build_interactive_slo_operator_decision(
        operator_id="operator",
        decided_at=NOW,
        design=fixtures["design"],
        capacity_manifest=fixtures["capacity_manifest"],
        control_manifest=fixtures["control_manifest"],
    )
    operator["runtime_activation_approved"] = True
    operator["decision_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in operator.items() if key != "decision_hash"}
    )
    with pytest.raises(InteractiveSloPolicyError):
        decide_interactive_slo_runtime_policy(
            design=fixtures["design"],
            capacity_manifest=fixtures["capacity_manifest"],
            control_manifest=fixtures["control_manifest"],
            operator_decision=operator,
        )


def test_policy_rejects_stale_source_binding_and_operator_hash() -> None:
    fixtures = _fixtures()
    stale_design = deepcopy(fixtures["design"])
    stale_design["source_binding"]["capacity_receipt_hash"] = "sha256:" + "f" * 64
    with pytest.raises(InteractiveSloPolicyError) as raised:
        build_interactive_slo_operator_decision(
            operator_id="operator",
            decided_at=NOW,
            design=stale_design,
            capacity_manifest=fixtures["capacity_manifest"],
            control_manifest=fixtures["control_manifest"],
        )
    assert raised.value.error_code == "INTERACTIVE_SLO_POLICY_INTEGRITY"

    operator = build_interactive_slo_operator_decision(
        operator_id="operator",
        decided_at=NOW,
        design=fixtures["design"],
        capacity_manifest=fixtures["capacity_manifest"],
        control_manifest=fixtures["control_manifest"],
    )
    operator["operator_id"] = "tampered"
    with pytest.raises(InteractiveSloPolicyError) as raised:
        decide_interactive_slo_runtime_policy(
            design=fixtures["design"],
            capacity_manifest=fixtures["capacity_manifest"],
            control_manifest=fixtures["control_manifest"],
            operator_decision=operator,
        )
    assert raised.value.error_code == "INTERACTIVE_SLO_POLICY_INTEGRITY"


@pytest.mark.parametrize("value", ["profiles", [None], [{"concurrency": 3}]])
def test_policy_rejects_malformed_capacity_profile_collections(value: object) -> None:
    with pytest.raises(InteractiveSloPolicyError):
        _profiles(value)


def test_policy_helpers_reject_invalid_profiles_hashes_and_timestamps() -> None:
    with pytest.raises(InteractiveSloPolicyError):
        validate_interactive_slo_policy_design([])  # type: ignore[arg-type]
    with pytest.raises(InteractiveSloPolicyError):
        validate_interactive_slo_policy_design({})
    with pytest.raises(InteractiveSloPolicyError):
        _profile([], 1)
    with pytest.raises(InteractiveSloPolicyError):
        _profile({}, 1)
    with pytest.raises(InteractiveSloPolicyError):
        _profile(
            {
                "concurrency": 1,
                "error_count": -1,
                "p95_latency_ms": 1.0,
                "maximum_latency_ms": 2.0,
                "throughput_rps": 1.0,
                "request_count": 1,
            },
            1,
        )
    with pytest.raises(InteractiveSloPolicyError):
        _hash_ref(None, "hash")
    with pytest.raises(InteractiveSloPolicyError):
        _hash_ref("bad", "hash")
    for timestamp in ("", "2026-11-05", "badZ"):
        with pytest.raises(InteractiveSloPolicyError):
            _timestamp(timestamp, "timestamp")


def _fixtures() -> dict:
    source = capacity_fixtures()
    capacity_design = source["capacity_design"]
    control_design = source["control_design"]
    capacity_receipt = source["capacity_receipt"]
    control_receipt = _control_receipt(source)
    capacity_manifest = evaluate_sync_capacity_receipt(
        capacity_receipt, design=capacity_design
    )
    control_manifest = evaluate_sync_capacity_control_receipt(
        control_receipt,
        design=control_design,
        capacity_receipt=capacity_receipt,
    )
    design = json.loads(
        (
            ROOT
            / "scripts/smoke/data/s136_answer_support_interactive_slo_policy_v1_design.json"
        ).read_text(encoding="utf-8")
    )
    design["source_binding"].update(
        {
            "capacity_design_hash": validate_sync_capacity_design(capacity_design)[
                "design_hash"
            ],
            "capacity_manifest_hash": capacity_manifest["manifest_hash"],
            "capacity_receipt_hash": capacity_receipt["receipt_hash"],
            "control_design_hash": validate_sync_capacity_control_design(
                control_design
            )["design_hash"],
            "control_manifest_hash": control_manifest["manifest_hash"],
            "control_receipt_hash": control_receipt["receipt_hash"],
            "provider_binding_hash": capacity_receipt["source_binding"][
                "provider_binding_hash"
            ],
        }
    )
    return {
        **source,
        "design": design,
        "capacity_receipt": capacity_receipt,
        "control_receipt": control_receipt,
        "capacity_manifest": capacity_manifest,
        "control_manifest": control_manifest,
    }


def _rehash_manifest(value: dict) -> None:
    value.pop("manifest_hash", None)
    value["manifest_hash"] = semantic_sha256_hash_ref(value)


def _bind_manifest(
    design: dict, *, capacity: dict | None = None, control: dict | None = None
) -> dict:
    result = deepcopy(design)
    if capacity is not None:
        result["source_binding"]["capacity_manifest_hash"] = capacity["manifest_hash"]
    if control is not None:
        result["source_binding"]["control_manifest_hash"] = control["manifest_hash"]
    return result
