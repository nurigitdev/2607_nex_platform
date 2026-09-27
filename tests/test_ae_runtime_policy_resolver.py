from __future__ import annotations

import json

import run_ae_runtime_policy_resolver as smoke


def test_runtime_policy_smoke_passes() -> None:
    result = smoke.run_ae_runtime_policy_resolver()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["resolved_rule_count"] == 4
    assert result["remote_provider_required"] is False
    assert result["next_slice"] == "1026"


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_ae_runtime_policy_resolver()
    assert smoke.summary_line(passing) == (
        "ae_runtime_policy_resolver=pass checks=9/9 rules=4 next=1026"
    )
    assert smoke._rejection_code({"port": 9111}) == (
        "ae.provider_runtime_field_forbidden"
    )

    monkeypatch.setattr(smoke, "run_ae_runtime_policy_resolver", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "resolver=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_ae_runtime_policy_resolver",
        lambda: {"status": "FAIL", "checks": {}},
    )
    assert smoke.main([]) == 1
