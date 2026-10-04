from __future__ import annotations

import run_platform_endpoint_timeout_policy as smoke


def test_endpoint_timeout_policy_passes() -> None:
    result = smoke.run_platform_endpoint_timeout_policy()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["decision"]["cx_mo_timeout_inversion_closed"] is True
    assert result["decision"]["legacy_aliases_removed"] is False


def test_summary_and_main(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_endpoint_timeout_policy()
    assert smoke.summary_line(passing) == (
        "platform_endpoint_timeout_policy=pass endpoints=5 "
        "budgets=60/60/130 aliases=2 next=1317"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_endpoint_timeout_policy=fail issues=1"
    )

    monkeypatch.setattr(smoke, "run_platform_endpoint_timeout_policy", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "policy=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_endpoint_timeout_policy",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert smoke.main([]) == 1
