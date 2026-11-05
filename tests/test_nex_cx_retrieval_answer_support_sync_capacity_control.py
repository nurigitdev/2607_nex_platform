from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_cx.retrieval_answer_support_sync_capacity import (
    validate_sync_capacity_design,
)
from nex_cx.retrieval_answer_support_sync_capacity_control import (
    SyncCapacityControlError,
    _exact,
    _hash_ref,
    _mapping,
    _ratio,
    evaluate_sync_capacity_control_receipt,
    validate_sync_capacity_control_design,
    validate_sync_capacity_control_entry,
)
from nex_runtime.model_artifact_revision import model_artifact_revision_evidence_digest
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_gb2_ca00_s20qpw_sync_capacity import _runner_fixtures

ROOT = Path(__file__).resolve().parents[1]


def test_control_design_and_entry_bind_terminal_capacity_evidence() -> None:
    fixtures = _fixtures()
    normalized = validate_sync_capacity_control_entry(
        design=fixtures["control_design"],
        capacity_receipt=fixtures["capacity_receipt"],
        artifact_evidence_hash=fixtures["artifact_hash"],
    )
    assert normalized["design_hash"] == fixtures["control_design_hash"]
    assert normalized["control_experiment"]["concurrency"] == 1


@pytest.mark.parametrize(
    ("control_p95", "error_count", "expected"),
    [
        (11_000.0, 0, "ORIGINAL_C1_TEMPORAL_CONFOUND_LIKELY"),
        (30_000.0, 0, "CONCURRENCY_OR_BATCHING_EFFECT_PLAUSIBLE"),
        (14_000.0, 0, "MIXED_OR_INCONCLUSIVE"),
        (11_000.0, 1, "TRAILING_CONTROL_FAILED"),
    ],
)
def test_control_evaluator_classifies_observation_without_cutover(
    control_p95: float, error_count: int, expected: str
) -> None:
    fixtures = _fixtures()
    receipt = _control_receipt(fixtures, p95=control_p95, error_count=error_count)
    manifest = evaluate_sync_capacity_control_receipt(
        receipt,
        design=fixtures["control_design"],
        capacity_receipt=fixtures["capacity_receipt"],
    )
    assert manifest["observation"] == expected
    assert manifest["causal_concurrency_attribution_permitted"] is False
    assert manifest["execution_mode_selected"] is False
    assert manifest["runtime_activation_permitted"] is False
    assert manifest["production_cutover_permitted"] is False


def test_control_evaluator_reports_slo_and_ratios() -> None:
    fixtures = _fixtures()
    manifest = evaluate_sync_capacity_control_receipt(
        _control_receipt(fixtures, p95=11_000.0),
        design=fixtures["control_design"],
        capacity_receipt=fixtures["capacity_receipt"],
    )
    assert manifest["p95_ratio_trailing_to_original_c1"] == 0.275
    assert manifest["p95_ratio_trailing_to_c2"] == 1.1
    assert manifest["p95_ratio_trailing_to_c4"] == 1.0
    assert manifest["background_slo_met"] is True
    assert manifest["timeout_bound_met"] is True


def test_control_contract_rejects_design_receipt_and_source_tampering() -> None:
    fixtures = _fixtures()
    invalid_design = deepcopy(fixtures["control_design"])
    invalid_design["control_experiment"]["maximum_provider_calls"] = 31
    with pytest.raises(SyncCapacityControlError) as raised:
        validate_sync_capacity_control_design(invalid_design)
    assert raised.value.error_code == "SYNC_CAPACITY_CONTROL_INVALID"

    receipt = _control_receipt(fixtures)
    receipt["control_profile"]["p95_latency_ms"] = 12_000.0
    with pytest.raises(SyncCapacityControlError) as raised:
        evaluate_sync_capacity_control_receipt(
            receipt,
            design=fixtures["control_design"],
            capacity_receipt=fixtures["capacity_receipt"],
        )
    assert raised.value.error_code == "SYNC_CAPACITY_CONTROL_INTEGRITY"

    with pytest.raises(SyncCapacityControlError):
        validate_sync_capacity_control_entry(
            design=fixtures["control_design"],
            capacity_receipt={**fixtures["capacity_receipt"], "status": "FAIL"},
            artifact_evidence_hash=fixtures["artifact_hash"],
        )


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        (None, "status", "DRAFT"),
        ("comparison_policy", "maximum_error_count", 1),
        ("safety", "database_call_permitted", True),
    ],
)
def test_control_design_rejects_identity_policy_and_safety_drift(
    section: str | None, field: str, value: object
) -> None:
    design = deepcopy(_fixtures()["control_design"])
    target = design if section is None else design[section]
    target[field] = value
    with pytest.raises(SyncCapacityControlError):
        validate_sync_capacity_control_design(design)


def test_control_design_rejects_stale_supplied_hash() -> None:
    design = deepcopy(_fixtures()["control_design"])
    design["design_hash"] = "sha256:" + "f" * 64
    with pytest.raises(SyncCapacityControlError) as raised:
        validate_sync_capacity_control_design(design)
    assert raised.value.error_code == "SYNC_CAPACITY_CONTROL_INTEGRITY"


