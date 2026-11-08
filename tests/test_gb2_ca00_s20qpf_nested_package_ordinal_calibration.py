from __future__ import annotations

import run_gb2_s20qpf_nested_package_ordinal_calibration as smoke


def _source() -> dict:
    return {
        "status": "PASS",
        "database_identity": {"database": "nex_cx_test", "role": "nex_cx_user"},
        "pipeline_repeatability": {"status": "STABLE"},
        "repeat_collection": {
            "runs": [{"candidate_observations": ["observation"]}]
        },
        "dataset": {
            "dataset_id": "dataset-v4",
            "dataset_sha256": "dataset-sha",
            "holdout_status": "SEALED_NOT_COLLECTED",
        },
        "binding": {},
        "provider_request_counts": {"total": 2240},
    }


def _selection(*, admitted: bool) -> dict:
    inner = [
        {
            "inner_folds": [
                {"candidate_probability_training_candidate_count": 384}
            ]
        }
    ]
    return {
        "status": (
            "CALIBRATION_OOF_ADMITTED" if admitted else "NO_ADMISSIBLE_PROFILE"
        ),
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
        "holdout": {"status": "SEALED_NOT_OPENED"},
        "outer_folds": [{"inner_selection": inner}],
        "oof_evaluation": {
            "metrics": {"ready_recall": 0.2, "false_ready_rate": 0.05}
        },
    }


def test_skip_profile_and_missing_source_guards(tmp_path) -> None:
    assert smoke.run_gb2_s20qpf_nested_package_ordinal_calibration({})[
        "status"
    ] == "SKIPPED"
    assert smoke.run_gb2_s20qpf_nested_package_ordinal_calibration(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )["failure_code"] == "profile_not_allowed"
    assert smoke.run_gb2_s20qpf_nested_package_ordinal_calibration(
        {smoke.SMOKE_ENV: "1", smoke.SOURCE_ENV: str(tmp_path / "missing.json")}
    )["failure_code"] == "source_evidence_missing"


def test_runner_accepts_fail_closed_no_profile(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "build_expanded_candidate_relevance_calibration_samples",
        lambda _rows: ["sample"],
    )
    monkeypatch.setattr(
        smoke,
        "select_nested_package_ordinal_profile",
        lambda *_args, **_kwargs: _selection(admitted=False),
    )
    result = smoke.run_gb2_s20qpf_nested_package_ordinal_calibration(
        {smoke.SMOKE_ENV: "1"}, source=_source()
    )

    assert result["status"] == "PASS"
    assert result["decision"] == "NO_ADMISSIBLE_PROFILE_STOP_BEFORE_P_G"
    assert result["provider_calls"] == 0
    assert result["holdout_opened"] is False
    assert "selection=NO_ADMISSIBLE_PROFILE" in smoke.summary_line(result)


def test_runner_reports_admitted_candidate_and_source_drift(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "build_expanded_candidate_relevance_calibration_samples",
        lambda _rows: ["sample"],
    )
    monkeypatch.setattr(
        smoke,
        "select_nested_package_ordinal_profile",
        lambda *_args, **_kwargs: _selection(admitted=True),
    )
    admitted = smoke.run_gb2_s20qpf_nested_package_ordinal_calibration(
        {smoke.SMOKE_ENV: "1"}, source=_source()
    )
    assert admitted["decision"] == "CALIBRATION_OOF_PROFILE_AVAILABLE_P_G_REQUIRED"

    source = _source()
    source["pipeline_repeatability"] = {"status": "UNSTABLE"}
    failed = smoke.run_gb2_s20qpf_nested_package_ordinal_calibration(
        {smoke.SMOKE_ENV: "1"}, source=source
    )
    assert failed["status"] == "FAIL"
    assert "uncertainty_aware_repeatability_stable" in failed["failed_checks"]


def test_missing_observations_and_main(tmp_path, monkeypatch, capsys) -> None:
    source = _source()
    source["repeat_collection"] = {}
    assert smoke.run_gb2_s20qpf_nested_package_ordinal_calibration(
        {smoke.SMOKE_ENV: "1"}, source=source
    )["failure_code"] == "candidate_observations_missing"

    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpf_nested_package_ordinal_calibration",
        lambda: {"status": "PASS", "selection": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text(encoding="utf-8")
    assert "=pass" in capsys.readouterr().out
