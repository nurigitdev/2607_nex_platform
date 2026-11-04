from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import nex_cx.retrieval_answer_support_canonical_profile as subject
import pytest
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts" / "smoke" / "data"
REPORT = ROOT / "reports" / "live"


def _design() -> dict:
    return json.loads(
        (DATA / "s136_answer_support_canonical_profile_v2_design.json").read_text()
    )


def _audit() -> dict:
    source = json.loads(
        (REPORT / "gb2_ca00_s20qpk_profile_stability_equivalence_audit.json").read_text()
    )
    return source["audit"]


def _rehash(value: dict) -> dict:
    value.pop("audit_hash", None)
    value["audit_hash"] = semantic_sha256_hash_ref(value)
    return value


def test_freeze_binds_semantic_profile_to_p_k_without_threshold() -> None:
    result = subject.freeze_canonical_answer_support_profile(
        _design(), p_k_audit=_audit()
    )

    assert result["status"] == (
        "CANONICAL_PROFILE_FROZEN_FRESH_CALIBRATION_REQUIRED"
    )
    assert result["canonical_profile"]["profile_id"] == (
        "answer-support-contradiction-aware-v2"
    )
    assert result["canonical_profile"]["threshold"] is None
    assert result["evidence_plan"]["fresh_calibration_scenario_count"] == 100
    assert result["holdout_access_permitted"] is False
    assert result["runtime_activation_permitted"] is False


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.update(status="ACTIVE"), "identity"),
        (lambda value: value.update(source_binding={}), "source binding fields"),
        (
            lambda value: value["source_binding"].update(p_k_decision="OTHER"),
            "P-K decision",
        ),
        (lambda value: value.update(ready_semantics={}), "READY semantics"),
        (lambda value: value.update(feature_transforms={}), "feature transforms"),
        (
            lambda value: value["canonical_profile"].update(threshold=0.5),
            "profile definition",
        ),
        (lambda value: value.update(admission={}), "admission"),
        (lambda value: value.update(evidence_plan={}), "evidence plan"),
        (lambda value: value.update(safety={}), "safety"),
    ],
)
def test_design_rejects_contract_drift(mutator, message) -> None:
    design = _design()
    mutator(design)
    with pytest.raises((TypeError, ValueError), match=message):
        subject.validate_canonical_answer_support_profile_design(design)


def test_freeze_rejects_p_k_integrity_and_boundary_drift() -> None:
    audit = _audit()
    audit["audit_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="integrity"):
        subject.freeze_canonical_answer_support_profile(_design(), p_k_audit=audit)

    for mutator in (
        lambda value: value.update(status="INCONCLUSIVE"),
        lambda value: value.update(equivalence_family_authorized=True),
        lambda value: value["semantic_equivalence"]["checks"].update(
            feature_dependency_sets_equal=True
        ),
        lambda value: value["next_contract"].update(
            fresh_calibration_evidence_required=False
        ),
    ):
        audit = deepcopy(_audit())
        mutator(audit)
        _rehash(audit)
        with pytest.raises(ValueError, match="boundary"):
            subject.freeze_canonical_answer_support_profile(
                _design(), p_k_audit=audit
            )


def test_primitives_reject_invalid_values() -> None:
    with pytest.raises(TypeError, match="mapping"):
        subject._mapping([], "mapping")
    with pytest.raises(ValueError, match="fields"):
        subject._exact_mapping({}, {"required"}, "fields")
    with pytest.raises(ValueError, match="text"):
        subject._required_text(" ", "text")
