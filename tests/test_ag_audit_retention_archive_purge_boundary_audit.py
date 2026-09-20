from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_audit_retention_archive_purge_boundary_audit as audit


def test_boundary_audit_passes_for_repository() -> None:
    result = audit.run_ag_audit_retention_archive_purge_boundary_audit()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["decision"] == {
        "owner": "nex-ag",
        "source_tables": ["service_operational_events", "ag_ev_exports"],
        "source_rows_are_archive_payload": False,
        "metadata_only_manifest_allows_purge": False,
        "physical_purge_requires_sealed_archive_receipt": True,
        "archive_payload_authority": "external_injected_adapter",
        "archive_receipt_authority": "nex-ag",
        "proposed_receipt_table": "ag_ret_archives",
        "new_table_required": True,
        "direct_delete_api_must_not_be_operator_exposed": True,
        "dry_run_default": True,
        "explicit_execute_confirmation_required": True,
        "decision_status": "CONFIRMATION_REQUIRED",
    }
    assert len(result["current_risks"]) == 4
    assert result["deferred_scope"][-1] == (
        "ag_mvp_acceptance_and_cx_transition_s90"
    )
    assert all(item["within_limit"] for item in result["identifiers"])


def test_boundary_audit_reports_missing_paths_and_tokens(tmp_path: Path) -> None:
    quality_path = tmp_path / "scripts/quality/run_quality_gate.sh"
    quality_path.parent.mkdir(parents=True)
    quality_path.write_text(
        "run_ag_audit_retention_archive_purge_boundary_audit.py\n",
        encoding="utf-8",
    )

    result = audit.run_ag_audit_retention_archive_purge_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["required_paths_present"] is False
    assert result["checks"]["required_tokens_present"] is False
    assert any(item["category"] == "path_missing" for item in result["issues"])
    assert any(
        item["category"] == "source_token_missing" for item in result["issues"]
    )


def test_boundary_audit_reports_long_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "PROPOSED_RECEIPT_TABLE", "x" * 31)

    result = audit.run_ag_audit_retention_archive_purge_boundary_audit()

    assert result["status"] == "FAIL"
    assert result["checks"]["identifier_lengths_safe"] is False
    assert {"category": "identifier_too_long", "identifier": "x" * 31} in result[
        "issues"
    ]


def test_group_and_read_helpers_cover_present_and_missing(tmp_path: Path) -> None:
    present = tmp_path / "present.txt"
    present.write_text("content", encoding="utf-8")
    items = [
        {"group": "ready", "present": True},
        {"group": "blocked", "present": False},
    ]

    assert audit._read_text(present) == "content"
    assert audit._read_text(tmp_path / "missing.txt") == ""
    assert audit._group_present(items, "ready") is True
    assert audit._group_present(items, "blocked") is False
    assert audit._group_present(items, "missing") is False


def test_summary_line_reports_pass_and_failure() -> None:
    passed = audit.summary_line(
        {
            "status": "PASS",
            "decision": {
                "source_tables": ["one", "two"],
                "proposed_receipt_table": "ag_ret_archives",
                "decision_status": "CONFIRMATION_REQUIRED",
            },
        }
    )
    failed = audit.summary_line(
        {"status": "FAIL", "issues": [{"category": "missing"}]}
    )

    assert "boundary=pass" in passed
    assert "sources=2" in passed
    assert "receipt_table=ag_ret_archives" in passed
    assert "decision=CONFIRMATION_REQUIRED" in passed
    assert "boundary=fail" in failed
    assert "issues=1" in failed


def test_main_prints_summary_json_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passing = {
        "status": "PASS",
        "decision": {
            "source_tables": ["one", "two"],
            "proposed_receipt_table": "ag_ret_archives",
            "decision_status": "CONFIRMATION_REQUIRED",
        },
    }
    monkeypatch.setattr(
        audit,
        "run_ag_audit_retention_archive_purge_boundary_audit",
        lambda: passing,
    )

    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_ag_audit_retention_archive_purge_boundary_audit",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
