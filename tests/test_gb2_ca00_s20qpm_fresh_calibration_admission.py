from __future__ import annotations

import json

import run_gb2_s20qpm_fresh_calibration_admission as smoke


def _source() -> dict:
    return json.loads(smoke.P_L_SOURCE_PATH.read_text(encoding="utf-8"))


def _admission() -> dict:
    return {
        "status": "ADMITTED_FRESH_CALIBRATION_ONLY",
        "dataset_hash": "sha256:" + "a" * 64,
        "scenario_count": 100,
        "package_count": 200,
        "candidate_count": 800,
        "holdout_case_count": 0,
        "provider_calls": 0,
        "runtime_activation_permitted": False,
    }


def test_skip_profile_and_failure_guards() -> None:
    assert smoke.run_gb2_s20qpm_fresh_calibration_admission({})["status"] == (
        "SKIPPED"
    )
    assert smoke.run_gb2_s20qpm_fresh_calibration_admission(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )["failure_code"] == "profile_not_allowed"
    assert smoke.run_gb2_s20qpm_fresh_calibration_admission(
        {smoke.SMOKE_ENV: "1", smoke.P_L_SOURCE_ENV: "/missing"}
    )["failure_code"] == "fresh_calibration_admission_failed"


def test_runner_passes_and_reports_source_failure() -> None:
    result = smoke.run_gb2_s20qpm_fresh_calibration_admission(
        {smoke.SMOKE_ENV: "1"},
        p_l_source=_source(),
        design={},
        predecessor_cases=[],
        builder=lambda *_args, **_kwargs: {},
        admitter=lambda *_args, **_kwargs: _admission(),
    )
    assert result["status"] == "PASS"
    assert result["new_provider_calls"] == 0
    assert "scenarios=100" in smoke.summary_line(result)

    source = _source()
    source["status"] = "FAIL"
    result = smoke.run_gb2_s20qpm_fresh_calibration_admission(
        {smoke.SMOKE_ENV: "1"},
        p_l_source=source,
        design={},
        predecessor_cases=[],
        builder=lambda *_args, **_kwargs: {},
        admitter=lambda *_args, **_kwargs: _admission(),
    )
    assert result["status"] == "FAIL"
    assert result["failed_checks"] == ["p_l_evidence_passed"]


def test_default_loading_helpers_and_main(tmp_path, monkeypatch, capsys) -> None:
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(_source()), encoding="utf-8")
    result = smoke.run_gb2_s20qpm_fresh_calibration_admission(
        {smoke.SMOKE_ENV: "1", smoke.P_L_SOURCE_ENV: str(source_path)},
        builder=lambda *_args, **_kwargs: {},
        admitter=lambda *_args, **_kwargs: _admission(),
    )
    assert result["status"] == "PASS"
    assert "=skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "bad" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "bad"}
    )

    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    try:
        smoke._load(invalid)
    except TypeError as exc:
        assert "object" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-object JSON must fail")
    try:
        smoke._mapping([], "value")
    except TypeError as exc:
        assert "value" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-mapping value must fail")

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpm_fresh_calibration_admission",
        lambda: {"status": "PASS", "admission": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text()
    assert "=pass" in capsys.readouterr().out
