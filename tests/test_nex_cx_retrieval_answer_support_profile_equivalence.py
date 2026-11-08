from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import nex_cx.retrieval_answer_support_profile_equivalence as subject
import pytest
from nex_cx.retrieval_answer_support_nested_selection import (
    ANSWER_SUPPORT_NESTED_SAMPLE_SCHEMA_VERSION,
    validate_answer_support_nested_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts" / "smoke" / "data"
HASH = "sha256:" + "a" * 64


def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _nested_design() -> dict:
    return _load("s136_answer_support_nested_calibration_v1_design.json")


def _audit_design() -> dict:
    return _load("s136_answer_support_profile_equivalence_audit_v1_design.json")


def _sample(scenario: int, *, ready: bool, divergent: bool = False) -> dict:
    top_value = 0.9 if ready else 0.1
    contradiction_value = top_value
    if divergent and scenario % 2 == 0:
        contradiction_value = 0.7 if ready else 0.3
    features = {
        "direct_or_support_fraction": contradiction_value,
        "second_answer_support_score": top_value,
        "top_two_answer_support_mean": top_value,
        "inverse_maximum_contradiction_score": contradiction_value,
        "inverse_mean_contradiction_score": contradiction_value,
        "normalized_support_contradiction_margin": contradiction_value,
    }
    row = {
        "sample_schema_version": ANSWER_SUPPORT_NESTED_SAMPLE_SCHEMA_VERSION,
        "sample_id": f"scenario-{scenario}-{'ready' if ready else 'low'}",
        "scenario_id": f"scenario-{scenario}",
        "expected_ready": ready,
        "domain": "PROJECT",
        "language_profile": "KOREAN",
        "features": features,
        "source_feature_hash": semantic_sha256_hash_ref(
            {"scenario": scenario, "ready": ready, "kind": "feature"}
        ),
        "source_evidence_hash": semantic_sha256_hash_ref(
            {"scenario": scenario, "ready": ready, "kind": "evidence"}
        ),
    }
    row["sample_hash"] = semantic_sha256_hash_ref(row)
    return row


def _samples(*, divergent: bool = False) -> list[dict]:
    return [
        _sample(scenario, ready=ready, divergent=divergent)
        for scenario in range(20)
        for ready in (False, True)
    ]


def _fold_plan() -> dict:
    scenario_ids = [f"scenario-{value}" for value in range(20)]
    outer_folds = []
    for outer_index in range(5):
        validation = scenario_ids[outer_index * 4 : outer_index * 4 + 4]
        training = [value for value in scenario_ids if value not in validation]
        outer_folds.append(
            {
                "fold_index": outer_index,
                "validation_scenario_ids": validation,
                "inner_folds": [
                    {
                        "fold_index": inner_index,
                        "validation_scenario_ids": training[
                            inner_index * 4 : inner_index * 4 + 4
                        ],
                    }
                    for inner_index in range(4)
                ],
            }
        )
    return {
        "assignment": {"outer_fold_count": 5, "outer_folds": outer_folds}
    }


def _selection(nested_design: dict, *, counts: dict | None = None) -> dict:
    normalized = validate_answer_support_nested_design(nested_design)
    value = {
        "selection_schema_version": (
            "cx_answer_support_nested_profile_selection.v1"
        ),
        "status": "NO_ADMISSIBLE_PROFILE",
        "runtime_activation_permitted": False,
        "holdout_access_permitted": False,
        "binding": {
            "source_collection_hash": HASH,
            "answer_support_design_hash": normalized["design_hash"],
        },
        "oof_evaluation": {
            "profile_selection_counts": counts
            or {
                "answer-support-top-two-v1": 2,
                "answer-support-contradiction-aware-v1": 3,
            }
        },
    }
    value["selection_hash"] = semantic_sha256_hash_ref(value)
    return value


def _bound_design(selection: dict) -> dict:
    design = _audit_design()
    design["source_binding"]["collection_hash"] = HASH
    design["source_binding"]["p_j_selection_hash"] = selection["selection_hash"]
    return design


def _audit(samples: list[dict], nested_design: dict | None = None) -> dict:
    nested_design = nested_design or _nested_design()
    selection = _selection(nested_design)
    return subject.audit_answer_support_profile_equivalence(
        samples,
        nested_design=nested_design,
        fold_plan=_fold_plan(),
        p_j_selection=selection,
        audit_design=_bound_design(selection),
    )


def test_empirically_close_profiles_remain_semantically_distinct() -> None:
    result = _audit(_samples())

    assert result["status"] == "DIAGNOSED"
    assert result["decision"] == (
        "EMPIRICALLY_CLOSE_SEMANTICALLY_DISTINCT_CANONICAL_PROFILE_REQUIRED"
    )
    assert all(result["empirical_equivalence"]["checks"].values())
    assert not any(result["semantic_equivalence"]["checks"].values())
    assert result["equivalence_family_authorized"] is False


def test_distinct_ordering_requires_fresh_design() -> None:
    result = _audit(_samples(divergent=True))

    assert result["decision"] == "DISTINCT_PROFILES_FRESH_DESIGN_REQUIRED"
    assert result["empirical_equivalence"]["checks"][
        "score_ordering_agreement_within_limit"
    ] is False


def test_identical_profile_semantics_only_justify_future_design_review() -> None:
    nested_design = _nested_design()
    top_two = deepcopy(nested_design["profile_shortlist"][1])
    nested_design["profile_shortlist"][3]["feature_fields"] = top_two[
        "feature_fields"
    ]
    nested_design["profile_shortlist"][3]["weights"] = top_two["weights"]

    result = _audit(_samples(), nested_design)

    assert result["decision"] == "PREDECLARED_EQUIVALENCE_DESIGN_REVIEW_JUSTIFIED"
    assert all(result["semantic_equivalence"]["checks"].values())
    assert result["equivalence_family_authorized"] is False


def test_refit_failure_is_inconclusive(monkeypatch) -> None:
    monkeypatch.setattr(
        subject,
        "evaluate_binary_score_calibration",
        lambda *_args, **_kwargs: {"status": "FAILED", "selected_threshold": None},
    )

    result = _audit(_samples())

    assert result["status"] == "INCONCLUSIVE"
    assert result["decision"] == "STOP_FOR_REVIEW"
    assert result["checks"]["empirical_diagnostics_complete"] is False
    assert len(result["empirical_equivalence"]["failed_refits"]) == 10


def test_oof_package_coverage_mismatch_is_rejected(monkeypatch) -> None:
    original = subject._profile_scores

    def mismatched_scores(samples, *, profile, scenario_ids=None):
        rows = original(samples, profile=profile, scenario_ids=scenario_ids)
        if (
            profile["profile_id"] == "answer-support-top-two-v1"
            and scenario_ids == {f"scenario-{value}" for value in range(4)}
        ):
            return rows[:-1]
        return rows

    monkeypatch.setattr(subject, "_profile_scores", mismatched_scores)

    with pytest.raises(ValueError, match="OOF package coverage"):
        _audit(_samples())


@pytest.mark.parametrize(
    ("mutator", "error"),
    [
        (lambda value: value.update(status="ACTIVE"), "identity"),
        (lambda value: value.update(source_binding={}), "source binding"),
        (lambda value: value.update(compared_profiles=[]), "compared profiles"),
        (
            lambda value: value.update(empirical_equivalence={}),
            "empirical equivalence fields",
        ),
        (
            lambda value: value["empirical_equivalence"].update(
                maximum_oof_decision_disagreement_rate=2
            ),
            "maximum_oof",
        ),
        (
            lambda value: value["empirical_equivalence"].update(
                require_complete_fold_local_thresholds=False
            ),
            "threshold requirement",
        ),
        (
            lambda value: value["semantic_equivalence"].update(
                require_equal_feature_dependency_sets=False
            ),
            "semantic equivalence requirements",
        ),
        (lambda value: value.update(counterfactual_pairs=[]), "pairs"),
        (lambda value: value.update(safety={}), "safety"),
    ],
)
def test_audit_design_rejects_contract_drift(mutator, error) -> None:
    design = _audit_design()
    mutator(design)
    with pytest.raises((TypeError, ValueError), match=error):
        subject.validate_profile_equivalence_audit_design(design)


def test_counterfactual_contract_guards() -> None:
    design = _audit_design()
    design["counterfactual_pairs"][0].pop("variant")
    with pytest.raises(ValueError, match="pair fields"):
        subject.validate_profile_equivalence_audit_design(design)

    design = _audit_design()
    design["counterfactual_pairs"].append(
        deepcopy(design["counterfactual_pairs"][0])
    )
    with pytest.raises(ValueError, match="duplicated"):
        subject.validate_profile_equivalence_audit_design(design)

    design = _audit_design()
    design["counterfactual_pairs"][0]["baseline"].pop(
        "direct_or_support_fraction"
    )
    with pytest.raises(ValueError, match="feature fields"):
        subject.validate_profile_equivalence_audit_design(design)


@pytest.mark.parametrize(
    ("mutator", "error"),
    [
        (lambda value: value.update(selection_hash=HASH), "integrity"),
        (lambda value: value.update(status="CALIBRATION_OOF_ADMITTED"), "boundary"),
        (
            lambda value: value["binding"].update(
                source_collection_hash="sha256:" + "b" * 64
            ),
            "binding",
        ),
        (
            lambda value: value["oof_evaluation"].update(
                profile_selection_counts={"other": 5}
            ),
            "instability",
        ),
    ],
)
def test_p_j_selection_rejects_integrity_and_binding_drift(mutator, error) -> None:
    nested_design = _nested_design()
    selection = _selection(nested_design)
    mutator(selection)
    if error != "integrity":
        unsigned = dict(selection)
        unsigned.pop("selection_hash")
        selection["selection_hash"] = semantic_sha256_hash_ref(unsigned)
    audit_design = _bound_design(selection)
    with pytest.raises(ValueError, match=error):
        subject.audit_answer_support_profile_equivalence(
            _samples(),
            nested_design=nested_design,
            fold_plan=_fold_plan(),
            p_j_selection=selection,
            audit_design=audit_design,
        )


def test_ordering_and_primitive_guards() -> None:
    with pytest.raises(ValueError, match="score coverage"):
        subject._ordering_agreement({}, {})
    with pytest.raises(ValueError, match="two packages"):
        subject._ordering_agreement({"one": 0.1}, {"one": 0.1})
    assert subject._ordering_agreement(
        {"one": 0.1, "two": 0.1, "three": 0.9},
        {"one": 0.1, "two": 0.1, "three": 0.9},
    ) == 1.0
    assert {subject._direction(value) for value in (-1.0, 0.0, 1.0)} == {-1, 0, 1}
    with pytest.raises(ValueError, match="rate"):
        subject._rate(2.0, "rate")
    for value in (True, "1", float("nan"), -0.1):
        with pytest.raises(ValueError, match="number"):
            subject._nonnegative(value, "number")
    with pytest.raises(ValueError, match="text"):
        subject._required_text(" ", "text")
    with pytest.raises(TypeError, match="flag"):
        subject._required_bool(1, "flag")
    with pytest.raises(ValueError, match="fields"):
        subject._exact_mapping({}, {"required"}, "mapping")
    with pytest.raises(TypeError, match="mapping"):
        subject._mapping([], "mapping")
