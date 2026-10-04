from __future__ import annotations

from pathlib import Path

import run_platform_runtime_topology_boundary as boundary


def test_repository_boundary_passes() -> None:
    result = boundary.run_platform_runtime_topology_boundary()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["decision"]["service_count"] == 5
    assert result["decision"]["ae_web_required"] is True
    assert result["decision"]["cross_service_database_reads_allowed"] is False
    assert result["decision"]["postgres_restart_evidence_required"] is False
    assert result["decision"]["remote_provider_evidence_required"] is False
    assert result["decision"]["next_requirement"] == "S133"
    assert result["slice_plan"] == [str(value) for value in range(1312, 1322)]
    assert result["quality_cadence"]["checkpoint_gate"] == "1316"
    assert result["quality_cadence"]["full_gate"] == "1321"


def test_boundary_reports_missing_repository(tmp_path: Path) -> None:
    result = boundary.run_platform_runtime_topology_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert not any(result["checks"].values())
    assert any(item["category"] == "path_missing" for item in result["issues"])
    assert any(item["category"] == "token_missing" for item in result["issues"])


def test_helpers_cover_missing_files_and_groups(tmp_path: Path) -> None:
    present = tmp_path / "present.md"
    present.write_text("value", encoding="utf-8")
    items = [
        {"group": "ready", "present": True},
        {"group": "blocked", "present": False},
    ]

    assert boundary._read_text(present) == "value"
    assert boundary._read_text(tmp_path / "missing.md") == ""
    assert boundary._groups_present(items, "ready") is True
    assert boundary._groups_present(items, "ready", "blocked") is False
    assert boundary._groups_present(items, "missing") is False


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "decision": {
            "service_count": 5,
            "local_mock_actual_process_smoke_required": True,
            "postgres_restart_evidence_required": False,
            "remote_provider_evidence_required": False,
            "next_requirement": "S133",
        },
    }
    assert boundary.summary_line(passing) == (
        "platform_runtime_topology_boundary=pass services=5+web "
        "process_smoke=True postgres_restart=False live=False next=S133"
    )
    assert boundary.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_runtime_topology_boundary=fail issues=1"
    )

    monkeypatch.setattr(boundary, "run_platform_runtime_topology_boundary", lambda: passing)
    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        boundary,
        "run_platform_runtime_topology_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1
