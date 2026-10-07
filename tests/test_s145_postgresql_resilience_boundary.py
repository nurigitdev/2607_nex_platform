from __future__ import annotations

from pathlib import Path

import run_s145_postgresql_resilience_boundary as boundary


def test_repository_boundary_freezes_s145_scope() -> None:
    result = boundary.run_postgresql_resilience_boundary()
    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "required_path_count": len(boundary.REQUIRED_PATHS),
        "check_count": 13, "gap_count": 8, "slice_count": 10,
        "database_count": 5, "missing_path_count": 0,
    }
    assert result["decision"]["high_availability_in_scope"] is False
    assert result["decision"]["recovery_mode"] == "OPERATOR_CONTROLLED_COLD_RECOVERY"
    assert result["decision"]["next_slice"] == "1444"


def test_gap_inventory_is_exact_and_open() -> None:
    result = boundary.run_postgresql_resilience_boundary()
    assert [item["gap_id"] for item in result["gaps"]] == [item.gap_id for item in boundary.POSTGRES_RESILIENCE_GAPS]
    assert all(item["state"] == "OPEN" for item in result["gaps"])
    assert result["gaps"][-1]["target_slices"] == ["1450", "1451", "1452"]


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = boundary.run_postgresql_resilience_boundary(tmp_path)
    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["missing_path_count"] == len(boundary.REQUIRED_PATHS)
    assert result["decision"]["next_slice"] == "blocked"
    assert result["issues"]


def test_helpers_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source"
    source.write_text('{"value": 1}', encoding="utf-8")
    assert boundary._read_text(source) == '{"value": 1}'
    assert boundary._read_text(tmp_path / "missing") == ""
    assert boundary._read_json(source) == {"value": 1}
    invalid = tmp_path / "invalid"
    invalid.write_text("[]", encoding="utf-8")
    assert boundary._read_json(invalid) == {}
    assert boundary._read_json(tmp_path / "absent") == {}

    passing = boundary.run_postgresql_resilience_boundary()
    assert boundary.summary_line(passing) == (
        "postgresql_resilience_boundary=pass checks=13/13 databases=5 gaps=8 ha=false next=1444"
    )
    failing = {"status": "FAIL", "issues": ["one"]}
    assert boundary.summary_line(failing) == "postgresql_resilience_boundary=fail issues=1"

    monkeypatch.setattr(boundary, "run_postgresql_resilience_boundary", lambda: passing)
    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(boundary, "run_postgresql_resilience_boundary", lambda: failing)
    assert boundary.main([]) == 1
