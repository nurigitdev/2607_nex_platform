from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path

import pytest

import run_s110_ae_mvp_acceptance_operations_closure as closure


NOW = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)


def _live() -> dict:
    timestamp = "2026-09-29T08:30:00Z"
    return {
        "status": "PASS",
        "acceptance_gate_evidence": {
            "postgres_smoke": {
                "status": "PASS",
                "observed_at": timestamp,
                "backend": "postgresql",
                "databases": ["nex_ae_test", "nex_cx_test"],
                "zero_residue": True,
            },
            "live_grounded_generation": {
                "status": "PASS",
                "observed_at": timestamp,
                "provider_models": {
                    "embedding": "Qwen3-Embedding-4B",
                    "reranking": "Qwen3-Reranker-4B",
                    "generation": "Qwen3.5-4B",
                },
                "failed_calls": 0,
                "browser_engine": "chromium",
                "display_state": "VERIFIED_RESPONSE",
                "server_secret_header": False,
            },
            "operations_handoff": {
                "status": "PASS",
                "observed_at": timestamp,
                "target_service": "nex-ag",
                "manifest_status": "SEALED",
            },
        },
    }


def _regression(**overrides) -> dict:
    return {
        "passed_tests": 9000,
        "failed_tests": 0,
        "statement_percent": 98.8,
        "branch_percent": 96.8,
        **overrides,
    }


