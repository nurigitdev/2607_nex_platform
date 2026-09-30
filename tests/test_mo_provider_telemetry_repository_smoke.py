from __future__ import annotations

import run_mo_provider_telemetry_repository as runner


def test_repository_smoke_proves_restart_and_cleanup() -> None:
    evidence = runner.run_mo_provider_telemetry_repository()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["summary"] == {
        "migration_present": True,
        "row_count": 1,
        "request_count": 1,
        "attempt_count": 2,
        "retry_count": 1,
        "cleanup_count": 1,
    }


def test_repository_smoke_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_telemetry_repository()
    assert "repository=pass" in runner.summary_line(passing)

    monkeypatch.setattr(runner, "run_mo_provider_telemetry_repository", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "next=1155" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_telemetry_repository",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
