from __future__ import annotations

import run_oa_token_validation as smoke


def test_token_validation_evidence_passes() -> None:
    result = smoke.run_oa_token_validation()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["active_before_revoke"] is True
    assert result["active_after_revoke"] is False


def test_token_validation_summary_and_main(capsys, monkeypatch) -> None:
    result = smoke.run_oa_token_validation()
    assert smoke.summary_line(result) == (
        "oa_token_validation=pass active_before=true active_after=false next=1269"
    )
    assert smoke.main(["--summary"]) == 0
    assert "oa_token_validation=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_oa_token_validation",
        lambda: {
            "status": "FAIL",
            "active_before_revoke": False,
            "active_after_revoke": False,
            "next_slice": "blocked",
        },
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