def test_repository_closure_passes_with_final_evidence_pending() -> None:
    result = closure.run_s110_ae_mvp_acceptance_operations_closure(
        environ={}, now=NOW
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["closure_readiness"] == "REPOSITORY_READY_FINAL_EVIDENCE_PENDING"
    assert result["final_evidence"]["acceptance_status"] == "PENDING"
    assert result["summary"]["resolved_gap_count"] == 8
    assert result["summary"]["requirement_count"] == 9
    assert result["production_release_approved"] is False
    assert result["next_requirement"] == "S111"


def test_final_closure_accepts_nine_gates_and_binds_handoff() -> None:
    result = closure.run_s110_ae_mvp_acceptance_operations_closure(
        environ={closure.FINAL_ENV: "1"},
        live_evidence=_live(),
        regression_evidence=_regression(),
        now=NOW,
    )

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "AE_MVP_ACCEPTED_OPERATIONS_HANDOFF_BOUND"
    assert result["final_evidence"]["acceptance_status"] == "ACCEPTED"
    assert result["final_evidence"]["operations_status"] == "READY_FOR_OPERATIONS"
    assert result["final_evidence"]["passed_gate_count"] == 9
    assert result["final_evidence"]["attestation_status"] == "BOUND"
    assert result["final_evidence"]["attestation_verification"] == "VERIFIED"
    assert result["final_evidence"]["raw_evidence_exposed"] is False


@pytest.mark.parametrize(
    "regression",
    [
        _regression(passed_tests=8499),
        _regression(failed_tests=1),
        _regression(statement_percent=97.99),
        _regression(branch_percent=95.99),
    ],
)
def test_final_closure_blocks_invalid_regression(regression: dict) -> None:
    result = closure.run_s110_ae_mvp_acceptance_operations_closure(
        environ={closure.FINAL_ENV: "1"},
        live_evidence=_live(),
        regression_evidence=regression,
        now=NOW,
    )

    assert result["status"] == "FAIL"
    assert result["final_evidence"]["acceptance_status"] == "BLOCKED"
    assert result["final_evidence"]["attestation_status"] is None
    assert result["checks"]["final_evidence_policy_satisfied"] is False


def test_final_closure_fails_closed_when_evidence_paths_are_missing() -> None:
    result = closure.run_s110_ae_mvp_acceptance_operations_closure(
        environ={closure.FINAL_ENV: "1"}, now=NOW
    )

    assert result["status"] == "FAIL"
    assert result["final_evidence"]["failure_code"] == "final_evidence_invalid"
    assert result["final_evidence"]["error_type"] == "ValueError"


def test_json_and_regression_loaders_accept_fresh_files(tmp_path: Path) -> None:
    live_path = tmp_path / "live.json"
    coverage_path = tmp_path / "coverage.json"
    log_path = tmp_path / "pytest.log"
    live_path.write_text(json.dumps(_live()), encoding="utf-8")
    coverage_path.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_statements_covered": 98.8,
                    "percent_branches_covered": 96.8,
                }
            }
        ),
        encoding="utf-8",
    )
    log_path.write_text(
        "9000 passed, 5 skipped, 1 warning in 10.00s\n", encoding="utf-8"
    )

    assert closure._load_json_evidence(
        str(live_path), label="live", now=datetime.now(UTC)
    )["status"] == "PASS"
    assert closure._load_regression_evidence(
        str(coverage_path), str(log_path), now=datetime.now(UTC)
    ) == _regression()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "missing"),
        ("stale", "stale"),
        ("invalid_json_shape", "does not prove PASS"),
        ("invalid_coverage", "percentages"),
        ("failed_tests", "passing Full Gate"),
    ],
)
def test_evidence_loaders_fail_closed(tmp_path: Path, mutation: str, message: str) -> None:
    live = tmp_path / "live.json"
    coverage = tmp_path / "coverage.json"
    log = tmp_path / "pytest.log"
    live.write_text(json.dumps(_live()), encoding="utf-8")
    coverage.write_text(
        json.dumps(
            {"totals": {"percent_statements_covered": 98.8, "percent_branches_covered": 96.8}}
        ),
        encoding="utf-8",
    )
    log.write_text("9000 passed in 10.00s\n", encoding="utf-8")
    now = datetime.now(UTC)
    if mutation == "missing":
        live.unlink()
        with pytest.raises(ValueError, match=message):
            closure._load_json_evidence(str(live), label="live", now=now)
        return
    if mutation == "stale":
        old = (now - timedelta(hours=25)).timestamp()
        os.utime(live, (old, old))
        with pytest.raises(ValueError, match=message):
            closure._load_json_evidence(str(live), label="live", now=now)
        return
    if mutation == "invalid_json_shape":
        live.write_text(json.dumps({"status": "FAIL"}), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            closure._load_json_evidence(str(live), label="live", now=now)
        return
    if mutation == "invalid_coverage":
        coverage.write_text(
            json.dumps({"totals": {"percent_statements_covered": True, "percent_branches_covered": 96.8}}),
            encoding="utf-8",
        )
    else:
        log.write_text("8999 passed, 1 failed in 10.00s\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        closure._load_regression_evidence(str(coverage), str(log), now=now)


def test_missing_repository_fails_closed(tmp_path: Path) -> None:
    result = closure.run_s110_ae_mvp_acceptance_operations_closure(
        root=tmp_path, environ={}, now=NOW
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["required_files_present"] is False
    assert result["checks"]["required_tokens_present"] is False
    assert result["checks"]["operations_candidate_verified"] is False


def test_contract_and_safe_evidence_bound_exceptions(monkeypatch) -> None:
    monkeypatch.setattr(
        closure,
        "validate_contract_tree",
        lambda _path: (_ for _ in ()).throw(RuntimeError("private")),
    )
    assert closure._contract_evidence(closure.ROOT) == {
        "status": "FAIL",
        "error_type": "RuntimeError",
    }
    assert closure._safe_evidence(
        lambda: (_ for _ in ()).throw(RuntimeError("private")), "bounded"
    ) == {
        "status": "FAIL",
        "failure_code": "bounded",
        "error_type": "RuntimeError",
    }


def test_helpers_summary_and_main(monkeypatch, tmp_path, capsys) -> None:
    assert closure._read_text(tmp_path / "missing") == ""
    assert closure._mapping([]) == {}
    assert closure._valid_percent(100)
    assert not closure._valid_percent(True)
    assert not closure._valid_percent(101)
    with pytest.raises(ValueError, match="timezone-aware"):
        closure._normalize_now(datetime(2026, 9, 29, 9, 0))

    pending = closure.run_s110_ae_mvp_acceptance_operations_closure(
        environ={}, now=NOW
    )
    assert "acceptance=PENDING handoff=PENDING next=S111" in closure.summary_line(pending)
    monkeypatch.setattr(
        closure,
        "run_s110_ae_mvp_acceptance_operations_closure",
        lambda: pending,
    )
    output = tmp_path / "closure.json"
    assert closure.main(["--summary", "--output", str(output)]) == 0
    assert output.is_file()
    assert "closure=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s110_ae_mvp_acceptance_operations_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
