from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import run_s120_mo_mvp_acceptance_oa_transition_closure as closure


NOW = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)


def _live() -> dict:
    timestamp = "2026-10-01T12:30:00Z"
    return {
        "status": "PASS",
        "acceptance_gate_evidence": {
            "postgres_smoke": {
                "status": "PASS",
                "observed_at": timestamp,
                "backend": "postgresql",
                "database": "nex_mo_test",
                "zero_residue": True,
            },
            "live_provider_acceptance": {
                "status": "PASS",
                "observed_at": timestamp,
                "provider_models": {
                    "embedding": "Qwen3-Embedding-4B",
                    "reranking": "Qwen3-Reranker-4B",
                    "generation": "Qwen3.5-4B",
                },
                "ready_capabilities": 3,
                "failed_calls": 0,
                "explicit_bfloat16": True,
            },
            "oa_transition_handoff": {
                "status": "PASS",
                "observed_at": timestamp,
                "target_service": "nex-oa",
                "manifest_status": "SEALED",
            },
        },
    }


def _regression(**overrides) -> dict:
    return {
        "passed_tests": 9300,
        "failed_tests": 0,
        "statement_percent": 98.8,
        "branch_percent": 97.1,
        **overrides,
    }


def test_repository_closure_passes_with_final_evidence_pending() -> None:
    result = closure.run_s120_mo_mvp_acceptance_oa_transition_closure(
        environ={}, now=NOW
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["closure_readiness"] == (
        "REPOSITORY_READY_FINAL_EVIDENCE_PENDING"
    )
    assert result["final_evidence"]["acceptance_status"] == "PENDING"
    assert result["summary"]["resolved_gap_count"] == 8
    assert result["summary"]["requirement_count"] == 9
    assert result["summary"]["runbook_count"] == 7
    assert set(result["repository_evidence_statuses"].values()) == {"PASS"}
    assert result["next_requirement"] == "S121"
    assert result["next_requirement_scope"] == (
        "oa_current_state_reaudit_and_refactoring_checkpoint"
    )


def test_final_closure_accepts_nine_gates_and_binds_oa_handoff() -> None:
    result = closure.run_s120_mo_mvp_acceptance_oa_transition_closure(
        environ={closure.FINAL_ENV: "1"},
        live_evidence=_live(),
        regression_evidence=_regression(),
        now=NOW,
    )

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "MO_MVP_ACCEPTED_OA_HANDOFF_BOUND"
    final = result["final_evidence"]
    assert final["acceptance_status"] == "ACCEPTED"
    assert final["transition_status"] == "READY_FOR_OA"
    assert final["passed_gate_count"] == 9
    assert final["blocked_gate_count"] == 0
    assert final["attestation_status"] == "BOUND"
    assert final["attestation_verification"] == "VERIFIED"
    assert set(final["live_gate_statuses"].values()) == {"PASS"}
    assert final["raw_evidence_exposed"] is False


@pytest.mark.parametrize(
    "regression",
    [
        _regression(passed_tests=8999),
        _regression(failed_tests=1),
        _regression(statement_percent=97.99),
        _regression(branch_percent=95.99),
    ],
)
def test_final_closure_blocks_invalid_regression(regression: dict) -> None:
    result = closure.run_s120_mo_mvp_acceptance_oa_transition_closure(
        environ={closure.FINAL_ENV: "1"},
        live_evidence=_live(),
        regression_evidence=regression,
        now=NOW,
    )

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["checks"]["final_evidence_policy_satisfied"] is False
    assert result["final_evidence"]["acceptance_status"] == "BLOCKED"
    assert result["final_evidence"]["attestation_status"] is None


def test_final_closure_fails_closed_for_missing_or_invalid_live_evidence() -> None:
    missing = closure.run_s120_mo_mvp_acceptance_oa_transition_closure(
        environ={closure.FINAL_ENV: "1"}, now=NOW
    )
    invalid_live = _live()
    invalid_live["acceptance_gate_evidence"].pop("postgres_smoke")
    blocked = closure.run_s120_mo_mvp_acceptance_oa_transition_closure(
        environ={closure.FINAL_ENV: "1"},
        live_evidence=invalid_live,
        regression_evidence=_regression(),
        now=NOW,
    )

    assert missing["status"] == "FAIL"
    assert missing["final_evidence"]["failure_code"] == "final_evidence_invalid"
    assert blocked["status"] == "FAIL"
    assert blocked["final_evidence"]["acceptance_status"] == "BLOCKED"


def test_closure_fails_closed_when_repository_assets_are_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s120_mo_mvp_acceptance_oa_transition_closure(
        tmp_path, environ={}, now=NOW
    )

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["checks"]["oa_candidate_verified"] is False


def test_evidence_file_loaders_accept_fresh_full_gate_artifacts(
    tmp_path: Path,
) -> None:
    live_path = tmp_path / "live.json"
    coverage_path = tmp_path / "coverage.json"
    log_path = tmp_path / "full.log"
    live_path.write_text(json.dumps(_live()), encoding="utf-8")
    coverage_path.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_statements_covered": 98.8,
                    "percent_branches_covered": 97.1,
                }
            }
        ),
        encoding="utf-8",
    )
    log_path.write_text(
        "================ 9,301 passed, 6 skipped in 10.00s ================\n",
        encoding="utf-8",
    )
    timestamp = NOW.timestamp()
    for path in (live_path, coverage_path, log_path):
        os.utime(path, (timestamp, timestamp))

    assert closure._load_json_evidence(
        str(live_path), label="live", now=NOW
    )["status"] == "PASS"
    assert closure._load_regression_evidence(
        str(coverage_path), str(log_path), now=NOW
    ) == {
        "passed_tests": 9301,
        "failed_tests": 0,
        "statement_percent": 98.8,
        "branch_percent": 97.1,
    }


