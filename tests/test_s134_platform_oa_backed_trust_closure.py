from __future__ import annotations

from pathlib import Path

import run_s134_platform_oa_backed_trust_closure as closure


def test_repository_closure_passes_and_hands_off_to_s135() -> None:
    result = closure.run_s134_platform_oa_backed_trust_closure()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["evidence_statuses"] == {
        "boundary": "PASS",
        "trust": "PASS",
        "scope": "PASS",
        "restart": "PASS",
        "postgres": "SKIPPED",
        "operations": "PASS",
    }
    assert result["summary"] == {
        "evidence_count": 6,
        "passed_evidence_count": 5,
        "protected_skip_count": 1,
        "check_count": 15,
        "passed_check_count": 15,
        "service_count": 5,
        "trust_hop_count": 5,
        "denial_count": 4,
        "restart_generation_count": 2,
        "database_count": 5,
        "operations_check_count": 11,
    }
    assert result["decision"]["completion_signal_met"] is True
    assert result["decision"]["closure_database_or_provider_mutation_performed"] is False
    assert result["decision"]["next_requirement"] == "S135"


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s134_platform_oa_backed_trust_closure(tmp_path)

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
            "passed_evidence_count": 5,
            "protected_skip_count": 1,
            "evidence_count": 6,
            "passed_check_count": 15,
            "check_count": 15,
            "trust_hop_count": 5,
            "denial_count": 4,
        },
        "decision": {"next_requirement": "S135"},
    }
    assert closure.summary_line(passing) == (
        "s134_platform_oa_backed_trust_closure=pass evidence=5+1/6 "
        "checks=15/15 hops=5 denials=4 next=S135"
    )
    assert closure.summary_line(
        {"status": "FAIL", "failed_checks": ["a"]}
    ) == "s134_platform_oa_backed_trust_closure=fail checks=1"

    monkeypatch.setattr(
        closure,
        "run_s134_platform_oa_backed_trust_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S135" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s134_platform_oa_backed_trust_closure",
        lambda: {"status": "FAIL", "failed_checks": []},
    )
    assert closure.main([]) == 1
