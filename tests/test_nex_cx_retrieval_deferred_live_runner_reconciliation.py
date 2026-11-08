from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_cx.retrieval_deferred_live_runner_reconciliation import (
    DeferredLiveRunnerReconciliationError,
    build_deferred_live_runner_reconciliation_contract,
    evaluate_deferred_live_runner_replay,
    validate_deferred_live_runner_reconciliation_design,
)

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/s136_deferred_live_runner_reconciliation_v1_design.json"
)
CLOSURE_PATH = (
    ROOT
    / "reports/live/gb2_ca00_s20q_multi_signal_live_holdout_acceptance_closure.json"
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _contract() -> dict:
    return build_deferred_live_runner_reconciliation_contract(
        design=_json(DESIGN_PATH),
        s20q_closure=_json(CLOSURE_PATH),
        s20q_closure_document_hash=(
            f"sha256:{hashlib.sha256(CLOSURE_PATH.read_bytes()).hexdigest()}"
        ),
    )


def _s136() -> dict:
    checks = {
        "provider_calls_complete": True,
        "cleanup_complete": True,
        "five_run_pipeline_repeatability_stable": True,
        "vector_rank_repeatable": True,
        "rrf_score_repeatable": True,
        "candidate_membership_repeatable": True,
        "final_rank_repeatable": True,
        "holdout_remained_sealed": True,
        "runtime_activation_prohibited": True,
    }
    return {
        "evidence_schema_version": "gb2_s20qpa_vector_near_tie_ordering.v1",
        "slice_id": "GB2-CA00-S20Q-P-A",
        "status": "PASS",
        "database_identity": {"database": "nex_cx_test", "role": "nex_cx_user"},
        "provider_binding": {
            "embedding_model_revision": "hf:5cf2132abc99cad020ac570b19d031efec650f2b",
            "reranker_model_revision": "hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5",
        },
        "checks": checks,
        "failed_checks": [],
    }


def _s137() -> dict:
    return {
        "smoke_schema_version": (
            "platform_grounded_generation_artifact_live_postgres_smoke.v1"
        ),
        "status": "PASS",
        "actual_postgres": True,
        "answer_support_observation": {
            "primary_policy_installed": True,
            "steady_state_policy_installed": True,
            "selected_policy_hash": (
                "sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb"
            ),
            "steady_state_state": "ACTIVE",
            "cutover_state": "ACTIVE",
        },
        "provider_observation": {
            "generation": {
                "model": "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a"
            }
        },
        "post_journey_residue": {"ae_chat": 0, "cx_generations": 0},
        "checks": {"canonical_answer_support_policy_applied": True},
        "failed_checks": [],
    }


def test_frozen_design_and_s20q_closure_build_ready_contract() -> None:
    design = validate_deferred_live_runner_reconciliation_design(
        _json(DESIGN_PATH)
    )
    contract = _contract()

    assert design["provider_binding"]["generation"] == {
        "deployment_id": "dgx-qwen3-5-9b-9116",
        "model": "Qwen3.5-9B",
        "revision": "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a",
    }
    assert contract["status"] == "READY"
    assert contract["runner_mapping"]["s136"][
        "retired_v1_calibration_reexecution_permitted"
    ] is False
    assert contract["safety"]["holdout_reexecution_permitted"] is False


def test_design_and_closure_drift_fail_closed() -> None:
    design = _json(DESIGN_PATH)
    design["provider_binding"]["generation"]["model"] = "Qwen3.5-4B"
    with pytest.raises(DeferredLiveRunnerReconciliationError):
        validate_deferred_live_runner_reconciliation_design(design)

    design = _json(DESIGN_PATH)
    design["provider_binding"]["generation"]["deployment_id"] = "stale"
    with pytest.raises(DeferredLiveRunnerReconciliationError):
        validate_deferred_live_runner_reconciliation_design(design)

    closure = _json(CLOSURE_PATH)
    closure["selected_policy_hash"] = "sha256:" + "0" * 64
    with pytest.raises(DeferredLiveRunnerReconciliationError):
        build_deferred_live_runner_reconciliation_contract(
            design=_json(DESIGN_PATH),
            s20q_closure=closure,
            s20q_closure_document_hash=(
                f"sha256:{hashlib.sha256(CLOSURE_PATH.read_bytes()).hexdigest()}"
            ),
        )


def test_design_shape_identity_and_integrity_drift_fail_closed() -> None:
    invalid_designs = []

    design = _json(DESIGN_PATH)
    design["status"] = "DRAFT"
    invalid_designs.append(design)

    design = _json(DESIGN_PATH)
    design["runner_mapping"]["s136"]["historical_runner"] = "stale"
    invalid_designs.append(design)

    design = _json(DESIGN_PATH)
    design["provider_binding"].pop("embedding")
    invalid_designs.append(design)

    design = _json(DESIGN_PATH)
    design["provider_binding"]["embedding"]["unexpected"] = True
    invalid_designs.append(design)

    design = _json(DESIGN_PATH)
    design["provider_binding"]["embedding"]["revision"] = "mutable"
    invalid_designs.append(design)

    design = _json(DESIGN_PATH)
    design["safety"]["public_api_change_permitted"] = True
    invalid_designs.append(design)

    design = _json(DESIGN_PATH)
    design["design_hash"] = "sha256:" + "0" * 64
    invalid_designs.append(design)

    design = _json(DESIGN_PATH)
    design["source_binding"].pop("s20q_closure_hash")
    invalid_designs.append(design)

    for invalid in invalid_designs:
        with pytest.raises(DeferredLiveRunnerReconciliationError):
            validate_deferred_live_runner_reconciliation_design(invalid)

    without_hash = _json(DESIGN_PATH)
    without_hash.pop("design_hash")
    assert validate_deferred_live_runner_reconciliation_design(without_hash)[
        "design_hash"
    ].startswith("sha256:")

    with pytest.raises(DeferredLiveRunnerReconciliationError):
        validate_deferred_live_runner_reconciliation_design(None)  # type: ignore[arg-type]


def test_closure_document_hash_drift_fails_closed() -> None:
    with pytest.raises(DeferredLiveRunnerReconciliationError):
        build_deferred_live_runner_reconciliation_contract(
            design=_json(DESIGN_PATH),
            s20q_closure=_json(CLOSURE_PATH),
            s20q_closure_document_hash="sha256:" + "0" * 64,
        )


def test_current_s136_and_s137_replays_close_reconciliation() -> None:
    evidence = evaluate_deferred_live_runner_replay(
        contract=_contract(),
        s136_replay=_s136(),
        s137_replay=_s137(),
    )

    assert evidence["status"] == "PASS"
    assert evidence["failed_checks"] == []
    assert evidence["replay_order"] == ["S136", "S137"]
    assert evidence["holdout_reexecuted"] is False
    assert evidence["retired_v1_calibration_reexecuted"] is False


def test_replay_fails_closed_for_provider_or_policy_drift() -> None:
    s136 = _s136()
    s136["provider_binding"]["reranker_model_revision"] = "hf:" + "0" * 40
    s137 = _s137()
    s137["answer_support_observation"]["selected_policy_hash"] = (
        "sha256:" + "0" * 64
    )

    evidence = evaluate_deferred_live_runner_replay(
        contract=_contract(),
        s136_replay=s136,
        s137_replay=s137,
    )

    assert evidence["status"] == "FAIL"
    assert set(evidence["failed_checks"]) == {
        "s136_provider_revisions_exact",
        "s137_answer_support_policy_exact",
    }


def test_contract_hash_tamper_fails_closed() -> None:
    contract = deepcopy(_contract())
    contract["status"] = "TAMPERED"
    with pytest.raises(DeferredLiveRunnerReconciliationError):
        evaluate_deferred_live_runner_replay(
            contract=contract,
            s136_replay=_s136(),
            s137_replay=_s137(),
        )
