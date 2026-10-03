from __future__ import annotations

import json

import run_oa_token_validation_checkpoint as checkpoint


def test_token_validation_checkpoint_passes() -> None:
    result = checkpoint.run_oa_token_validation_checkpoint()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["http_failure_semantics"] == {
        "untrusted_or_inactive_token": 401,
        "insufficient_scope": 403,
        "required_trust_dependency_unavailable": 503,
    }


def test_summary_and_main_cover_pass_and_failure(monkeypatch, capsys) -> None:
    passing = checkpoint.run_oa_token_validation_checkpoint()
    assert checkpoint.summary_line(passing) == (
        "oa_token_validation_checkpoint=pass jwks_ttl=300 "
        "introspection_timeout=3 next=1247"
    )
    assert checkpoint.main(["--summary"]) == 0
    assert "checkpoint=pass" in capsys.readouterr().out
    assert checkpoint.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        checkpoint,
        "run_oa_token_validation_checkpoint",
        lambda: {"status": "FAIL", "policy": {}, "next_slice": "1247"},
    )
    assert checkpoint.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
