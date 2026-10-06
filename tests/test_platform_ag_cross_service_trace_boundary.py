from __future__ import annotations

import json
from pathlib import Path

import run_platform_ag_cross_service_trace_boundary as boundary


def test_repository_boundary_freezes_s138_gaps() -> None:
    result = boundary.run_platform_ag_cross_service_trace_boundary()

    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["gap_states"] == {
        "redacted_trace_envelope_contract": "OPEN",
        "cx_admin_trace_projection": "OPEN",
        "ae_trace_projection": "OPEN",
        "oa_mo_trace_projection": "OPEN",
        "ag_service_api_timeline_aggregation": "OPEN",
        "ag_durable_audit_operations": "OPEN",
        "deterministic_trace_e2e": "OPEN",
        "protected_postgres_trace_e2e": "OPEN",
    }
    assert result["summary"] == {
        "required_path_count": 12,
        "evidence_token_count": 8,
        "integration_gap_count": 8,
        "open_gap_count": 8,
        "missing_path_count": 0,
        "missing_token_count": 0,
    }
    assert result["decision"] == {
        "new_table_required": False,
        "remote_model_provider_required": False,
        "protected_postgres_deferred_to_slice": "1380",
        "legacy_cross_service_database_reads_allowed": False,
        "next_slice": "1373",
    }


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = boundary.run_platform_ag_cross_service_trace_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["issues"]
    assert result["summary"]["missing_path_count"] == len(boundary.REQUIRED_PATHS)
    assert result["summary"]["missing_token_count"] == len(boundary.TOKENS)
    assert result["decision"]["next_slice"] == "blocked"


def test_text_helpers_and_summary_branches(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("one\n  two", encoding="utf-8")
    assert boundary._read_text(source) == "one\n  two"
    assert boundary._normalized_text(source) == "one two"
    assert boundary._read_text(tmp_path / "missing.md") == ""

    passing = boundary.run_platform_ag_cross_service_trace_boundary()
    assert boundary.summary_line(passing) == (
        "platform_ag_cross_service_trace_boundary=pass "
        "paths=12/12 tokens=8/8 gaps=8/8 next=1373"
    )
    assert boundary.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_ag_cross_service_trace_boundary=fail issues=1"
    )


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = boundary.run_platform_ag_cross_service_trace_boundary()
    monkeypatch.setattr(
        boundary,
        "run_platform_ag_cross_service_trace_boundary",
        lambda: passing,
    )
    assert boundary.main(["--summary"]) == 0
    assert "next=1373" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        boundary,
        "run_platform_ag_cross_service_trace_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1
