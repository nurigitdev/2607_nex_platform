from __future__ import annotations

import run_platform_runtime_orchestrator as smoke


def test_runtime_orchestrator_evidence_passes() -> None:
    result = smoke.run_platform_runtime_orchestrator()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["decision"]["actual_processes_spawned"] is False


def test_summary_and_main(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_runtime_orchestrator()
    assert smoke.summary_line(passing) == (
        "platform_runtime_orchestrator=pass ready=13 started=13 next=1320"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_runtime_orchestrator=fail issues=1"
    )

    monkeypatch.setattr(smoke, "run_platform_runtime_orchestrator", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "orchestrator=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_platform_runtime_orchestrator",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert smoke.main([]) == 1


def test_simulated_handle_kill_path() -> None:
    handle = smoke._Handle("worker", [])

    handle.kill()

    assert handle.poll() == -9
