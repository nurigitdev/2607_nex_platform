from __future__ import annotations

import json

import pytest

import run_s130_oa_mvp_platform_trust_closure as closure


def _integrated() -> dict[str, object]:
    return {
        "status": "PASS",
        "summary": {
            "artifact_count": 7,
            "passed_artifact_count": 7,
            "actual_postgres_smoke_count": 4,
            "passed_gate_count": 7,
            "gate_count": 8,
            "cleanup_residue_count": 0,
        },
    }


def test_closure_accepts_exact_full_gate_context(monkeypatch) -> None:
    monkeypatch.setattr(
        closure.acceptance,
        "run_s130_oa_mvp_platform_trust_acceptance",
        lambda env: _integrated(),
    )

    result = closure.run_s130_oa_mvp_platform_trust_closure(
        environ={closure.FULL_GATE_ENV: "1"}
    )

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["gate_evaluation"]["status"] == "ACCEPTED"
    assert result["summary"]["passed_gate_count"] == 8
    assert result["summary"]["cleanup_residue_count"] == 0
    assert result["production_activation"] == "DEPLOYMENT_CONTROLS_REQUIRED"
    assert result["next_requirement"] == "S131"


def test_closure_is_protected_by_full_gate_context() -> None:
    result = closure.run_s130_oa_mvp_platform_trust_closure(environ={})

    assert result["status"] == "SKIPPED"
    assert closure.FULL_GATE_ENV in result["skip_reason"]


def test_closure_fails_closed_when_integrated_acceptance_fails(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        closure.acceptance,
        "run_s130_oa_mvp_platform_trust_acceptance",
        lambda env: {"status": "FAIL"},
    )

    result = closure.run_s130_oa_mvp_platform_trust_closure(
        environ={closure.FULL_GATE_ENV: "1"}
    )

    assert result["status"] == "FAIL"
    assert "integrated_acceptance_passed" in result["failed_checks"]
    assert result["next_requirement"] == "blocked"


def test_safe_acceptance_redacts_exception(monkeypatch) -> None:
    monkeypatch.setattr(
        closure.acceptance,
        "run_s130_oa_mvp_platform_trust_acceptance",
        lambda env: (_ for _ in ()).throw(RuntimeError("secret")),
    )

    result = closure._safe_acceptance({})

    assert result == {
        "status": "ERROR",
        "failure_code": "integrated_acceptance_execution_failed",
        "detail": "RuntimeError",
    }


def test_text_and_command_helpers_fail_closed(tmp_path) -> None:
    assert closure._last_command("") == ""
    assert closure._last_command("\n first \n second \n") == "second"
    assert closure._read_text(tmp_path / "missing") == ""
    assert closure._mapping(None) == {}


def test_summary_and_main(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_check_count": 9,
            "check_count": 9,
            "passed_gate_count": 8,
            "gate_count": 8,
            "actual_postgres_smoke_count": 4,
            "cleanup_residue_count": 0,
        },
        "production_activation": "DEPLOYMENT_CONTROLS_REQUIRED",
        "next_requirement": "S131",
    }
    assert closure.summary_line(passing) == (
        "s130_oa_mvp_trust_closure=pass checks=9/9 gates=8/8 "
        "postgres=4 residue=0 activation=DEPLOYMENT_CONTROLS_REQUIRED next=S131"
    )
    assert "skip" in closure.summary_line({"status": "SKIPPED"})
    assert "code=failed" in closure.summary_line(
        {"status": "FAIL", "failure_code": "failed"}
    )

    monkeypatch.setattr(
        closure,
        "run_s130_oa_mvp_platform_trust_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S131" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        closure,
        "run_s130_oa_mvp_platform_trust_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1


@pytest.mark.skipif(
    closure.os.getenv(closure.FULL_GATE_ENV) != "1",
    reason=f"{closure.FULL_GATE_ENV}=1 is required",
)
def test_actual_full_gate_closure() -> None:
    result = closure.run_s130_oa_mvp_platform_trust_closure()

    assert result["status"] == "PASS", result
    assert result["summary"]["passed_gate_count"] == 8
    assert result["summary"]["actual_postgres_smoke_count"] == 4
    assert result["summary"]["cleanup_residue_count"] == 0
