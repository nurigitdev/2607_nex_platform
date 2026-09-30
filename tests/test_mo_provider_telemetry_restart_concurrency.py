from __future__ import annotations

import run_mo_provider_telemetry_restart_concurrency as runner


def test_restart_concurrency_smoke_proves_atomic_recovery() -> None:
    evidence = runner.run_mo_provider_telemetry_restart_concurrency()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["summary"] == {
        "worker_count": 8,
        "mutation_count": 40,
        "request_count": 40,
        "attempt_count": 40,
        "cleanup_count": 1,
    }


def test_restart_concurrency_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_telemetry_restart_concurrency()
    assert "restart_concurrency=pass" in runner.summary_line(passing)

    monkeypatch.setattr(
        runner,
        "run_mo_provider_telemetry_restart_concurrency",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "next=1158" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_telemetry_restart_concurrency",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
