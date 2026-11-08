from __future__ import annotations

import json
from pathlib import Path

import nex_cx.retrieval_answer_support_canonical_calibration as calibration
import pytest
from nex_cx.retrieval_answer_support_canonical_calibration import (
    calibrate_canonical_answer_support_threshold,
    validate_canonical_calibration_design,
)
from nex_cx.retrieval_answer_support_canonical_profile import (
    validate_canonical_answer_support_profile_design,
)
from nex_cx.retrieval_answer_support_nested_selection import (
    ANSWER_SUPPORT_NESTED_SAMPLE_SCHEMA_VERSION,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts" / "smoke" / "data"


def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _calibration_design() -> dict:
    return _load("s136_answer_support_canonical_calibration_v1_design.json")


def _canonical_design() -> dict:
    return _load("s136_answer_support_canonical_profile_v2_design.json")


def _freeze() -> dict:
    design = validate_canonical_answer_support_profile_design(_canonical_design())
    profile = dict(design["canonical_profile"])
    profile["profile_hash"] = semantic_sha256_hash_ref(
        {
            "policy_id": design["policy_id"],
            "ready_semantics": design["ready_semantics"],
            "feature_transforms": design["feature_transforms"],
            "profile": profile,
        }
    )
    freeze = {
        "freeze_schema_version": "cx_answer_support_canonical_profile_freeze.v1",
        "status": "CANONICAL_PROFILE_FROZEN_FRESH_CALIBRATION_REQUIRED",
        "policy_id": design["policy_id"],
        "design_hash": design["design_hash"],
        "source_audit_hash": design["source_binding"]["p_k_audit_hash"],
        "canonical_profile": profile,
        "admission": design["admission"],
        "evidence_plan": design["evidence_plan"],
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    }
    freeze["freeze_hash"] = semantic_sha256_hash_ref(freeze)
    return freeze


def _samples(*, separated: bool = True) -> list[dict]:
    domains = (
        "PROJECT",
        "FINANCE",
        "IDENTITY_AUTHORIZATION",
        "GOVERNANCE_OPERATIONS",
        "AI_RUNTIME",
    )
    rows = []
    for domain in domains:
        for index in range(1, 21):
            language = (
                "KOREAN"
                if index <= 12
                else "KOREAN_ENGLISH_MIXED"
                if index <= 16
                else "ENGLISH"
            )
            scenario = f"fresh-{domain.lower().replace('_', '-')}-{index:02d}"
            for ready in (False, True):
                value = (0.1 if not ready else 0.9) if separated else 0.5
                row = {
                    "sample_schema_version": (
                        ANSWER_SUPPORT_NESTED_SAMPLE_SCHEMA_VERSION
                    ),
                    "sample_id": f"{scenario}-{'ready' if ready else 'low'}",
                    "scenario_id": scenario,
                    "expected_ready": ready,
                    "domain": domain,
                    "language_profile": language,
                    "features": {
                        "direct_or_support_fraction": value,
                        "second_answer_support_score": value,
                        "top_two_answer_support_mean": value,
                        "inverse_maximum_contradiction_score": value,
                        "inverse_mean_contradiction_score": value,
                        "normalized_support_contradiction_margin": value,
                    },
                    "source_feature_hash": semantic_sha256_hash_ref(
                        {"scenario": scenario, "ready": ready, "kind": "feature"}
                    ),
                    "source_evidence_hash": semantic_sha256_hash_ref(
                        {"scenario": scenario, "ready": ready, "kind": "evidence"}
                    ),
                }
                row["sample_hash"] = semantic_sha256_hash_ref(row)
                rows.append(row)
    return rows


def _provider_binding() -> dict:
    source = _calibration_design()["source_binding"]
    return {
        "provider_alias": "general-llm-default",
        "provider_type": "vllm",
        "model_revision": source["artifact_revision"],
        "deployment_id": "dgx-qwen3-5-9b-9116",
        "request_profile_id": "s136-answer-support-generation-json-v1",
        "score_semantics_id": "bounded-ordinal-answer-support-v1",
    }


def _calibrate(samples: list[dict]) -> dict:
    source = _calibration_design()["source_binding"]
    return calibrate_canonical_answer_support_threshold(
        samples,
        dataset_id="s136-answer-support-fresh-calibration-v1",
        dataset_sha256=source["p_m_dataset_hash"],
        collection_hash=source["p_n_collection_hash"],
        provider_binding=_provider_binding(),
        artifact_evidence_hash=source["artifact_evidence_hash"],
        canonical_design=_canonical_design(),
        canonical_freeze=_freeze(),
        calibration_design=_calibration_design(),
    )


def _rehash(row: dict) -> None:
    row.pop("sample_hash", None)
    row["sample_hash"] = semantic_sha256_hash_ref(row)


def test_fixed_profile_oof_admits_stable_threshold_without_holdout() -> None:
    result = _calibrate(_samples())

    assert result["status"] == "CALIBRATION_THRESHOLD_CANDIDATE_ADMITTED"
    assert result["candidate"]["profile_id"] == (
        "answer-support-contradiction-aware-v2"
    )
    assert result["candidate"]["threshold"] == 0.5
    assert result["oof_evaluation"]["package_auc"] == 1.0
    assert result["oof_evaluation"]["threshold_spread"] == 0.0
    assert {row["training_package_count"] for row in result["outer_folds"]} == {
        160
    }
    assert {row["validation_package_count"] for row in result["outer_folds"]} == {
        40
    }
    assert all(
        row["language_counts"]
        == {"ENGLISH": 4, "KOREAN": 12, "KOREAN_ENGLISH_MIXED": 4}
        for row in result["fold_plan"]
    )
    assert result["holdout"] == {
        "status": "SEALED_NOT_OPENED",
        "threshold_reselected": False,
    }
    assert result["runtime_activation_permitted"] is False


def test_fixed_profile_oof_fails_closed_without_separation() -> None:
    result = _calibrate(_samples(separated=False))

    assert result["status"] == "NO_ADMISSIBLE_THRESHOLD"
    assert result["candidate"] is None
    assert all(
        row["status"] == "NO_ACCEPTABLE_TRAINING_THRESHOLD"
        for row in result["outer_folds"]
    )
    assert result["holdout_access_permitted"] is False


def test_final_refit_failure_revokes_candidate(monkeypatch) -> None:
    original = calibration.evaluate_binary_score_calibration
    calls = 0

    def fail_final(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 6:
            result["status"] = "NO_ACCEPTABLE_THRESHOLD"
        return result

    monkeypatch.setattr(calibration, "evaluate_binary_score_calibration", fail_final)
    result = _calibrate(_samples())

    assert result["status"] == "NO_ADMISSIBLE_THRESHOLD"
    assert result["candidate"] is None
    assert result["checks"]["full_calibration_threshold_fitted"] is False


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.update(status="ACTIVE"), "identity"),
        (lambda value: value.update(source_binding={}), "source binding"),
        (lambda value: value.update(protocol={}), "protocol"),
        (lambda value: value.update(admission={}), "admission"),
        (lambda value: value.update(safety={}), "safety"),
    ],
)
def test_calibration_design_rejects_contract_drift(mutator, message) -> None:
    design = _calibration_design()
    mutator(design)
    with pytest.raises((TypeError, ValueError), match=message):
        validate_canonical_calibration_design(design)


