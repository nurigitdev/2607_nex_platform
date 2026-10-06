from __future__ import annotations

from pathlib import Path

import run_platform_operational_incompleteness_register as register


def test_repository_register_prioritizes_all_operational_gaps() -> None:
    result = register.run_platform_operational_incompleteness_register()

    assert result["status"] == "PASS", result
    assert result["issues"] == []
    assert all(result["checks"].values())
    assert result["summary"] == {
        "gap_count": 12,
        "p0_count": 8,
        "p1_count": 4,
        "domain_count": 5,
        "owner_count": 6,
        "target_requirement_count": 8,
        "deferral_coverage_count": 9,
        "open_count": 12,
    }
    assert all(item["state"] == "OPEN" for item in result["gaps"])
    assert result["decision"] == {
        "gap_inventory_is_completion_evidence": False,
        "production_admission_blocked": True,
        "production_connection_required": False,
        "next_slice": "1409",
    }


def test_empty_repository_fails_documentation_check(tmp_path: Path) -> None:
    result = register.run_platform_operational_incompleteness_register(tmp_path)

    assert result["status"] == "FAIL"
    assert result["issues"] == ["all_gap_records_complete"]
    assert result["decision"]["next_slice"] == "blocked"


def test_each_deferral_maps_to_exactly_one_operational_gap() -> None:
    sources = [
        source
        for item in register.OPERATIONAL_GAPS
        for source in item.source_deferrals
    ]
    assert len(sources) == 9
    assert len(set(sources)) == 9


def test_text_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    assert register._read_text(tmp_path / "missing") == ""
    source = tmp_path / "source"
    source.write_text("value", encoding="utf-8")
    assert register._read_text(source) == "value"

    passing = register.run_platform_operational_incompleteness_register()
    assert register.summary_line(passing) == (
        "platform_operational_incompleteness_register=pass gaps=12 p0=8 "
        "p1=4 deferrals=9/9 targets=8 open=12 next=1409"
    )
    failing = {"status": "FAIL", "issues": ["one"]}
    assert register.summary_line(failing) == (
        "platform_operational_incompleteness_register=fail issues=1"
    )

    monkeypatch.setattr(
        register, "run_platform_operational_incompleteness_register", lambda: passing
    )
    assert register.main(["--summary"]) == 0
    assert "register=pass" in capsys.readouterr().out
    assert register.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        register,
        "run_platform_operational_incompleteness_register",
        lambda: failing,
    )
    assert register.main([]) == 1
