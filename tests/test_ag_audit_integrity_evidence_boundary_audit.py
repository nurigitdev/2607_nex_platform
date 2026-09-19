from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_audit_integrity_evidence_boundary_audit as audit


def test_boundary_audit_passes_for_repository() -> None:
    result = audit.run_ag_audit_integrity_evidence_boundary_audit()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["decision"]["new_table_required"] is False
    assert result["decision"]["new_migration_required"] is False
    assert result["decision"]["verification_mode"] == "read_only_deterministic"
    assert result["decision"]["manifest_hash_algorithm"] == (
        "sha256_canonical_json"
    )
    assert result["deferred_scope"] == [
        "external_notary_or_signature_service",
        "cross_database_distributed_transaction",
        "retention_archive_and_physical_purge_s89",
    ]
    assert all(item["within_limit"] for item in result["identifiers"])


def test_boundary_audit_reports_missing_paths_and_tokens(tmp_path: Path) -> None:
    quality_path = tmp_path / "scripts/quality/run_quality_gate.sh"
    quality_path.parent.mkdir(parents=True)
    quality_path.write_text(
        "run_ag_audit_integrity_evidence_boundary_audit.py\n",
        encoding="utf-8",
    )

    result = audit.run_ag_audit_integrity_evidence_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["required_paths_present"] is False
    assert result["checks"]["required_tokens_present"] is False
    assert any(item["category"] == "path_missing" for item in result["issues"])
    assert any(
        item["category"] == "source_token_missing" for item in result["issues"]
    )


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
                "new_table_required": False,
                "verification_mode": "read_only_deterministic",
            },
        }
    )
    failed = audit.summary_line(
        {"status": "FAIL", "issues": [{"category": "missing"}]}
    )

    assert "boundary=pass" in passed
    assert "new_table=False" in passed
    assert "boundary=fail" in failed
    assert "issues=1" in failed


def test_main_prints_summary_json_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit,
        "run_ag_audit_integrity_evidence_boundary_audit",
        lambda: {
            "status": "PASS",
            "decision": {
                "new_table_required": False,
                "verification_mode": "read_only_deterministic",
            },
        },
    )

    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_ag_audit_integrity_evidence_boundary_audit",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