def test_control_contract_rejects_invalid_capacity_profiles_and_metrics() -> None:
    fixtures = _fixtures()
    capacity = deepcopy(fixtures["capacity_receipt"])
    capacity["profiles"] = capacity["profiles"][:2]
    with pytest.raises(SyncCapacityControlError):
        evaluate_sync_capacity_control_receipt(
            _control_receipt(fixtures),
            design=fixtures["control_design"],
            capacity_receipt=capacity,
        )

    receipt = _control_receipt(fixtures)
    receipt["control_profile"]["maximum_latency_ms"] = 1.0
    _rehash(receipt)
    with pytest.raises(SyncCapacityControlError):
        evaluate_sync_capacity_control_receipt(
            receipt,
            design=fixtures["control_design"],
            capacity_receipt=fixtures["capacity_receipt"],
        )

    capacity = deepcopy(fixtures["capacity_receipt"])
    capacity["profiles"] = "invalid"
    with pytest.raises(SyncCapacityControlError):
        evaluate_sync_capacity_control_receipt(
            _control_receipt(fixtures),
            design=fixtures["control_design"],
            capacity_receipt=capacity,
        )


def test_control_contract_rejects_receipt_boundary_and_invalid_primitives() -> None:
    fixtures = _fixtures()
    receipt = _control_receipt(fixtures)
    receipt["holdout_accessed"] = True
    _rehash(receipt)
    with pytest.raises(SyncCapacityControlError):
        evaluate_sync_capacity_control_receipt(
            receipt,
            design=fixtures["control_design"],
            capacity_receipt=fixtures["capacity_receipt"],
        )

    with pytest.raises(SyncCapacityControlError):
        _mapping([], "mapping")
    with pytest.raises(SyncCapacityControlError):
        _exact({"unexpected": True}, {"expected"}, "exact")
    with pytest.raises(SyncCapacityControlError):
        _hash_ref("invalid", "hash")
    with pytest.raises(SyncCapacityControlError):
        _hash_ref(None, "hash")
    with pytest.raises(SyncCapacityControlError):
        _ratio(1.0, 0.0)


def _fixtures() -> dict:
    capacity_fixtures = _runner_fixtures()
    capacity_design = capacity_fixtures["design"]
    normalized_capacity = validate_sync_capacity_design(capacity_design)
    profiles = [
        _profile(1, "P_V_BASELINE_RECEIPT", 40_000.0, 0.035),
        _profile(2, "SYNCHRONOUS_LIVE_REPLAY", 10_000.0, 0.198),
        _profile(4, "SYNCHRONOUS_LIVE_REPLAY", 11_000.0, 0.362),
    ]
    capacity_receipt = {
        "receipt_schema_version": "cx_answer_support_sync_capacity_receipt.v1",
        "status": "PASS",
        "design_hash": normalized_capacity["design_hash"],
        "source_binding": dict(normalized_capacity["source_binding"]),
        "environment_observation": {
            "evidence_level": "BOUND_ENDPOINT_REACHABILITY_PROXY",
            "operator_declared_vllm_max_num_seqs": 4,
            "port_reachability": {"9112": True, "9113": True, "9116": True},
        },
        "profiles": profiles,
        "provider_http_requests": 60,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    _rehash(capacity_receipt)
    control_design = json.loads(
        (
            ROOT
            / "scripts/smoke/data/s136_answer_support_sync_capacity_c1_control_v1_design.json"
        ).read_text(encoding="utf-8")
    )
    control_design["source_binding"].update(
        {
            "artifact_evidence_hash": model_artifact_revision_evidence_digest(
                capacity_fixtures["artifact_evidence"]
            ),
            "capacity_design_hash": normalized_capacity["design_hash"],
            "capacity_receipt_hash": capacity_receipt["receipt_hash"],
            "case_set_hash": normalized_capacity["source_binding"]["case_set_hash"],
            "provider_binding_hash": normalized_capacity["source_binding"][
                "provider_binding_hash"
            ],
            "request_profile_hash": normalized_capacity["source_binding"][
                "request_profile_hash"
            ],
            "signal_design_hash": normalized_capacity["source_binding"][
                "signal_design_hash"
            ],
        }
    )
    normalized_control = validate_sync_capacity_control_design(control_design)
    return {
        **capacity_fixtures,
        "capacity_design": capacity_design,
        "capacity_receipt": capacity_receipt,
        "control_design": control_design,
        "control_design_hash": normalized_control["design_hash"],
        "artifact_hash": model_artifact_revision_evidence_digest(
            capacity_fixtures["artifact_evidence"]
        ),
    }


def _control_receipt(
    fixtures: dict, *, p95: float = 11_000.0, error_count: int = 0
) -> dict:
    receipt = {
        "receipt_schema_version": (
            "cx_answer_support_sync_capacity_control_receipt.v1"
        ),
        "status": "PASS",
        "control_design_hash": fixtures["control_design_hash"],
        "capacity_receipt_hash": fixtures["capacity_receipt"]["receipt_hash"],
        "source_binding": dict(fixtures["control_design"]["source_binding"]),
        "operator_observation": {
            "dgx_idle_confirmed": True,
            "operator_id_hash": "sha256:" + "a" * 64,
            "port_reachability": {"9112": True, "9113": True, "9116": True},
        },
        "control_profile": _profile(
            1,
            "SYNCHRONOUS_LIVE_TRAILING_CONTROL",
            p95,
            0.09,
            error_count=error_count,
        ),
        "provider_http_requests": 30,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    _rehash(receipt)
    return receipt


def _profile(
    concurrency: int,
    source: str,
    p95: float,
    throughput: float,
    *,
    error_count: int = 0,
) -> dict:
    return {
        "concurrency": concurrency,
        "source": source,
        "request_count": 30,
        "provider_request_count": 30,
        "error_count": error_count,
        "latency_sample_count": 30,
        "p95_latency_ms": p95,
        "maximum_latency_ms": p95 + 500.0,
        "elapsed_seconds": 30.0 / throughput,
        "throughput_rps": throughput,
        "total_tokens": 13_900,
    }


def _rehash(value: dict) -> None:
    value.pop("receipt_hash", None)
    value["receipt_hash"] = semantic_sha256_hash_ref(value)
