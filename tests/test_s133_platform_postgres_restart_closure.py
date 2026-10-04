from __future__ import annotations

from pathlib import Path

import run_s133_platform_postgres_restart_closure as closure


def test_repository_closure_passes_and_hands_off_to_s134() -> None:
    result = closure.run_s133_platform_postgres_restart_closure()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["evidence_statuses"] == {
        "boundary": "PASS",
        "evidence": "PASS",
        "targets": "PASS",
        "migration": "SKIPPED",
        "pools": "SKIPPED",
        "startup": "SKIPPED",
        "state_machine": "PASS",
        "restoration": "SKIPPED",
        "restart": "SKIPPED",
    }
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 4,
        "protected_skip_count": 5,
        "check_count": 15,
        "passed_check_count": 15,
        "service_count": 5,
        "migration_count": 89,
        "process_count": 13,
        "pool_count_per_generation": 10,
        "restart_count": 1,
        "restored_service_count": 5,
        "typed_evidence_record_count": 60,
    }
    assert result["decision"]["completion_signal_met"] is True
    assert result["decision"]["closure_database_or_provider_mutation_performed"] is False
    assert result["decision"]["next_requirement"] == "S134"


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s133_platform_postgres_restart_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failed_checks"]
    assert result["summary"]["evidence_count"] == 0
    assert result["decision"]["next_requirement"] == "blocked"


def test_helpers_cover_mapping_text_and_noncanonical_root(tmp_path: Path) -> None:
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._run_evidence(tmp_path) == {}

    source = tmp_path / "source.md"
    source.write_text("content", encoding="utf-8")
    assert closure._read_text(source) == "content"
    source.write_text("line one\n  line two", encoding="utf-8")
    assert closure._normalized_text(source) == "line one line two"
    assert closure._read_text(tmp_path / "missing.md") == ""


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_evidence_count": 4,
            "protected_skip_count": 5,
            "evidence_count": 9,
            "passed_check_count": 15,
            "check_count": 15,
            "service_count": 5,
            "migration_count": 89,
            "process_count": 13,
        },
        "decision": {"next_requirement": "S134"},
    }
    assert closure.summary_line(passing) == (
        "s133_platform_postgres_restart_closure=pass evidence=4+5/9 "
        "checks=15/15 services=5 migrations=89 processes=13 next=S134"
    )
    assert closure.summary_line(
        {"status": "FAIL", "failed_checks": ["a"]}
    ) == "s133_platform_postgres_restart_closure=fail checks=1"

    monkeypatch.setattr(
        closure,
        "run_s133_platform_postgres_restart_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S134" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s133_platform_postgres_restart_closure",
        lambda: {"status": "FAIL", "failed_checks": []},
    )
    assert closure.main([]) == 1
