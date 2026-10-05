from __future__ import annotations

import json
from pathlib import Path

import run_cx_grounded_generation_runtime_composition as smoke


def test_repository_grounded_generation_composition_passes() -> None:
    result = smoke.run_cx_grounded_generation_runtime_composition()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "check_count": 9,
        "passed_count": 9,
        "issue_count": 0,
    }
    assert result["decision"] == {
        "postgres_store": "restart_safe_owner_scoped",
        "local_store": "in_memory_compatibility",
        "sync_async_store_identity": "shared",
        "remote_provider_required": False,
        "next_slice": "1365",
    }


def test_empty_root_fails_composition_evidence(tmp_path: Path) -> None:
    result = smoke.run_cx_grounded_generation_runtime_composition(tmp_path)

    assert result["status"] == "FAIL"
    assert result["summary"]["passed_count"] == 0
    assert result["summary"]["issue_count"] == 9
    assert result["decision"]["next_slice"] == "blocked"
    assert smoke._read_text(tmp_path / "missing") == ""


def test_composition_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_cx_grounded_generation_runtime_composition()
    assert smoke.summary_line(passing) == (
        "cx_grounded_generation_composition=pass checks=9/9 issues=0 next=1365"
    )
    monkeypatch.setattr(
        smoke,
        "run_cx_grounded_generation_runtime_composition",
        lambda: passing,
    )
    assert smoke.main(["--summary"]) == 0
    assert "checks=9/9" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_cx_grounded_generation_runtime_composition",
        lambda: {"status": "FAIL", "summary": {}, "decision": {}},
    )
    assert smoke.main([]) == 1
