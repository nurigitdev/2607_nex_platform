from __future__ import annotations

import json

import run_oa_token_rollout_plan as rollout


def test_token_rollout_plan_passes() -> None:
    result = rollout.run_oa_token_rollout_plan()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["rollout_units"] == (
        "shared_verifier_and_oa_issuer",
        "nex-ae-api",
        "nex-cx",
        "nex-mo",
        "nex-ag",
    )
    assert result["rollback_policy"] == (
        "stop_forward_rollout_never_auto_broaden_trust"
    )


def test_summary_and_main_cover_pass_and_failure(monkeypatch, capsys) -> None:
    passing = rollout.run_oa_token_rollout_plan()
    assert rollout.summary_line(passing) == (
        "oa_token_rollout_plan=pass profiles=3 units=5 next=1249"
    )
    assert rollout.main(["--summary"]) == 0
    assert "plan=pass" in capsys.readouterr().out
    assert rollout.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        rollout,
        "run_oa_token_rollout_plan",
        lambda: {"status": "FAIL", "profiles": {}, "next_slice": "1249"},
    )
    assert rollout.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
