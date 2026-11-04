from __future__ import annotations

import run_gb2_s20qpe_package_ordinal_calibrator_contract as smoke


def test_skip_and_profile_guard() -> None:
    skipped = smoke.run_gb2_s20qpe_package_ordinal_calibrator_contract({})
    denied = smoke.run_gb2_s20qpe_package_ordinal_calibrator_contract(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("=skipped")
    assert denied["failure_code"] == "profile_not_allowed"


def test_contract_fixture_is_directional_but_not_admitted() -> None:
    result = smoke.run_gb2_s20qpe_package_ordinal_calibrator_contract(
        {smoke.SMOKE_ENV: "1"}
    )

    assert result["status"] == "PASS"
    assert result["provider_calls"] == 0
    assert result["holdout_opened"] is False
    assert all(row["directional"] for row in result["design_fixture"])
    assert result["design"]["safety"]["runtime_activation_permitted"] is False
    assert "profiles=4" in smoke.summary_line(result)


def test_main_writes_evidence_and_failure_summary(tmp_path, monkeypatch, capsys) -> None:
    output = tmp_path / "contract.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpe_package_ordinal_calibrator_contract",
        lambda: {"status": "PASS"},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text(encoding="utf-8")
    assert "=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpe_package_ordinal_calibrator_contract",
        lambda: {"status": "FAIL", "failed_checks": ["forced"]},
    )
    assert smoke.main(["--summary"]) == 1
    assert "checks=forced" in capsys.readouterr().out
