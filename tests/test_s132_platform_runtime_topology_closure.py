from __future__ import annotations

from pathlib import Path

import run_s132_platform_runtime_topology_closure as closure


def test_repository_closure_passes_and_hands_off_to_s133() -> None:
    result = closure.run_s132_platform_runtime_topology_closure()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 9,
        "check_count": 13,
        "passed_check_count": 13,
        "profile_count": 5,
        "endpoint_count": 6,
        "process_count": 13,
        "http_probe_count": 6,
    }
    assert result["decision"]["completion_signal_met"] is True
    assert result["decision"]["database_or_provider_mutation_performed"] is False
    assert result["decision"]["next_requirement"] == "S133"


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s132_platform_runtime_topology_closure(tmp_path)

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
    assert closure._read_text(tmp_path / "missing.md") == ""


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_evidence_count": 9,
            "evidence_count": 9,
            "passed_check_count": 13,
            "check_count": 13,
            "profile_count": 5,
            "process_count": 13,
            "http_probe_count": 6,
        },
        "decision": {"next_requirement": "S133"},
    }
    assert closure.summary_line(passing) == (
        "s132_platform_runtime_topology_closure=pass evidence=9/9 "
        "checks=13/13 profiles=5 processes=13 http=6 next=S133"
    )
    assert closure.summary_line(
        {"status": "FAIL", "failed_checks": ["a"]}
    ) == "s132_platform_runtime_topology_closure=fail checks=1"

    monkeypatch.setattr(
        closure,
        "run_s132_platform_runtime_topology_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S133" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s132_platform_runtime_topology_closure",
        lambda: {"status": "FAIL", "failed_checks": []},
    )
    assert closure.main([]) == 1
