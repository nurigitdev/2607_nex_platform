from __future__ import annotations

import run_gb2_s20qpb_candidate_probability_package_signal as smoke


def test_skip_and_profile_guard() -> None:
    skipped = smoke.run_gb2_s20qpb_candidate_probability_package_signal({})
    denied = smoke.run_gb2_s20qpb_candidate_probability_package_signal(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("=skipped")
    assert denied == {
        "evidence_schema_version": smoke.SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "profile_not_allowed",
    }


def test_design_fixture_is_directional_and_fail_closed() -> None:
    result = smoke.run_gb2_s20qpb_candidate_probability_package_signal(
        {smoke.SMOKE_ENV: "1"}
    )

    assert result["status"] == "PASS"
    assert result["provider_calls"] == 0
    assert result["database_calls"] == 0
    assert result["holdout_opened"] is False
    assert result["package_signal"]["positive_ready_probability"] > (
        result["package_signal"]["negative_ready_probability"]
    )
    assert result["checks"]["ready_decision_deferred"] is True
    assert result["failed_checks"] == []
    assert "holdout=sealed" in smoke.summary_line(result)


def test_main_writes_evidence_and_returns_status(tmp_path, monkeypatch, capsys) -> None:
    output = tmp_path / "evidence.json"
    monkeypatch.setenv(smoke.SMOKE_ENV, "1")

    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text(encoding="utf-8")
    assert "candidate_probability_package_signal=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpb_candidate_probability_package_signal",
        lambda: {"status": "FAIL", "failed_checks": ["forced"]},
    )
    assert smoke.main([]) == 1
