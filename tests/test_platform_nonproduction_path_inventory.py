from __future__ import annotations

from pathlib import Path

import run_platform_nonproduction_path_inventory as inventory


def test_repository_inventory_classifies_nonproduction_paths() -> None:
    result = inventory.run_platform_nonproduction_path_inventory()

    assert result["status"] == "PASS", result
    assert result["issues"] == []
    assert all(result["checks"].values())
    assert result["summary"] == {
        "path_count": 9,
        "evidence_anchor_count": 15,
        "path_class_count": 5,
        "production_forbidden_count": 9,
        "transition_requirement_count": 6,
    }
    assert all(
        record["production_disposition"] == "FORBIDDEN_IN_PRODUCTION"
        for record in result["records"]
    )
    assert result["decision"] == {
        "retain_nonproduction_regression_paths": True,
        "silent_production_fallback_allowed": False,
        "production_connection_required": False,
        "next_slice": "1405",
    }


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = inventory.run_platform_nonproduction_path_inventory(tmp_path)

    assert result["status"] == "FAIL"
    assert result["issues"] == [
        "all_evidence_anchors_present",
        "all_records_documented",
        "production_profile_is_nonmock",
    ]
    assert result["decision"]["next_slice"] == "blocked"
    assert all(
        not record["checks"]["evidence_present"] for record in result["records"]
    )


def test_text_and_summary_branches(tmp_path: Path) -> None:
    assert inventory._read_text(tmp_path / "missing") == ""
    source = tmp_path / "source"
    source.write_text("present", encoding="utf-8")
    assert inventory._read_text(source) == "present"

    passing = inventory.run_platform_nonproduction_path_inventory()
    assert inventory.summary_line(passing) == (
        "platform_nonproduction_path_inventory=pass paths=9 anchors=15 "
        "classes=5 forbidden=9 targets=6 next=1405"
    )
    assert inventory.summary_line({"status": "FAIL", "issues": [1, 2]}) == (
        "platform_nonproduction_path_inventory=fail issues=2"
    )


def test_main_outputs_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = inventory.run_platform_nonproduction_path_inventory()
    monkeypatch.setattr(
        inventory, "run_platform_nonproduction_path_inventory", lambda: passing
    )
    assert inventory.main(["--summary"]) == 0
    assert "inventory=pass" in capsys.readouterr().out
    assert inventory.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        inventory,
        "run_platform_nonproduction_path_inventory",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert inventory.main([]) == 1
