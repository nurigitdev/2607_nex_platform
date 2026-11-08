from __future__ import annotations

import json
from pathlib import Path

import pytest
from nex_cx.retrieval_answer_support_holdout_freeze import (
    freeze_holdout_one_shot_execution,
    validate_holdout_execution_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_answer_support_holdout_one_shot_v1_design.json"
)


def _design() -> dict:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def _calibration(design: dict) -> dict:
    source = design["source_binding"]
    value = {
        "calibration_schema_version": (
            "cx_answer_support_canonical_threshold_calibration.v1"
        ),
        "status": "CALIBRATION_THRESHOLD_CANDIDATE_ADMITTED",
        "candidate": {
            "status": "CANDIDATE_NOT_ACTIVE",
            "profile_id": "answer-support-contradiction-aware-v2",
            "profile_hash": source["canonical_profile_hash"],
            "threshold": source["p_o_threshold"],
        },
        "binding": {
            "calibration_design_hash": source["p_o_calibration_design_hash"],
            "source_collection_hash": source["p_n_collection_hash"],
            "artifact_evidence_hash": source["artifact_evidence_hash"],
            "provider_binding": {
                "provider_alias": "general-llm-default",
                "provider_type": "vllm",
                "model_revision": source["artifact_revision"],
                "deployment_id": "deployment-a",
                "request_profile_id": "request-profile-v1",
                "score_semantics_id": "bounded-ordinal-v1",
            },
        },
        "oof_evaluation": {
            "metrics": {"false_ready_rate": 0.0, "ready_recall": 1.0},
            "package_auc": 1.0,
        },
        "checks": {"outer_folds": True, "full_fit": True},
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    }
    value["calibration_hash"] = semantic_sha256_hash_ref(value)
    design["source_binding"]["p_o_calibration_hash"] = value["calibration_hash"]
    return value


def _manifest() -> dict:
    source = _design()["source_binding"]
    return {
        "status": "PASS",
        "dataset_id": "s136-retrieval-package-confidence-public-v4",
        "dataset_file_sha256": source["dataset_file_sha256"].removeprefix(
            "sha256:"
        ),
        "dataset_sha256": source["dataset_semantic_sha256"].removeprefix(
            "sha256:"
        ),
        "scenario_count": 100,
        "package_count": 200,
        "candidate_count": 800,
        "holdout_scenario_count": 20,
        "independent_review_passed": True,
        "immutable": True,
        "holdout_excluded_from_folds": True,
        "runtime_activation_permitted": False,
    }


def _freeze(
    *,
    calibration_mutator=None,
    manifest_mutator=None,
    receipt=None,
) -> dict:
    design = _design()
    calibration = _calibration(design)
    manifest = _manifest()
    if calibration_mutator is not None:
        original_hash = calibration["calibration_hash"]
        calibration_mutator(calibration)
        if calibration.get("calibration_hash") == original_hash:
            calibration.pop("calibration_hash")
            calibration["calibration_hash"] = semantic_sha256_hash_ref(calibration)
            design["source_binding"]["p_o_calibration_hash"] = calibration[
                "calibration_hash"
            ]
    if manifest_mutator is not None:
        manifest_mutator(manifest)
    return freeze_holdout_one_shot_execution(
        p_o_calibration=calibration,
        dataset_manifest=manifest,
        design=design,
        existing_receipt=receipt,
    )


def test_freeze_arms_one_deterministic_future_execution() -> None:
    first = _freeze()
    second = _freeze()

    assert first == second
    assert first["status"] == "HOLDOUT_ONE_SHOT_EXECUTION_ARMED"
    assert first["execution_id"].startswith("s20qpq-")
    assert first["authorization"]["candidate"] == {
        "profile_id": "answer-support-contradiction-aware-v2",
        "profile_hash": _design()["source_binding"]["canonical_profile_hash"],
        "threshold": 0.46375,
        "score_semantics": "WEIGHTED_BOUNDED_ORDINAL_NOT_PROBABILITY",
    }
    assert first["authorization"]["dataset"]["scenario_count"] == 20
    assert first["authorization"]["protocol"]["maximum_execution_attempts"] == 1
    assert first["receipt_contract"]["reexecution_permitted"] is False
    assert first["receipt_contract"]["reservation_status"] == "STARTED"
    assert first["receipt_contract"]["reservation_write_mode"] == (
        "ATOMIC_CREATE_EXCLUSIVE"
    )
    assert first["receipt_contract"][
        "reservation_required_before_provider_call"
    ] is True
    assert first["safety"]["holdout_executed_in_this_slice"] is False
    assert first["new_provider_calls"] == 0
    assert first["runtime_activation_permitted"] is False


