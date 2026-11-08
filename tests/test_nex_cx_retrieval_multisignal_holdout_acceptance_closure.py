from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_cx.retrieval_multisignal_holdout_acceptance_closure import (
    CLOSURE_STATUS,
    DECISION,
    NEXT_BOUNDARY,
    MultiSignalHoldoutAcceptanceClosureError,
    _exact,
    _hash_ref,
    _mapping,
    build_multisignal_holdout_acceptance_closure,
    validate_multisignal_holdout_acceptance_closure_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT / "scripts/smoke/data/"
    "s136_multi_signal_live_holdout_acceptance_closure_v1_design.json"
)
RETRIEVAL_PATH = ROOT / "reports/live/gb2_ca00_s20qpa_vector_near_tie_ordering.json"
HOLDOUT_PATH = ROOT / "reports/live/gb2_ca00_s20qpq_one_shot_holdout.json"
RECEIPT_PATH = ROOT / "reports/live/gb2_ca00_s20qpq_holdout_one_shot_receipt.json"
OPERATIONS_PATH = (
    ROOT / "reports/live/"
    "gb2_ca00_s20qpas_answer_support_policy_steady_state_operations_"
    "continuation_closure.json"
)
MAINTENANCE_PATH = (
    ROOT / "reports/live/"
    "gb2_ca00_s20qpat_answer_support_policy_controlled_steady_state_"
    "baseline_maintenance.json"
)


def test_closure_reconciles_live_retrieval_holdout_and_operations_evidence() -> None:
    result = _build()

    assert result["status"] == "PASS"
    assert result["decision"] == DECISION
    assert result["closure_status"] == CLOSURE_STATUS
    assert result["next_boundary"] == NEXT_BOUNDARY
    assert result["retrieval_execution"] == {
        "database": "nex_cx_test",
        "role": "nex_cx_user",
        "dataset_id": result["retrieval_execution"]["dataset_id"],
        "dataset_sha256": result["retrieval_execution"]["dataset_sha256"],
        "scenario_count": 80,
        "package_count": 160,
        "candidate_count": 640,
        "embedding_calls": 1440,
        "reranking_calls": 800,
        "provider_failures": 0,
        "cleanup_complete": True,
    }
    assert result["retrieval_binding"]["chunk_policy_id"] == "chunk_1000_100"
    assert result["retrieval_binding"]["ranking_policy_id"] == (
        "weighted_rrf_vector_bm25_v1"
    )
    assert result["holdout_binding"]["profile_id"] == (
        "answer-support-contradiction-aware-v2"
    )
    assert result["holdout_binding"]["threshold"] == 0.46375
    assert result["holdout_metrics"] == {
        "scenario_count": 20,
        "package_count": 40,
        "candidate_count": 160,
        "false_ready_rate": 0.05,
        "ready_recall": 1.0,
        "balanced_accuracy": 0.975,
        "package_auc": 1.0,
        "provider_evaluations": 40,
        "provider_http_requests": 40,
        "authorization_consumed": True,
    }
    assert result["operations_state"]["corrective_chain_closed"] is True
    assert result["maintenance_state"]["maintenance_status"] == (
        "ACTIVE_CONTROLLED_BASELINE_MAINTENANCE"
    )
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert result["holdout_reexecution_permitted"] is False
    assert result["threshold_or_profile_reselection_permitted"] is False
    assert result["runtime_changed"] is False
    assert result["production_cutover_permitted"] is False
    assert result["closure_hash"].startswith("sha256:")


