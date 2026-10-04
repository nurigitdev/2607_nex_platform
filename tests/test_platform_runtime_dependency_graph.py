from __future__ import annotations

import run_platform_runtime_dependency_graph as smoke


def test_dependency_graph_evidence_passes() -> None:
    result = smoke.run_platform_runtime_dependency_graph()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["decision"]["local_mock_database_readiness_required"] is False
    assert result["decision"]["protected_database_readiness_required"] is True


def test_fixture_and_summary() -> None:
    manifest = smoke._manifest()
    assert len(manifest.processes) == 3

    passing = smoke.run_platform_runtime_dependency_graph()
    assert smoke.summary_line(passing) == (
        "platform_runtime_dependency_graph=pass layers=3 probes=2 "
        "local=liveness protected=readiness next=1316"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_runtime_dependency_graph=fail issues=1"
    )


def test_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_runtime_dependency_graph()
    monkeypatch.setattr(smoke, "run_platform_runtime_dependency_graph", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "graph=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_runtime_dependency_graph",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert smoke.main([]) == 1