def test_freeze_rejects_existing_receipt() -> None:
    with pytest.raises(ValueError, match="already consumed"):
        _freeze(receipt={"status": "PASS"})
    with pytest.raises(TypeError, match="existing holdout receipt"):
        _freeze(receipt=[])


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(status="NO_ADMISSIBLE_THRESHOLD"),
        lambda value: value["candidate"].update(status="ACTIVE"),
        lambda value: value["candidate"].update(profile_id="other"),
        lambda value: value["candidate"].update(threshold=0.5),
        lambda value: value["binding"].update(source_collection_hash="sha256:" + "0" * 64),
        lambda value: value["binding"]["provider_binding"].update(
            model_revision="hf:" + "0" * 40
        ),
        lambda value: value["oof_evaluation"]["metrics"].update(
            false_ready_rate=0.2
        ),
        lambda value: value["oof_evaluation"].update(package_auc=0.7),
        lambda value: value["checks"].update(outer_folds=False),
        lambda value: value.update(holdout_access_permitted=True),
        lambda value: value.update(calibration_hash="sha256:" + "0" * 64),
    ],
)
def test_freeze_rejects_calibration_drift(mutator) -> None:
    with pytest.raises(ValueError, match="calibration admission"):
        _freeze(calibration_mutator=mutator)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(status="FAIL"),
        lambda value: value.update(dataset_id="other"),
        lambda value: value.update(dataset_file_sha256="0" * 64),
        lambda value: value.update(dataset_sha256="0" * 64),
        lambda value: value.update(scenario_count=99),
        lambda value: value.update(package_count=199),
        lambda value: value.update(candidate_count=799),
        lambda value: value.update(holdout_scenario_count=19),
        lambda value: value.update(independent_review_passed=False),
        lambda value: value.update(immutable=False),
        lambda value: value.update(holdout_excluded_from_folds=False),
        lambda value: value.update(runtime_activation_permitted=True),
    ],
)
def test_freeze_rejects_dataset_manifest_drift(mutator) -> None:
    with pytest.raises(ValueError, match="Dataset v4 holdout admission"):
        _freeze(manifest_mutator=mutator)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.update(status="ACTIVE"), "identity"),
        (lambda value: value.update(source_binding={}), "source binding"),
        (lambda value: value.update(holdout_manifest={}), "holdout manifest"),
        (lambda value: value.update(protocol={}), "protocol"),
        (lambda value: value.update(admission={}), "admission"),
        (lambda value: value.update(safety={}), "safety"),
    ],
)
def test_design_rejects_contract_drift(mutator, message) -> None:
    design = _design()
    mutator(design)
    with pytest.raises((TypeError, ValueError), match=message):
        validate_holdout_execution_design(design)


def test_design_and_primitive_guards() -> None:
    design = _design()
    design["unexpected"] = True
    with pytest.raises(ValueError, match="fields"):
        validate_holdout_execution_design(design)

    design = _design()
    design["source_binding"]["artifact_revision"] = " "
    with pytest.raises(ValueError, match="artifact_revision"):
        validate_holdout_execution_design(design)

    design = _design()
    design["source_binding"]["p_o_threshold"] = float("nan")
    with pytest.raises(ValueError, match="p_o_threshold"):
        validate_holdout_execution_design(design)

    manifest = _manifest()
    manifest["dataset_sha256"] = "not-a-hash"
    with pytest.raises(ValueError, match="hash"):
        _freeze(manifest_mutator=lambda value: value.update(manifest))
