from __future__ import annotations

from pathlib import Path

import run_s148_observability_incident_boundary as boundary


def test_repository_boundary_freezes_s148_scope() -> None:
    result = boundary.run_observability_incident_boundary()

    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "required_path_count": len(boundary.REQUIRED_PATHS),
        "check_count": 12,
        "delivery_mode_count": 3,
        "service_owner_count": 5,
        "gap_count": 7,
        "slice_count": 10,
        "missing_path_count": 0,
    }
    assert result["decision"]["external_activation"] == "EXTERNAL_NOT_ACTIVATED"
    assert result["decision"]["next_slice"] == "1474"


def test_delivery_modes_and_service_owners_are_exact() -> None:
    result = boundary.run_observability_incident_boundary()

    assert result["delivery_modes"] == list(boundary.DELIVERY_MODES)
    assert result["service_owners"] == list(boundary.SERVICE_OWNERS)
    assert "endpoint" not in result["decision"]
    assert "credential" not in result["decision"]


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = boundary.run_observability_incident_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["missing_path_count"] == len(boundary.REQUIRED_PATHS)
    assert result["decision"]["next_slice"] == "blocked"
    assert result["issues"]


def test_helpers_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    assert boundary._read_text(tmp_path / "missing") == ""
    source = tmp_path / "source"
    source.write_text("value", encoding="utf-8")
    assert boundary._read_text(source) == "value"

    passing = boundary.run_observability_incident_boundary()
    assert boundary.summary_line(passing) == (
        "s148_observability_boundary=pass checks=12/12 modes=3 services=5 "
        "gaps=7 slices=10 next=1474"
    )
    assert boundary.summary_line({"status": "FAIL", "issues": ["one"]}) == (
        "s148_observability_boundary=fail issues=1"
    )
    monkeypatch.setattr(
        boundary,
        "run_observability_incident_boundary",
        lambda: passing,
    )
    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        boundary,
        "run_observability_incident_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1
