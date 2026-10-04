from __future__ import annotations

from pathlib import Path

import run_platform_persistence_worker_process_audit as audit


def test_repository_persistence_worker_process_audit_exposes_orchestration_gap() -> None:
    result = audit.run_platform_persistence_worker_process_audit()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["findings"]["service_count"] == 5
    assert result["findings"]["migration_counts"] == {
        "nex-oa": 17,
        "nex-ag": 19,
        "nex-ae-api": 23,
        "nex-cx": 21,
        "nex-mo": 9,
    }
    assert result["findings"]["migration_total"] == 89
    assert result["findings"]["worker_runtime_module_count"] == 7
    assert result["findings"]["executable_worker_runtime_count"] == 2
    assert all(result["findings"]["process_orchestration_gaps"].values())
    assert result["decision"]["current_run_all_services_is_release_orchestration"] is False
    assert result["decision"]["next_slice"] == "1310"


def test_audit_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = audit.run_platform_persistence_worker_process_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["issues"]
    assert result["findings"]["migration_total"] == 0
    assert result["findings"]["worker_runtime_module_count"] == 0


def test_read_text_and_summary_branches(tmp_path: Path) -> None:
    path = tmp_path / "source.py"
    path.write_text("source", encoding="utf-8")
    assert audit._read_text(path) == "source"
    assert audit._read_text(tmp_path / "missing.py") == ""

    passing = {
        "status": "PASS",
        "findings": {
            "service_count": 5,
            "migration_total": 89,
            "worker_runtime_module_count": 7,
            "process_orchestration_gaps": {"a": True, "b": False},
        },
        "decision": {"next_slice": "1310"},
    }
    assert audit.summary_line(passing) == (
        "platform_persistence_worker_process=pass services=5 migrations=89 "
        "worker_runtimes=7 process_gaps=1 next=1310"
    )
    assert audit.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_persistence_worker_process=fail issues=1"
    )


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "findings": {},
        "decision": {"next_slice": "1310"},
    }
    monkeypatch.setattr(
        audit,
        "run_platform_persistence_worker_process_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "worker_process=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        audit,
        "run_platform_persistence_worker_process_audit",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
