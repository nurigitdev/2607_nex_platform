from __future__ import annotations

import json
from pathlib import Path

import run_s118_mo_catalog_alias_lifecycle_closure as closure


def test_repository_s118_closure_passes() -> None:
    result = closure.run_s118_mo_catalog_alias_lifecycle_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S119"
    assert result["feature_readiness"] == (
        "MO_DURABLE_CATALOG_ALIAS_LIFECYCLE_READY"
    )
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 9,
        "component_count": 5,
        "closed_component_count": 5,
        "catalog_entry_count": 3,
        "active_binding_count": 3,
        "runtime_operation_count": 29,
        "postgres_check_count": 13,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S119"


def test_s118_closure_freezes_lifecycle_and_quality_decisions() -> None:
    decision = closure._closure_decision()

    assert decision["traceability"] == {
        "requirement_id": "MO-FR-001",
        "s111_baseline_status": "IMPLEMENTED_STATIC",
        "s118_current_status": "DURABLE_IMPLEMENTED",
    }
    assert decision["required_capabilities"] == (
        "embedding",
        "reranking",
        "generation",
    )
    assert decision["tables"] == ("mo_model_catalog", "mo_alias_bindings")
    assert decision["runtime_resolution"] == "active_durable_alias_fail_closed"
    assert decision["runtime_configuration"] == "external_not_persisted"
    assert decision["concurrency"] == "expected_revision_optimistic_guard"
    assert decision["rollback"] == "append_only_binding_lineage"
    assert decision["authenticated_operation_count"] == 7
    assert decision["postgres_smoke_required"] is True
    assert decision["dgx_provider_calls_required"] is False


def test_s118_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s118_mo_catalog_alias_lifecycle_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["summary"]["postgres_check_count"] == 0
    assert result["components"]["postgres_and_quality_evidence"] is False


def test_s118_closure_fails_when_deterministic_evidence_regresses(
    monkeypatch,
) -> None:
    monkeypatch.setattr(closure, "run_alias", lambda: {"status": "FAIL"})

    result = closure.run_s118_mo_catalog_alias_lifecycle_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["all_evidence_passed"] is False
    assert result["checks"]["atomic_activation_rollback_closed"] is False
    assert result["evidence_statuses"]["alias"] == "FAIL"


def test_s118_closure_helpers_fail_closed(tmp_path: Path) -> None:
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


def test_s118_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s118_mo_catalog_alias_lifecycle_closure()
    assert closure.summary_line(passing) == (
        "s118_mo_catalog_alias_lifecycle_closure=pass evidence=9/9 "
        "components=5/5 catalog=3/3 operations=29 postgres=13 next=S119"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s118_mo_catalog_alias_lifecycle_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        closure,
        "run_s118_mo_catalog_alias_lifecycle_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
