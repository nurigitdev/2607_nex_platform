from __future__ import annotations

import json
from pathlib import Path

import run_ae_durable_workspace_chat_boundary_audit as audit


def test_repository_boundary_audit_passes() -> None:
    result = audit.run_ae_durable_workspace_chat_boundary_audit()

    assert result["status"] == "PASS"
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["summary"]["foundation_count"] == 7
    assert result["summary"]["gap_count"] == 8
    assert result["summary"]["open_gap_count"] == 0
    assert result["summary"]["resolved_gap_count"] == 8
    assert result["summary"]["planned_slice_count"] == 10
    assert result["issues"] == []
    assert result["next_slice"] == "1021"


def test_boundary_freezes_storage_ownership_and_quality_policy() -> None:
    decision = audit.boundary_decision()

    assert decision["workspace_tables"] == [
        "ae_workspaces",
        "ae_workspace_activities",
    ]
    assert decision["chat_table"] == "ae_chat_interactions"
    assert decision["chat_workspace_link"] == (
        "nullable_for_legacy_service_compatibility"
    )
    assert decision["browser_owner_authority"] == "validated_oa_claim"
    assert decision["cross_owner_behavior"] == "not_found"
    assert decision["private_message_body_persisted"] is False
    assert decision["new_tables_expected"] == 2
    assert decision["remote_provider_required"] is False
    assert decision["quality_cadence"]["checkpoint_gate"] == "1016"


def test_boundary_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = audit.run_ae_durable_workspace_chat_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert not result["checks"]["required_paths_present"]
    assert not result["checks"]["required_tokens_present"]
    assert result["summary"]["issue_count"] == (
        len(audit.REQUIRED_PATHS) + len(audit.EVIDENCE_TOKENS)
    )


def test_gap_progression_and_helpers(tmp_path: Path) -> None:
    for path in audit.REQUIRED_PATHS:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    for item in audit.EVIDENCE_TOKENS:
        target = tmp_path / item.relative_path
        target.write_text(
            target.read_text(encoding="utf-8") + item.token,
            encoding="utf-8",
        )
    first_gap = next(iter(audit.GAP_RESOLUTION_PATHS.values()))
    target = tmp_path / first_gap
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("ready", encoding="utf-8")

    result = audit.run_ae_durable_workspace_chat_boundary_audit(tmp_path)

    assert result["status"] == "PASS"
    assert result["summary"]["resolved_gap_count"] == 1
    assert result["summary"]["open_gap_count"] == 7
    assert result["next_slice"] == "1014"
    assert audit._read_text(tmp_path / "missing") == ""
    assert audit._group_present(result["required_tokens"], "s101_handoff") is True
    assert audit._group_present(result["required_tokens"], "missing") is False


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    result = audit.run_ae_durable_workspace_chat_boundary_audit()
    assert "boundary=pass" in audit.summary_line(result)
    assert "gaps=8" in audit.summary_line(result)
    assert "boundary=fail" in audit.summary_line({"status": "FAIL", "issues": [{}]})

    monkeypatch.setattr(
        audit,
        "run_ae_durable_workspace_chat_boundary_audit",
        lambda: result,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_ae_durable_workspace_chat_boundary_audit",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
