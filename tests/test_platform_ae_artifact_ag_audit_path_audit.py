from __future__ import annotations

from pathlib import Path

import run_platform_ae_artifact_ag_audit_path_audit as audit


def test_repository_artifact_audit_path_passes_and_exposes_owner_mismatch() -> None:
    result = audit.run_platform_ae_artifact_ag_audit_path_audit()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["findings"] == {
        "ae_lineage_field_count": 3,
        "ag_generation_source_operation_count": 4,
        "ag_artifact_http_client_present": True,
        "cx_generation_reads_require_owner_context": True,
        "ag_generation_client_sends_owner_context": False,
        "ag_generation_client_is_cx_owner_compatible": False,
        "dedicated_cx_admin_audit_projection_present": False,
        "ag_cross_service_database_fallback_count": 4,
    }
    assert result["decision"]["dedicated_admin_projection_is_recommended"] is True
    assert result["decision"]["ag_should_assert_unknown_user_owner_context"] is False
    assert result["decision"]["next_slice"] == "1309"


def test_audit_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = audit.run_platform_ae_artifact_ag_audit_path_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert len(result["issues"]) == len(result["checks"])
    assert result["findings"]["ag_generation_client_is_cx_owner_compatible"] is True


def test_read_text_and_summary_branches(tmp_path: Path) -> None:
    path = tmp_path / "source.py"
    path.write_text("source", encoding="utf-8")
    assert audit._read_text(path) == "source"
    assert audit._read_text(tmp_path / "missing.py") == ""

    passing = {
        "status": "PASS",
        "findings": {
            "ag_generation_source_operation_count": 4,
            "cx_generation_reads_require_owner_context": True,
            "ag_generation_client_sends_owner_context": False,
            "ag_generation_client_is_cx_owner_compatible": False,
        },
        "decision": {"next_slice": "1309"},
    }
    assert audit.summary_line(passing) == (
        "platform_ae_artifact_ag_audit_path=pass ag_ops=4 "
        "owner_required=True owner_sent=False owner_compatible=False next=1309"
    )
    assert audit.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_ae_artifact_ag_audit_path=fail issues=1"
    )


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "findings": {},
        "decision": {"next_slice": "1309"},
    }
    monkeypatch.setattr(
        audit,
        "run_platform_ae_artifact_ag_audit_path_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "audit_path=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        audit,
        "run_platform_ae_artifact_ag_audit_path_audit",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
