from __future__ import annotations

import json

import pytest
import run_gb2_s20qpo_canonical_threshold_admission as smoke

DATASET_HASH = "sha256:" + "a" * 64


def _p_l() -> dict:
    return {"status": "PASS", "freeze": {}}


def _p_m() -> dict:
    return {"status": "PASS", "admission": {"dataset_hash": DATASET_HASH}}


def _p_n() -> dict:
    return {
        "status": "PASS",
        "artifact_evidence_hash": "sha256:" + "b" * 64,
        "checks": {"complete": True},
        "collection": {
            "collection_hash": "sha256:" + "c" * 64,
            "provider_binding": {"model_revision": "hf:" + "d" * 40},
        },
    }


def _dataset(*_args, **_kwargs) -> dict:
    return {
        "dataset_id": "fresh-dataset",
        "cases": [
            {
                "query": "private query",
                "candidates": [{"text": "private candidate"}],
            }
        ],
    }


def _calibration(*_args, admitted: bool = True, **_kwargs) -> dict:
    return {
        "status": (
            "CALIBRATION_THRESHOLD_CANDIDATE_ADMITTED"
            if admitted
            else "NO_ADMISSIBLE_THRESHOLD"
        ),
        "dataset": {"dataset_sha256": DATASET_HASH},
        "protocol": {
            "profile_count": 1,
            "profile_id": "answer-support-contradiction-aware-v2",
        },
        "outer_folds": [{"fold_index": index} for index in range(5)],
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
        "holdout": {"status": "SEALED_NOT_OPENED"},
        "candidate": (
            {"threshold": 0.5, "profile_id": "answer-support-contradiction-aware-v2"}
            if admitted
            else None
        ),
        "oof_evaluation": {"package_auc": 1.0},
    }


def _run(*, calibrator=_calibration, **overrides) -> dict:
    values = {
        "p_l_source": _p_l(),
        "p_m_source": _p_m(),
        "p_n_source": _p_n(),
        "canonical_design": {},
        "fresh_design": {},
        "calibration_design": {},
        "builder": _dataset,
        "sample_builder": lambda *_args: [],
        "calibrator": calibrator,
    }
    values.update(overrides)
    return smoke.run_gb2_s20qpo_canonical_threshold_admission(
        {smoke.SMOKE_ENV: "1"}, **values
    )


def test_skip_profile_and_missing_source_guards() -> None:
    assert smoke.run_gb2_s20qpo_canonical_threshold_admission({})["status"] == (
        "SKIPPED"
    )
    assert smoke.run_gb2_s20qpo_canonical_threshold_admission(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )["failure_code"] == "profile_not_allowed"
    result = smoke.run_gb2_s20qpo_canonical_threshold_admission(
        {
            smoke.SMOKE_ENV: "1",
            smoke.P_L_SOURCE_ENV: "/missing/p-l.json",
        }
    )
    assert result["failure_code"] == "canonical_threshold_calibration_failed"


def test_runner_accepts_candidate_and_fail_closed_outcome() -> None:
    result = _run()
    assert result["status"] == "PASS"
    assert result["decision"] == (
        "CANONICAL_THRESHOLD_CANDIDATE_ADMITTED_HOLDOUT_REQUIRED"
    )
    assert result["new_provider_calls"] == 0
    assert "threshold=0.5" in smoke.summary_line(result)

    result = _run(calibrator=lambda *_args, **_kwargs: _calibration(admitted=False))
    assert result["status"] == "PASS"
    assert result["decision"] == (
        "NO_ADMISSIBLE_THRESHOLD_HOLDOUT_REMAINS_SEALED"
    )


def test_runner_reports_failed_source_check_and_calibration_exception() -> None:
    p_n = _p_n()
    p_n["status"] = "FAIL"
    result = _run(p_n_source=p_n)
    assert result["status"] == "FAIL"
    assert "p_n_provider_collection_passed" in result["failed_checks"]

    result = _run(
        calibrator=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError())
    )
    assert result["failure_code"] == "canonical_threshold_calibration_failed"
    assert result["failure_detail"] == {"exception": "ValueError"}


def test_runner_rejects_malformed_decision_and_text_leak() -> None:
    malformed = _calibration()
    malformed["candidate"] = None
    result = _run(calibrator=lambda *_args, **_kwargs: malformed)
    assert result["status"] == "FAIL"
    assert "threshold_decision_is_fail_closed" in result["failed_checks"]

    leaked = _calibration()
    leaked["leak"] = "private query"
    result = _run(calibrator=lambda *_args, **_kwargs: leaked)
    assert result["failure_code"] == "protected_evidence_contains_source_text"


def test_helpers_summary_and_main(tmp_path, monkeypatch, capsys) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_p_l()), encoding="utf-8")
    assert smoke._source(None, str(source), tmp_path / "unused") == _p_l()

    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="object"):
        smoke._load(invalid)
    with pytest.raises(TypeError, match="mapping"):
        smoke._mapping([], "mapping")
    with pytest.raises(TypeError, match="cases"):
        smoke._assert_text_free({}, {"cases": {}})
    assert "=skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "bad" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "bad"}
    )

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpo_canonical_threshold_admission",
        lambda: {"status": "PASS", "calibration": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text()
    assert "=pass" in capsys.readouterr().out