def test_frozen_design_hash_is_reproducible_and_optional_during_validation() -> None:
    design = _load(DESIGN_PATH)
    normalized = validate_multisignal_holdout_acceptance_closure_design(design)
    assert normalized["design_hash"] == design["design_hash"]

    without_hash = deepcopy(design)
    without_hash.pop("design_hash")
    assert validate_multisignal_holdout_acceptance_closure_design(without_hash) == (
        normalized
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("design_schema_version",), "wrong"),
        (("status",), "DRAFT"),
        (("design_id",), ""),
        (("closure_contract", "holdout_reexecution_permitted"), True),
        (("acceptance_requirements", "actual_cx_postgresql_required"), False),
        (("scope_evolution", "backward_retrieval_contract_preserved"), False),
        (("safety", "provider_call_permitted"), True),
        (("source_binding", "selected_policy_hash"), "bad"),
    ],
)
def test_design_semantic_or_hash_drift_fails_closed(
    path: tuple[str, ...], value: object
) -> None:
    design = _load(DESIGN_PATH)
    target = design
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value

    with pytest.raises(MultiSignalHoldoutAcceptanceClosureError):
        validate_multisignal_holdout_acceptance_closure_design(design)

    if path == ("design_id",):
        design = _load(DESIGN_PATH)
        design["design_id"] += "-drift"
        with pytest.raises(MultiSignalHoldoutAcceptanceClosureError) as raised:
            validate_multisignal_holdout_acceptance_closure_design(design)
        assert raised.value.error_code == (
            "MULTI_SIGNAL_HOLDOUT_ACCEPTANCE_CLOSURE_INTEGRITY"
        )


@pytest.mark.parametrize(
    ("source_name", "field"),
    [
        ("retrieval_live_report", "status"),
        ("holdout_report", "status"),
        ("holdout_receipt", "status"),
        ("operations_closure_report", "status"),
        ("maintenance_report", "status"),
    ],
)
def test_every_source_document_is_integrity_bound(source_name: str, field: str) -> None:
    sources = _sources()
    sources[source_name][field] = "TAMPERED"

    with pytest.raises(MultiSignalHoldoutAcceptanceClosureError) as raised:
        _build(**sources)

    assert raised.value.error_code == (
        "MULTI_SIGNAL_HOLDOUT_ACCEPTANCE_CLOSURE_INTEGRITY"
    )


def test_rehashed_but_semantically_invalid_retrieval_and_holdout_fail_closed() -> None:
    sources = _sources()
    retrieval = sources["retrieval_live_report"]
    retrieval["status"] = "FAIL"
    design = _rebind(
        sources["design"],
        "retrieval_live_report_document_hash",
        semantic_sha256_hash_ref(retrieval),
    )
    with pytest.raises(MultiSignalHoldoutAcceptanceClosureError) as raised:
        _build(**{**sources, "design": design})
    assert raised.value.error_code == (
        "MULTI_SIGNAL_HOLDOUT_ACCEPTANCE_CLOSURE_INVALID"
    )

    sources = _sources()
    holdout = sources["holdout_report"]
    holdout["runtime_activation_permitted"] = True
    design = _rebind(
        sources["design"],
        "holdout_report_document_hash",
        semantic_sha256_hash_ref(holdout),
    )
    with pytest.raises(MultiSignalHoldoutAcceptanceClosureError) as raised:
        _build(**{**sources, "design": design})
    assert raised.value.error_code == (
        "MULTI_SIGNAL_HOLDOUT_ACCEPTANCE_CLOSURE_INVALID"
    )


def test_rehashed_but_semantically_invalid_operations_and_maintenance_fail_closed() -> (
    None
):
    sources = _sources()
    operations = sources["operations_closure_report"]
    operations["runtime_changed"] = True
    _rehash_internal(operations, "closure_hash")
    design = _rebind_many(
        sources["design"],
        {
            "operations_closure_hash": operations["closure_hash"],
            "operations_closure_report_document_hash": semantic_sha256_hash_ref(
                operations
            ),
        },
    )
    with pytest.raises(MultiSignalHoldoutAcceptanceClosureError) as raised:
        _build(**{**sources, "design": design})
    assert raised.value.error_code == (
        "MULTI_SIGNAL_HOLDOUT_ACCEPTANCE_CLOSURE_INVALID"
    )

    sources = _sources()
    maintenance = sources["maintenance_report"]
    maintenance["review_due"] = True
    _rehash_internal(maintenance, "maintenance_hash")
    design = _rebind_many(
        sources["design"],
        {
            "maintenance_hash": maintenance["maintenance_hash"],
            "maintenance_report_document_hash": semantic_sha256_hash_ref(maintenance),
        },
    )
    with pytest.raises(MultiSignalHoldoutAcceptanceClosureError) as raised:
        _build(**{**sources, "design": design})
    assert raised.value.error_code == (
        "MULTI_SIGNAL_HOLDOUT_ACCEPTANCE_CLOSURE_INVALID"
    )


