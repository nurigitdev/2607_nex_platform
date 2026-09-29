from __future__ import annotations

import json
from pathlib import Path

import run_s112_mo_provider_runtime_operations_closure as closure


def test_repository_s112_closure_passes() -> None:
    result = closure.run_s112_mo_provider_runtime_operations_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_PROVIDER_AWARE_READINESS"
    assert result["feature_readiness"] == (
        "RUNTIME_HARDENING_COMPLETE_OPERATIONS_FEATURES_DEFERRED"
    )
    assert all(result["checks"].values())
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 9,
        "runtime_boundary_count": 5,
        "hardened_module_count": 8,
        "compatibility_export_count": 5,
        "live_evidence_count": 5,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["persistence_decision"] == {
        "decision": "HYBRID_PERSISTENCE_BOUNDARY",
        "table_created": False,
        "next_durable_slice": "S116",
    }
    assert result["next_requirement"] == "S113"


def test_s113_handoff_keeps_remaining_operations_work_ordered() -> None:
    handoff = closure._s113_handoff()

    assert handoff["target_requirement"] == "S113"
    assert [item["requirement"] for item in handoff["ordered_work"]] == [
        "S113",
        "S114",
        "S115",
        "S116",
        "S117",
        "S118",
    ]
    assert "keep high-frequency metrics outside PostgreSQL" in handoff["guardrails"]


def test_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s112_mo_provider_runtime_operations_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["failed_checks"]


def test_closure_fails_when_slice_evidence_does_not_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        closure,
        "run_telemetry",
        lambda _root: {"status": "FAIL"},
    )

    result = closure.run_s112_mo_provider_runtime_operations_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["all_slice_evidence_passed"] is False
    assert result["evidence_statuses"]["telemetry"] == "FAIL"


def test_closure_helpers_fail_closed_without_private_details(tmp_path: Path) -> None:
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


def test_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s112_mo_provider_runtime_operations_closure()
    assert closure.summary_line(passing) == (
        "s112_mo_provider_runtime_operations_closure=pass evidence=9/9 "
        "boundaries=5 modules=8 live=5/5 next=S113"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s112_mo_provider_runtime_operations_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s112_mo_provider_runtime_operations_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
