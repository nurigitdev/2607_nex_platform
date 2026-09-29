from __future__ import annotations

import json
from pathlib import Path

import run_s109_ae_web_grounded_generation_experience_closure as closure


def _live() -> dict:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "execution_state": "EXECUTED",
        "evidence_mode": "single_correlated_browser_request",
        "database_identity": {
            "ae": {"database": "nex_ae_test", "role": "nex_ae_user"},
            "cx": {"database": "nex_cx_test", "role": "nex_cx_user"},
        },
        "checks": {f"check_{index}": True for index in range(16)},
        "browser_observation": {"display_mode": "VERIFIED_RESPONSE"},
        "persistence_observation": {
            "ae_status": "COMPLETED",
            "retrieval_status": "READY",
            "generation_status": "COMPLETED",
            "job_status": "SUCCEEDED",
        },
        "provider_observation": {
            capability: {
                "model": model,
                "success_count": 1,
                "failure_count": 0,
            }
            for capability, model in closure.EXPECTED_MODELS.items()
        },
    }


def _contract() -> dict:
    return {
        "status": "PASS",
        "schema_count": 108,
        "example_count": 166,
        "negative_example_count": 129,
        "openapi_count": 7,
        "failure_count": 0,
    }


def test_repository_s109_closure_passes_with_actual_live_evidence() -> None:
    result = closure.run_s109_ae_web_grounded_generation_experience_closure(
        live_evidence=_live(),
        contract_evidence=_contract(),
    )

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S110"
    assert result["feature_readiness"] == "AE_WEB_GROUNDED_GENERATION_READY"
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert result["summary"] == {
        "component_count": 10,
        "closed_component_count": 10,
        "resolved_gap_count": 8,
        "contract_schema_count": 108,
        "contract_example_count": 166,
        "contract_negative_count": 129,
        "live_check_count": 16,
        "provider_capability_count": 3,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["live_executed"] is True
    assert result["next_requirement"] == "S110"


def test_closure_allows_unrequested_protected_live_smoke_to_skip(
    monkeypatch,
) -> None:
    monkeypatch.delenv(closure.LIVE_SMOKE_ENV, raising=False)
    monkeypatch.setattr(
        closure,
        "run_live",
        lambda: {"status": "SKIPPED", "checks": {}, "actual_postgres": False},
    )

    result = closure.run_s109_ae_web_grounded_generation_experience_closure(
        contract_evidence=_contract()
    )

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_WITH_PROTECTED_LIVE_PENDING"
    assert result["feature_readiness"] == "REPOSITORY_READY_PROTECTED_LIVE_PENDING"
    assert result["live_executed"] is False
    assert result["summary"]["live_check_count"] == 0


def test_closure_fails_when_requested_live_smoke_did_not_execute(monkeypatch) -> None:
    monkeypatch.setenv(closure.LIVE_SMOKE_ENV, "1")
    monkeypatch.setattr(
        closure,
        "run_live",
        lambda: {"status": "SKIPPED", "checks": {}, "actual_postgres": False},
    )

    result = closure.run_s109_ae_web_grounded_generation_experience_closure(
        contract_evidence=_contract()
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["protected_live_policy_satisfied"] is False
    assert result["closure_readiness"] == "BLOCKED"


def test_closure_rejects_incomplete_live_evidence() -> None:
    live = _live()
    live["provider_observation"]["generation"]["model"] = "unexpected"

    result = closure.run_s109_ae_web_grounded_generation_experience_closure(
        live_evidence=live,
        contract_evidence=_contract(),
    )

    assert result["status"] == "FAIL"
    assert result["live_executed"] is False
    assert result["checks"]["protected_live_policy_satisfied"] is False


def test_closure_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = closure.run_s109_ae_web_grounded_generation_experience_closure(
        tmp_path,
        live_evidence=_live(),
        contract_evidence=_contract(),
    )

    assert result["status"] == "FAIL"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert not any(result["components"].values())
    assert result["checks"]["boundary_audit_passed"] is False


def test_closure_fails_for_contract_validation_failure() -> None:
    result = closure.run_s109_ae_web_grounded_generation_experience_closure(
        live_evidence=_live(),
        contract_evidence={"status": "FAIL", "failure_count": 1},
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["contract_tree_valid"] is False
    assert result["contract_status"] == "FAIL"


def test_closure_decision_contract_evidence_and_helpers(tmp_path: Path) -> None:
    decision = closure._closure_decision()
    assert decision["feature_scope"] == "ae_web_grounded_generation_experience"
    assert decision["browser_network_policy"] == "same_origin_ae_api_only"
    assert decision["live_provider_capabilities"] == [
        "embedding",
        "generation",
        "reranking",
    ]
    assert decision["new_tables_added"] == []
    assert decision["next_requirement_scope"] == "S110_to_be_confirmed"

    contract = closure._contract_evidence(closure.ROOT)
    assert contract["status"] == "PASS"
    assert contract["schema_count"] >= 108
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


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s109_ae_web_grounded_generation_experience_closure(
        live_evidence=_live(),
        contract_evidence=_contract(),
    )
    assert closure.summary_line(passing) == (
        "s109_ae_web_grounded_generation_experience_closure=pass "
        "components=10/10 gaps=8/8 live=pass live_checks=16 next=S110"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s109_ae_web_grounded_generation_experience_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s109_ae_web_grounded_generation_experience_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
