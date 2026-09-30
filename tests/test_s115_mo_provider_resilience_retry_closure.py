from __future__ import annotations

import json
from pathlib import Path

import run_s115_mo_provider_resilience_retry_closure as closure


def test_repository_s115_closure_passes() -> None:
    result = closure.run_s115_mo_provider_resilience_retry_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S116"
    assert result["feature_readiness"] == "MO_PROVIDER_RETRY_HARDENED"
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 9,
        "component_count": 5,
        "closed_component_count": 5,
        "capability_count": 3,
        "loopback_http_request_count": 6,
        "contract_drift_count": 0,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S116"


def test_s115_closure_freezes_retry_and_deferral_decisions() -> None:
    decision = closure._closure_decision()

    assert decision["attempt_limits"] == {
        "embedding": 3,
        "reranking": 3,
        "generation": 2,
    }
    assert decision["generation_ambiguous_replay"] == "blocked"
    assert decision["telemetry_persistence"] == "process_local"
    assert decision["durable_telemetry_requirement"] == "S116"
    assert decision["gpu_observability_requirement"] == "S117"
    assert decision["new_table_added"] is False
    assert decision["database_smoke_required"] is False
    assert decision["external_dgx_call_required"] is False


def test_s115_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s115_mo_provider_resilience_retry_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["components"]["contract_and_quality_handoff"] is False


def test_s115_closure_fails_when_deterministic_evidence_regresses(
    monkeypatch,
) -> None:
    monkeypatch.setattr(closure, "run_loopback", lambda: {"status": "FAIL"})

    result = closure.run_s115_mo_provider_resilience_retry_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["all_deterministic_evidence_passed"] is False
    assert result["checks"]["real_http_retry_evidence_closed"] is False
    assert result["evidence_statuses"]["loopback_http"] == "FAIL"


def test_s115_closure_helpers_fail_closed(tmp_path: Path) -> None:
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


def test_s115_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s115_mo_provider_resilience_retry_closure()
    assert closure.summary_line(passing) == (
        "s115_mo_provider_resilience_retry_closure=pass evidence=9/9 "
        "components=5/5 http=6 drift=0 next=S116"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s115_mo_provider_resilience_retry_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s115_mo_provider_resilience_retry_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
