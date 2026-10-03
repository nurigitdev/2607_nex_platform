from __future__ import annotations

import run_oa_signed_token_api as smoke


def test_signed_token_api_evidence_passes() -> None:
    result = smoke.run_oa_signed_token_api()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["jwks_key_count"] == 1
    assert result["introspection_active"] is True


def test_signed_token_api_summary_and_main(capsys, monkeypatch) -> None:
    result = smoke.run_oa_signed_token_api()
    assert smoke.summary_line(result) == (
        "oa_signed_token_api=pass jwks=1 active=true next=1270"
    )
    assert smoke.main(["--summary"]) == 0
    assert "oa_signed_token_api=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_oa_signed_token_api",
        lambda: {
            "status": "FAIL",
            "jwks_key_count": 0,
            "introspection_active": False,
            "next_slice": "blocked",
        },
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
