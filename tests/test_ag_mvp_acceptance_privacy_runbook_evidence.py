from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ag_mvp_acceptance_privacy_runbook_evidence as evidence


def test_privacy_runbook_passes_all_acceptance_failure_surfaces() -> None:
    result = evidence.run_ag_mvp_acceptance_privacy_runbook_evidence()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["surface_count"] == 8
    assert result["forbidden_value_labels"] == []
    assert result["forbidden_key_paths"] == []
    surfaces = result["surfaces"]
    assert surfaces["accepted_report"]["status"] == "ACCEPTED"
    assert surfaces["candidate_verification"]["status"] == "VERIFIED"
    assert surfaces["attestation_verification"]["status"] == "VERIFIED"
    assert surfaces["tampered_candidate"]["status"] == "INVALID"
    assert surfaces["tampered_attestation"]["status"] == "INVALID"
    assert len(surfaces["failure_matrix"]) == 11


def test_privacy_runbook_fails_without_docs_postgres_evidence_and_hook(
    tmp_path: Path,
) -> None:
    result = evidence.run_ag_mvp_acceptance_privacy_runbook_evidence(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "ag_mvp_acceptance_privacy_runbook_failed"
    assert result["checks"]["docs_present"] is False
    assert result["checks"]["quality_gate_hook_present"] is False
    assert result["checks"]["postgres_evidence_complete"] is False


def test_acceptance_evidence_and_failure_matrix_are_fail_closed() -> None:
    baseline = evidence._acceptance_evidence()
    policy = evidence.build_ag_mvp_acceptance_policy({})
    failures = evidence._failure_matrix(baseline, policy=policy)

    assert len(baseline) == 8
    assert set(failures) == {
        "evidence_missing",
        "evidence_skipped",
        "evidence_stale",
        "evidence_from_future",
        "regression_failure",
        "statement_coverage_low",
        "branch_coverage_low",
        "wrong_database",
        "cleanup_unproven",
        "runbook_incomplete",
        "handoff_invalid",
    }
    assert all(item["status"] == "BLOCKED" for item in failures.values())
    assert failures["evidence_missing"]["blockers"][0]["gate_id"] == (
        "contract_validation"
    )
    assert failures["wrong_database"]["blockers"][0]["reason_codes"] == [
        "test_database_not_proven"
    ]
    assert failures["cleanup_unproven"]["blockers"][0]["reason_codes"] == [
        "postgres_cleanup_not_proven"
    ]


def test_changed_and_report_projection_do_not_mutate_baseline() -> None:
    baseline = evidence._acceptance_evidence()
    changed = evidence._changed(
        baseline,
        "postgres_smoke",
        database="nex_ag_dev",
    )
    projection = evidence._report_projection(
        {
            "status": "BLOCKED",
            "transition_status": "BLOCKED",
            "acceptance_id": "a" * 64,
            "blockers": [{"gate_id": "postgres_smoke"}],
            "raw_evidence_included": False,
        }
    )
    empty = evidence._report_projection({})

    assert baseline["postgres_smoke"]["database"] == "nex_ag_test"
    assert changed["postgres_smoke"]["database"] == "nex_ag_dev"
    assert projection["blockers"] == [{"gate_id": "postgres_smoke"}]
    assert empty["blockers"] == []


def test_postgres_evidence_and_runbook_actions_are_complete() -> None:
    complete = " ".join(
        (
            "live smoke: PASS",
            "database=nex_ag_test",
            "acceptance=ACCEPTED",
            "handoff=BOUND",
            "remaining=0 probe_residue=0",
            "latest_migration=1",
            "aggregate regression: 6256 passed",
            "statement=75383/76264 branch=17634/18284",
        )
    )

    assert all(evidence._postgres_evidence(complete).values())
    assert not any(evidence._postgres_evidence("").values())
    runbook = evidence._runbook_actions()
    assert len(runbook) == 10
    assert runbook["evidence_missing_or_skipped"]["retryable"] is True
    assert runbook["handoff_attestation_invalid"]["retryable"] is False


def test_privacy_helpers_detect_nested_keys_values_and_missing_files(
    tmp_path: Path,
) -> None:
    serialized = (
        f"url={evidence.FORBIDDEN_VALUES['database_url']} "
        f"prompt={evidence.FORBIDDEN_VALUES['raw_prompt']}"
    )

    assert evidence._forbidden_value_labels(serialized) == [
        "database_url",
        "raw_prompt",
    ]
    assert evidence._forbidden_key_paths(
        {
            "safe": [
                {"authorization": "redacted"},
                {"nested": {"raw_payload": "redacted"}},
                "leaf",
            ]
        }
    ) == ["safe[0].authorization", "safe[1].nested.raw_payload"]
    with pytest.raises(ValueError, match="forbidden values"):
        evidence._assert_no_forbidden_values(serialized)
    assert evidence._read_text(tmp_path / "missing") == ""
    assert evidence._mapping({"ok": True}) == {"ok": True}
    assert evidence._mapping(None) == {}


def test_summary_line_reports_pass_and_failure() -> None:
    passed = evidence.summary_line(
        {
            "status": "PASS",
            "surface_count": 8,
            "checks": {
                "forbidden_values_absent": True,
                "postgres_evidence_complete": True,
                "runbook_complete": True,
            },
        }
    )
    failed = evidence.summary_line(
        {"status": "FAIL", "failure_code": "failed"}
    )

    assert "runbook=pass" in passed
    assert "privacy=True" in passed
    assert "postgres=True" in passed
    assert "runbook=fail" in failed


def test_main_prints_summary_json_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passing = {
        "status": "PASS",
        "surface_count": 1,
        "checks": {
            "forbidden_values_absent": True,
            "postgres_evidence_complete": True,
            "runbook_complete": True,
        },
    }
    monkeypatch.setattr(
        evidence,
        "run_ag_mvp_acceptance_privacy_runbook_evidence",
        lambda: passing,
    )

    assert evidence.main(["--summary"]) == 0
    assert "runbook=pass" in capsys.readouterr().out
    assert evidence.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        evidence,
        "run_ag_mvp_acceptance_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "failure_code": "test"},
    )
    assert evidence.main([]) == 1


def test_runbook_is_wired_to_quality_gate_and_slice_docs() -> None:
    quality = (evidence.ROOT / "scripts/quality/run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (evidence.ROOT / "docs/README.md").read_text(encoding="utf-8")
    service_readme = (evidence.ROOT / "services/nex-ag/README.md").read_text(
        encoding="utf-8"
    )
    slice_doc = evidence.ROOT / "docs/slices/0899_ag_mvp_acceptance_privacy_runbook.md"

    assert evidence.EVIDENCE_HOOK in quality
    assert "0899_ag_mvp_acceptance_privacy_runbook.md" in docs_index
    assert "Slice 0899" in service_readme
    assert slice_doc.is_file()
