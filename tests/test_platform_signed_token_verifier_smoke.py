from __future__ import annotations

import run_platform_signed_token_verifier as runner


def test_shared_verifier_accepts_oa_issued_service_token() -> None:
    evidence = runner.run_platform_signed_token_verifier()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["jwks_fetch_count"] == 1
    assert evidence["token_id_digest_length"] == 64
    assert evidence["next_slice"] == "1274"


def test_summary_and_main(capsys, monkeypatch) -> None:
    evidence = runner.run_platform_signed_token_verifier()

    assert runner.summary_line(evidence) == (
        "platform_signed_token_verifier=pass jwks_fetches=1 "
        "digest_length=64 next=1274"
    )
    monkeypatch.setattr(
        runner, "run_platform_signed_token_verifier", lambda: evidence
    )
    assert runner.main(["--summary"]) == 0
    assert "platform_signed_token_verifier=pass" in capsys.readouterr().out
    failed = {
        "status": "FAIL",
        "jwks_fetch_count": 0,
        "token_id_digest_length": 0,
        "next_slice": "blocked",
    }
    monkeypatch.setattr(
        runner, "run_platform_signed_token_verifier", lambda: failed
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
