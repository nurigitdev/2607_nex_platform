from __future__ import annotations

import run_p8_demo_s10c_installed_result_closure as smoke


def test_protected_smoke_is_explicitly_opt_in() -> None:
    result = smoke.run_p8_demo_s10c_installed_result_closure({}, execute=False)

    assert result == {
        "schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"--execute and {smoke.SMOKE_ENV}=1 are required",
    }
    assert smoke.summary_line(result).endswith("checks=0/0")


def test_wrapper_requires_all_installed_closure_invariants(monkeypatch) -> None:
    inherited = {
        "status": "PASS",
        "actual_postgres": True,
        "signed_service_tokens": True,
        "projection": {
            "execution_state": "SUCCEEDED",
            "execution_phase": "FINALIZE",
            "agent_result_count": 1,
            "acknowledged_delivery_count": 1,
            "workspace_result_activity_count": 1,
            "voucher_count": 1,
            "voucher_line_count": 2,
            "business_operation_count": 1,
        },
        "resume_cycle": {
            "result_closure": {"finalized_count": 1, "published_count": 1}
        },
        "replay_cycle": {
            "execution_count": 0,
            "result_closure": {"candidate_count": 0},
        },
    }
    monkeypatch.setattr(
        smoke,
        "run_p8_demo_s10b_installed_runtime",
        lambda _environment, *, execute: inherited,
    )

    result = smoke.run_p8_demo_s10c_installed_result_closure(
        {smoke.SMOKE_ENV: "1"},
        execute=True,
    )

    assert result["status"] == "PASS"
    assert result["checks_passed"] == result["checks_total"] == 8
    assert result["migration_added"] is False
    assert result["evidence_hash"].startswith("sha256:")


def test_wrapper_fails_on_duplicate_voucher(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_p8_demo_s10b_installed_runtime",
        lambda _environment, *, execute: {
            "status": "PASS",
            "actual_postgres": True,
            "signed_service_tokens": True,
            "projection": {
                "execution_state": "SUCCEEDED",
                "execution_phase": "FINALIZE",
                "agent_result_count": 1,
                "acknowledged_delivery_count": 1,
                "workspace_result_activity_count": 1,
                "voucher_count": 2,
                "voucher_line_count": 4,
                "business_operation_count": 1,
            },
            "resume_cycle": {
                "result_closure": {"finalized_count": 1, "published_count": 1}
            },
            "replay_cycle": {
                "execution_count": 0,
                "result_closure": {"candidate_count": 0},
            },
        },
    )

    result = smoke.run_p8_demo_s10c_installed_result_closure(
        {smoke.SMOKE_ENV: "1"},
        execute=True,
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["voucher_committed_once"] is False
