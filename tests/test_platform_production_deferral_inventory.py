from __future__ import annotations

from pathlib import Path

import run_platform_production_deferral_inventory as inventory


def test_repository_inventory_traces_all_nine_deferrals() -> None:
    result = inventory.run_platform_production_deferral_inventory()

    assert result["status"] == "PASS", result
    assert result["issues"] == []
    assert all(result["checks"].values())
    assert len(result["records"]) == 9
    assert result["runtime_deferral_ids"] == [
        item.deferral_id for item in inventory.DEFERRAL_REGISTRY
    ]
    assert result["summary"] == {
        "runtime_deferral_count": 9,
        "registered_deferral_count": 9,
        "documented_deferral_count": 9,
        "owner_count": 6,
        "target_requirement_count": 7,
        "open_deferral_count": 9,
    }
    assert result["decision"]["next_slice"] == "1404"
    assert result["decision"]["production_deployment_approved"] is False


def test_runtime_inventory_drift_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / inventory.SOURCE_PATH
    source.parent.mkdir(parents=True)
    source.write_text("DEPLOYMENT_DEFERRALS = ('unexpected',)\n", encoding="utf-8")
    plan = tmp_path / inventory.PLAN_PATH
    plan.parent.mkdir(parents=True)
    plan.write_text("production deployment remains unapproved", encoding="utf-8")

    result = inventory.run_platform_production_deferral_inventory(tmp_path)

    assert result["status"] == "FAIL"
    assert "runtime_inventory_exact" in result["issues"]
    assert "all_records_complete" in result["issues"]
    assert result["decision"]["next_slice"] == "blocked"


def test_ast_loader_rejects_missing_invalid_and_non_tuple_values(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    assert inventory._load_string_tuple(source, "ITEMS") == ()

    source.write_text("not valid python =", encoding="utf-8")
    assert inventory._load_string_tuple(source, "ITEMS") == ()

    source.write_text("ITEMS = unknown_name\n", encoding="utf-8")
    assert inventory._load_string_tuple(source, "ITEMS") == ()

    source.write_text("ITEMS = ['one']\n", encoding="utf-8")
    assert inventory._load_string_tuple(source, "ITEMS") == ()

    source.write_text("OTHER = ('one',)\n", encoding="utf-8")
    assert inventory._load_string_tuple(source, "ITEMS") == ()

    source.write_text("ITEMS: tuple[str, ...] = ('one',)\n", encoding="utf-8")
    assert inventory._load_string_tuple(source, "ITEMS") == ()

    source.write_text("ITEMS = ('one', 2)\n", encoding="utf-8")
    assert inventory._load_string_tuple(source, "ITEMS") == ()

    source.write_text("ITEMS = ('one', 'two')\n", encoding="utf-8")
    assert inventory._load_string_tuple(source, "ITEMS") == ("one", "two")


def test_text_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    assert inventory._read_text(tmp_path / "missing") == ""
    source = tmp_path / "text"
    source.write_text("evidence", encoding="utf-8")
    assert inventory._read_text(source) == "evidence"

    passing = inventory.run_platform_production_deferral_inventory()
    assert inventory.summary_line(passing) == (
        "platform_production_deferral_inventory=pass deferrals=9/9 "
        "documented=9/9 owners=6 targets=7 open=9 next=1404"
    )
    failing = {"status": "FAIL", "issues": ["one"]}
    assert inventory.summary_line(failing) == (
        "platform_production_deferral_inventory=fail issues=1"
    )

    monkeypatch.setattr(
        inventory, "run_platform_production_deferral_inventory", lambda: passing
    )
    assert inventory.main(["--summary"]) == 0
    assert "inventory=pass" in capsys.readouterr().out
    assert inventory.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        inventory,
        "run_platform_production_deferral_inventory",
        lambda: failing,
    )
    assert inventory.main([]) == 1
