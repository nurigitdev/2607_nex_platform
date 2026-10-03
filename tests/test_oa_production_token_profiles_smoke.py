from __future__ import annotations

import json

import run_oa_production_token_profiles as smoke


def test_production_token_profile_evidence_passes() -> None:
    result = smoke.run_oa_production_token_profiles()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert set(result["profiles"]) == {
        "service_access",
        "delegated_user_access",
    }
    assert result["claim_encoding"]["session"] == "non_secret_session_ref_only"


def test_summary_and_main_cover_pass_and_failure(monkeypatch, capsys) -> None:
    passing = smoke.run_oa_production_token_profiles()
    assert smoke.summary_line(passing) == (
        "oa_production_token_profiles=pass profiles=2 "
        "issuer=urn:nex-platform:oa next=1245"
    )
    assert smoke.main(["--summary"]) == 0
    assert "profiles=2" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_oa_production_token_profiles",
        lambda: {"status": "FAIL", "profiles": {}, "next_slice": "1245"},
    )
    assert smoke.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
