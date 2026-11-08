from __future__ import annotations

import json

import pytest
import run_gb2_s20qpk_profile_stability_equivalence_audit as smoke

HASH = "sha256:" + "a" * 64
SELECTION_HASH = "sha256:" + "b" * 64


def _selection() -> dict:
    return {
        "status": "NO_ADMISSIBLE_PROFILE",
        "selection_hash": SELECTION_HASH,
        "holdout_access_permitted": False,
        "binding": {"source_collection_hash": HASH},
    }


def _p_i_source() -> dict:
    return {
        "status": "PASS",
        "collection": {
            "collection_hash": HASH,
            "dataset": {"holdout_status": "SEALED_NOT_ACCESSED"},
        },
    }


def _p_j_source() -> dict:
    return {"status": "PASS", "selection": _selection()}


def _audit(*, decision: str = "DISTINCT_PROFILES_FRESH_DESIGN_REQUIRED") -> dict:
    return {
        "status": "DIAGNOSED",
        "decision": decision,
        "source_binding": {"collection_hash": HASH},
        "dataset": {
            "partition": "CALIBRATION",
            "scenario_count": 80,
            "package_count": 160,
        },
        "equivalence_family_authorized": False,
        "empirical_equivalence": {
            "score_ordering_agreement_rate": 0.9,
            "oof_decision_disagreement_rate": 0.01,
        },
        "semantic_equivalence": {
            "checks": {
                "feature_dependency_sets_equal": False,
                "counterfactual_responses_equivalent": False,
            }
        },
        "next_contract": {
            "holdout_access_permitted": False,
            "runtime_activation_permitted": False,
        },
    }


def _builder(collection, cases):
    assert collection["collection_hash"] == HASH
    assert cases
    return [{"sample": True}]


def test_skip_profile_and_missing_source_guards(tmp_path) -> None:
    assert smoke.run_gb2_s20qpk_profile_stability_equivalence_audit({})[
        "status"
    ] == "SKIPPED"
    assert smoke.run_gb2_s20qpk_profile_stability_equivalence_audit(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )["failure_code"] == "profile_not_allowed"
    assert smoke.run_gb2_s20qpk_profile_stability_equivalence_audit(
        {
            smoke.SMOKE_ENV: "1",
            smoke.P_I_SOURCE_ENV: str(tmp_path / "missing.json"),
        },
        p_j_source=_p_j_source(),
    )["failure_code"] == "p_i_evidence_missing"
    assert smoke.run_gb2_s20qpk_profile_stability_equivalence_audit(
        {
            smoke.SMOKE_ENV: "1",
            smoke.P_J_SOURCE_ENV: str(tmp_path / "missing.json"),
        },
        p_i_source=_p_i_source(),
    )["failure_code"] == "p_j_evidence_missing"


def test_invalid_source_guard(tmp_path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    result = smoke.run_gb2_s20qpk_profile_stability_equivalence_audit(
        {smoke.SMOKE_ENV: "1", smoke.P_I_SOURCE_ENV: str(invalid)},
        p_j_source=_p_j_source(),
    )
    assert result["failure_code"] == "p_i_evidence_invalid"


def test_runner_loads_both_sources_from_protected_paths(tmp_path) -> None:
    p_i_path = tmp_path / "p_i.json"
    p_j_path = tmp_path / "p_j.json"
    p_i_path.write_text(json.dumps(_p_i_source()), encoding="utf-8")
    p_j_path.write_text(json.dumps(_p_j_source()), encoding="utf-8")

    result = smoke.run_gb2_s20qpk_profile_stability_equivalence_audit(
        {
            smoke.SMOKE_ENV: "1",
            smoke.P_I_SOURCE_ENV: str(p_i_path),
            smoke.P_J_SOURCE_ENV: str(p_j_path),
        },
        sample_builder=_builder,
        auditor=lambda *_args, **_kwargs: _audit(),
    )

    assert result["status"] == "PASS"


def test_runner_accepts_diagnosed_fail_closed_audit() -> None:
    result = smoke.run_gb2_s20qpk_profile_stability_equivalence_audit(
        {smoke.SMOKE_ENV: "1"},
        p_i_source=_p_i_source(),
        p_j_source=_p_j_source(),
        sample_builder=_builder,
        auditor=lambda *_args, **_kwargs: _audit(),
    )

    assert result["status"] == "PASS"
    assert result["new_provider_calls"] == 0
    assert result["new_database_calls"] == 0
    assert result["decision"] == "DISTINCT_PROFILES_FRESH_DESIGN_REQUIRED"
    assert "holdout=sealed" in smoke.summary_line(result)


def test_runner_reports_source_drift_and_audit_exception() -> None:
    p_j = _p_j_source()
    p_j["status"] = "FAIL"
    result = smoke.run_gb2_s20qpk_profile_stability_equivalence_audit(
        {smoke.SMOKE_ENV: "1"},
        p_i_source=_p_i_source(),
        p_j_source=p_j,
        sample_builder=_builder,
        auditor=lambda *_args, **_kwargs: _audit(),
    )
    assert result["status"] == "FAIL"
    assert result["failed_checks"] == ["p_j_evidence_passed"]

    result = smoke.run_gb2_s20qpk_profile_stability_equivalence_audit(
        {smoke.SMOKE_ENV: "1"},
        p_i_source=_p_i_source(),
        p_j_source=_p_j_source(),
        sample_builder=lambda *_args: (_ for _ in ()).throw(ValueError("bad")),
    )
    assert result["failure_code"] == "profile_equivalence_audit_failed"
    assert result["failure_detail"] == {"exception": "ValueError"}


def test_redaction_helpers_and_main(tmp_path, monkeypatch, capsys) -> None:
    dataset = json.loads(smoke.DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="source text"):
        smoke._assert_text_free({"leak": dataset["cases"][0]["query"]}, dataset)
    with pytest.raises(TypeError, match="cases"):
        smoke._assert_text_free({}, {"cases": {}})
    with pytest.raises(TypeError, match="mapping"):
        smoke._mapping([], "mapping")
    assert "=skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "bad" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "bad"}
    )

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpk_profile_stability_equivalence_audit",
        lambda: {"status": "PASS", "audit": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text(encoding="utf-8")
    assert "=pass" in capsys.readouterr().out


def test_runner_rejects_source_text_in_audit() -> None:
    dataset = json.loads(smoke.DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
    audit = _audit()
    audit["leak"] = dataset["cases"][0]["query"]
    result = smoke.run_gb2_s20qpk_profile_stability_equivalence_audit(
        {smoke.SMOKE_ENV: "1"},
        p_i_source=_p_i_source(),
        p_j_source=_p_j_source(),
        sample_builder=_builder,
        auditor=lambda *_args, **_kwargs: audit,
    )
    assert result["failure_code"] == "protected_evidence_contains_source_text"
