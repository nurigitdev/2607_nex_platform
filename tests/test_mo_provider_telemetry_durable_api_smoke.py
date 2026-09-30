from __future__ import annotations

import run_mo_provider_telemetry_durable_api as runner


def test_durable_api_smoke_proves_auth_restart_privacy_and_cleanup() -> None:
    evidence = runner.run_mo_provider_telemetry_durable_api()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["summary"] == {
        "unauthorized_status": 401,
        "authenticated_status": 200,
        "wire_field_count": 26,
        "request_count": 1,
        "cleanup_count": 1,
    }


def test_durable_api_smoke_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_telemetry_durable_api()
    assert "durable_api=pass" in runner.summary_line(passing)

    monkeypatch.setattr(runner, "run_mo_provider_telemetry_durable_api", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "next=1159" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_telemetry_durable_api",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