def test_evidence_file_loaders_reject_stale_invalid_or_failed_artifacts(
    tmp_path: Path,
) -> None:
    live_path = tmp_path / "live.json"
    coverage_path = tmp_path / "coverage.json"
    log_path = tmp_path / "full.log"
    live_path.write_text('{"status":"FAIL"}', encoding="utf-8")
    coverage_path.write_text(
        '{"totals":{"percent_statements_covered":101,'
        '"percent_branches_covered":97}}',
        encoding="utf-8",
    )
    log_path.write_text("1 failed, 9300 passed in 1.00s\n", encoding="utf-8")
    timestamp = NOW.timestamp()
    for path in (live_path, coverage_path, log_path):
        os.utime(path, (timestamp, timestamp))

    with pytest.raises(ValueError, match="does not prove PASS"):
        closure._load_json_evidence(str(live_path), label="live", now=NOW)
    with pytest.raises(ValueError, match="percentages"):
        closure._load_regression_evidence(
            str(coverage_path), str(log_path), now=NOW
        )

    live_path.write_text(json.dumps(_live()), encoding="utf-8")
    stale = (NOW - timedelta(hours=25)).timestamp()
    os.utime(live_path, (stale, stale))
    with pytest.raises(ValueError, match="stale"):
        closure._load_json_evidence(str(live_path), label="live", now=NOW)


def test_regression_loader_and_contract_evidence_fail_closed(
    monkeypatch, tmp_path: Path
) -> None:
    coverage_path = tmp_path / "coverage.json"
    log_path = tmp_path / "full.log"
    with pytest.raises(ValueError, match="missing"):
        closure._load_regression_evidence(
            str(coverage_path), str(log_path), now=NOW
        )

    coverage_path.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_statements_covered": 98.8,
                    "percent_branches_covered": 97.1,
                }
            }
        ),
        encoding="utf-8",
    )
    log_path.write_text("9300 passed in 1.00s\n", encoding="utf-8")
    stale = (NOW - timedelta(hours=25)).timestamp()
    os.utime(coverage_path, (stale, stale))
    os.utime(log_path, (stale, stale))
    with pytest.raises(ValueError, match="stale"):
        closure._load_regression_evidence(
            str(coverage_path), str(log_path), now=NOW
        )

    current = NOW.timestamp()
    os.utime(coverage_path, (current, current))
    os.utime(log_path, (current, current))
    log_path.write_text("9300 collected in 1.00s\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not prove"):
        closure._load_regression_evidence(
            str(coverage_path), str(log_path), now=NOW
        )

    log_path.write_text(
        "mo_provider_catalog=pass compatibility=1 failed=0\n"
        "================ 9300 passed in 1.00s ================\n",
        encoding="utf-8",
    )
    assert closure._load_regression_evidence(
        str(coverage_path), str(log_path), now=NOW
    )["passed_tests"] == 9300

    log_path.write_text(
        "================ 1 failed, 9299 passed in 1.00s ================\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not prove"):
        closure._load_regression_evidence(
            str(coverage_path), str(log_path), now=NOW
        )

    monkeypatch.setattr(
        closure,
        "validate_contract_tree",
        lambda _path: (_ for _ in ()).throw(RuntimeError("private")),
    )
    assert closure._contract_evidence(tmp_path) == {
        "status": "FAIL",
        "error_type": "RuntimeError",
    }
    monkeypatch.setattr(
        closure,
        "validate_contract_tree",
        lambda _path: SimpleNamespace(
            ok=False,
            schema_count=1,
            example_count=1,
            negative_example_count=1,
            openapi_count=1,
        ),
    )
    assert closure._contract_evidence(tmp_path)["status"] == "FAIL"


def test_helpers_summary_and_main_paths(monkeypatch, capsys, tmp_path: Path) -> None:
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping([]) == {}
    assert closure._read_text(tmp_path / "missing") == ""
    assert closure._valid_percent(100)
    assert not closure._valid_percent(True)
    assert not closure._valid_percent(101)
    with pytest.raises(ValueError, match="timezone-aware"):
        closure._normalize_now(datetime(2026, 10, 1, 13, 0))
    failed = closure._safe_evidence(
        lambda: (_ for _ in ()).throw(RuntimeError("private detail"))
    )
    assert failed["error_type"] == "RuntimeError"

    passing = closure.run_s120_mo_mvp_acceptance_oa_transition_closure(
        environ={}, now=NOW
    )
    assert closure.summary_line(passing).endswith(
        "acceptance=PENDING handoff=PENDING next=S121"
    )
    monkeypatch.setattr(
        closure,
        "run_s120_mo_mvp_acceptance_oa_transition_closure",
        lambda: passing,
    )
    output = tmp_path / "closure.json"
    assert closure.main(["--summary", "--output", str(output)]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    monkeypatch.setattr(
        closure,
        "run_s120_mo_mvp_acceptance_oa_transition_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
