from __future__ import annotations

import json
from pathlib import Path

import run_cx_private_content_ownership_boundary_audit as audit


def test_repository_boundary_audit_freezes_s92_scope() -> None:
    result = audit.run_cx_private_content_ownership_boundary_audit()

    assert result["status"] == "PASS"
    assert result["boundary_readiness"] == "GAPS_CONFIRMED"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "volatile_private_payload_count": 5,
        "adapter_required_payload_count": 4,
        "owner_lineage_target_count": 4,
        "planned_slice_count": 10,
        "issue_count": 0,
    }
    assert result["decision"]["public_postgres_policy"] == (
        "metadata_hash_uri_dimension_only"
    )
    assert result["decision"]["dgx_live_provider_required"] is False
    assert result["next_slice"] == "0912"


def test_boundary_audit_fails_closed_without_repository_inputs(tmp_path: Path) -> None:
    result = audit.run_cx_private_content_ownership_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["checks"]["required_paths_present"] is False
    assert result["checks"]["required_tokens_present"] is False
    assert result["summary"]["issue_count"] == (
        len(audit.REQUIRED_PATHS) + len(audit.EVIDENCE_TOKENS)
    )


def test_group_and_text_helpers_cover_present_and_missing(tmp_path: Path) -> None:
    items = [{"group": "a", "present": True}, {"group": "b", "present": False}]
    assert audit._group_present(items, "a") is True
    assert audit._group_present(items, "b") is False
    assert audit._group_present(items, "missing") is False
    assert audit._read_text(tmp_path / "missing") == ""
    path = tmp_path / "present"
    path.write_text("value", encoding="utf-8")
    assert audit._read_text(path) == "value"


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = audit.run_cx_private_content_ownership_boundary_audit()
    assert audit.summary_line(passing) == (
        "cx_private_content_ownership_boundary=pass private_payloads=5 "
        "owner_targets=4 dgx_required=False issues=0"
    )
    assert "private_payloads=0" in audit.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        audit,
        "run_cx_private_content_ownership_boundary_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_cx_private_content_ownership_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
