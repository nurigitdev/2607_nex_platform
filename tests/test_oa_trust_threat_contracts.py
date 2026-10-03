from __future__ import annotations

import json

import run_oa_trust_threat_contracts as contracts


def test_trust_threat_contract_evidence_passes() -> None:
    result = contracts.run_oa_trust_threat_contracts()

    assert result["status"] == "PASS"
    assert result["threat_count"] == 8
    assert result["privacy_violation_count"] == 0
    assert all(result["checks"].values())


def test_summary_and_main_cover_pass_and_failure(monkeypatch, capsys) -> None:
    passing = contracts.run_oa_trust_threat_contracts()
    assert contracts.summary_line(passing) == (
        "oa_trust_threat_contracts=pass threats=8 "
        "privacy_violations=0 next=1250"
    )
    assert contracts.main(["--summary"]) == 0
    assert "contracts=pass" in capsys.readouterr().out
    assert contracts.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contracts,
        "run_oa_trust_threat_contracts",
        lambda: {
            "status": "FAIL",
            "threat_count": 0,
            "privacy_violation_count": 1,
            "next_slice": "1250",
        },
    )
    assert contracts.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
