from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_s92_cx_private_content_ownership_closure as closure


def test_repository_s92_closure_passes() -> None:
    result = closure.run_s92_cx_private_content_ownership_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S93"
    assert result["feature_readiness"] == (
        "CX_PRIVATE_CONTENT_AND_OWNERSHIP_HARDENED"
    )
    assert all(result["checks"].values())
    assert result["summary"] == {
        "evidence_count": 8,
        "passed_evidence_count": 8,
        "private_store_count": 2,
        "owner_guarded_module_count": 13,
        "owner_lineage_table_count": 4,
        "contract_drift_count": 0,
        "postgres_check_count": 17,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert all(result["postgres_evidence"].values())
    assert result["next_requirement"] == "S93"


def test_s92_closure_freezes_storage_and_owner_decisions() -> None:
    decision = closure._closure_decision()

    assert decision["owner_transport"] == [
        "X-NEX-Tenant-ID",
        "X-NEX-Subject-ID",
    ]
    assert decision["cross_owner_visibility"] == "not-found"
    assert decision["public_database_policy"] == (
        "metadata_and_owner_lineage_only"
    )
    assert decision["private_payload_storage"] == (
        "owner_scoped_replaceable_capability_ports"
    )
    assert decision["migration_strategy"] == (
        "versioned_sql_schema_migrations_runner"
    )
    assert decision["dgx_live_provider_required"] is False


def test_s92_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s92_cx_private_content_ownership_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["failed_checks"]


def test_s92_closure_fails_when_evidence_does_not_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        closure,
        "run_authorization",
        lambda _root: {"status": "FAIL", "summary": {}},
    )

    result = closure.run_s92_cx_private_content_ownership_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["all_deterministic_evidence_passed"] is False
    assert result["checks"]["central_authorization_closed"] is False


def test_s92_closure_helpers_fail_closed(tmp_path: Path) -> None:
    failed = closure._safe_evidence(
        lambda: (_ for _ in ()).throw(RuntimeError("private detail"))
    )
    assert failed == {
        "status": "FAIL",
        "failure_code": "evidence_builder_failed",
        "detail": "RuntimeError",
    }
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._read_text(tmp_path / "missing") == ""
    present = tmp_path / "present"
    present.write_text("ok", encoding="utf-8")
    assert closure._read_text(present) == "ok"
    assert closure._dgx_not_required("x", {"dgx_required": False}) is True
    assert closure._dgx_not_required("x", {}) is False
    assert closure._dgx_not_required("x", {"dgx_required": True}) is False


def test_s92_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s92_cx_private_content_ownership_closure()
    assert closure.summary_line(passing) == (
        "s92_cx_private_content_ownership_closure=pass evidence=8/8 "
        "owner_modules=13 postgres_checks=17 contract_drift=0 next=S93"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s92_cx_private_content_ownership_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s92_cx_private_content_ownership_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