@pytest.mark.parametrize(
    "field",
    ["dataset_sha256", "collection_hash", "artifact_evidence_hash"],
)
def test_calibration_rejects_source_hash_drift(field) -> None:
    source = _calibration_design()["source_binding"]
    kwargs = {
        "dataset_sha256": source["p_m_dataset_hash"],
        "collection_hash": source["p_n_collection_hash"],
        "artifact_evidence_hash": source["artifact_evidence_hash"],
    }
    kwargs[field] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="source binding"):
        calibrate_canonical_answer_support_threshold(
            _samples(),
            dataset_id="dataset",
            provider_binding=_provider_binding(),
            canonical_design=_canonical_design(),
            canonical_freeze=_freeze(),
            calibration_design=_calibration_design(),
            **kwargs,
        )


def test_calibration_rejects_provider_and_freeze_drift() -> None:
    binding = _provider_binding()
    binding["model_revision"] = "hf:" + "0" * 40
    source = _calibration_design()["source_binding"]
    with pytest.raises(ValueError, match="source binding"):
        calibrate_canonical_answer_support_threshold(
            _samples(),
            dataset_id="dataset",
            dataset_sha256=source["p_m_dataset_hash"],
            collection_hash=source["p_n_collection_hash"],
            provider_binding=binding,
            artifact_evidence_hash=source["artifact_evidence_hash"],
            canonical_design=_canonical_design(),
            canonical_freeze=_freeze(),
            calibration_design=_calibration_design(),
        )

    freeze = _freeze()
    freeze["runtime_activation_permitted"] = True
    with pytest.raises(ValueError, match="freeze binding"):
        calibrate_canonical_answer_support_threshold(
            _samples(),
            dataset_id="dataset",
            dataset_sha256=source["p_m_dataset_hash"],
            collection_hash=source["p_n_collection_hash"],
            provider_binding=_provider_binding(),
            artifact_evidence_hash=source["artifact_evidence_hash"],
            canonical_design=_canonical_design(),
            canonical_freeze=freeze,
            calibration_design=_calibration_design(),
        )


def test_calibration_rejects_incomplete_or_inconsistent_strata() -> None:
    with pytest.raises(ValueError, match="scenario coverage"):
        _calibrate(_samples()[:-2])

    samples = _samples()
    samples[0]["language_profile"] = "ENGLISH"
    _rehash(samples[0])
    with pytest.raises(ValueError, match="stratum is inconsistent"):
        _calibrate(samples)

    samples = _samples()
    for row in samples[:2]:
        row["language_profile"] = "ENGLISH"
        _rehash(row)
    with pytest.raises(ValueError, match="stratum coverage"):
        _calibrate(samples)


def test_design_and_primitive_guards() -> None:
    design = _calibration_design()
    design["unexpected"] = True
    with pytest.raises(ValueError, match="fields"):
        validate_canonical_calibration_design(design)

    design = _calibration_design()
    design["source_binding"]["artifact_revision"] = " "
    with pytest.raises(ValueError, match="artifact_revision"):
        validate_canonical_calibration_design(design)

    design = _calibration_design()
    design["protocol"] = []
    with pytest.raises(TypeError, match="protocol"):
        validate_canonical_calibration_design(design)


def test_fold_balance_guard_is_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        calibration,
        "_LANGUAGE_QUOTAS",
        {"ENGLISH": 4, "KOREAN": 11, "KOREAN_ENGLISH_MIXED": 4},
    )
    with pytest.raises(ValueError, match="fold balance"):
        _calibrate(_samples())
