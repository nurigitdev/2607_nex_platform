from __future__ import annotations

import run_mo_provider_telemetry_runtime as runner


def test_runtime_smoke_selects_store_by_persistence_mode() -> None:
    evidence = runner.run_mo_provider_telemetry_runtime()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["summary"] == {
        "runtime_mode_count": 2,
        "capability_count": 3,
        "durable_store_count": 1,
    }


def test_runtime_smoke_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_telemetry_runtime()
    assert "telemetry_runtime=pass" in runner.summary_line(passing)

    monkeypatch.setattr(runner, "run_mo_provider_telemetry_runtime", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "next=1157" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_telemetry_runtime",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
