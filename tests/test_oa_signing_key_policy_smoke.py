from __future__ import annotations

import json

import run_oa_signing_key_policy as smoke


def test_signing_key_policy_evidence_passes() -> None:
    result = smoke.run_oa_signing_key_policy()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["policy"]["production_custody_schemes"] == (
        "kms",
        "pkcs11",
        "vault",
    )
    assert "external_private_key_locator_only" in result["database_storage"]


def test_summary_and_main_cover_pass_and_failure(monkeypatch, capsys) -> None:
    passing = smoke.run_oa_signing_key_policy()
    assert smoke.summary_line(passing) == (
        "oa_signing_key_policy=pass alg=RS256 rsa_bits=3072 next=1246"
    )
    assert smoke.main(["--summary"]) == 0
    assert "alg=RS256" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_oa_signing_key_policy",
        lambda: {"status": "FAIL", "policy": {}, "next_slice": "1246"},
    )
    assert smoke.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