def test_nested_receipt_and_manifest_hashes_are_independently_verified() -> None:
    sources = _sources()
    receipt = sources["holdout_receipt"]
    receipt["attempt_number"] = 2
    design = _rebind(
        sources["design"],
        "holdout_receipt_document_hash",
        semantic_sha256_hash_ref(receipt),
    )
    with pytest.raises(MultiSignalHoldoutAcceptanceClosureError) as raised:
        _build(**{**sources, "design": design})
    assert raised.value.error_code == (
        "MULTI_SIGNAL_HOLDOUT_ACCEPTANCE_CLOSURE_INTEGRITY"
    )

    sources = _sources()
    operations = sources["operations_closure_report"]
    operations["closure_hash"] = "sha256:" + "0" * 64
    design = _rebind(
        sources["design"],
        "operations_closure_report_document_hash",
        semantic_sha256_hash_ref(operations),
    )
    with pytest.raises(MultiSignalHoldoutAcceptanceClosureError) as raised:
        _build(**{**sources, "design": design})
    assert raised.value.error_code == (
        "MULTI_SIGNAL_HOLDOUT_ACCEPTANCE_CLOSURE_INTEGRITY"
    )

    sources = _sources()
    maintenance = sources["maintenance_report"]
    maintenance["maintenance_hash"] = "sha256:" + "0" * 64
    design = _rebind(
        sources["design"],
        "maintenance_report_document_hash",
        semantic_sha256_hash_ref(maintenance),
    )
    with pytest.raises(MultiSignalHoldoutAcceptanceClosureError) as raised:
        _build(**{**sources, "design": design})
    assert raised.value.error_code == (
        "MULTI_SIGNAL_HOLDOUT_ACCEPTANCE_CLOSURE_INTEGRITY"
    )


def test_shape_and_hash_guards_are_fail_closed() -> None:
    with pytest.raises(MultiSignalHoldoutAcceptanceClosureError):
        _mapping([], "value")
    with pytest.raises(MultiSignalHoldoutAcceptanceClosureError):
        _exact({"extra": True}, set(), "value")
    with pytest.raises(MultiSignalHoldoutAcceptanceClosureError):
        _hash_ref(None, "hash")

    design = _load(DESIGN_PATH)
    design["unexpected"] = True
    with pytest.raises(MultiSignalHoldoutAcceptanceClosureError):
        validate_multisignal_holdout_acceptance_closure_design(design)


def _build(**overrides: dict) -> dict:
    return build_multisignal_holdout_acceptance_closure(**{**_sources(), **overrides})


def _sources() -> dict[str, dict]:
    return {
        "design": _load(DESIGN_PATH),
        "retrieval_live_report": _load(RETRIEVAL_PATH),
        "holdout_report": _load(HOLDOUT_PATH),
        "holdout_receipt": _load(RECEIPT_PATH),
        "operations_closure_report": _load(OPERATIONS_PATH),
        "maintenance_report": _load(MAINTENANCE_PATH),
    }


def _rebind(design: dict, field: str, value: str) -> dict:
    return _rebind_many(design, {field: value})


def _rebind_many(design: dict, values: dict[str, str]) -> dict:
    rebound = deepcopy(design)
    rebound["source_binding"].update(values)
    rebound.pop("design_hash")
    rebound["design_hash"] = semantic_sha256_hash_ref(rebound)
    return rebound


def _rehash_internal(report: dict, hash_field: str) -> None:
    payload = deepcopy(report)
    payload.pop("evidence_schema_version")
    payload.pop("slice_id")
    payload.pop(hash_field)
    report[hash_field] = semantic_sha256_hash_ref(payload)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
