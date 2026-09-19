from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_audit_evidence_privacy_runbook_evidence as evidence


def test_privacy_runbook_passes_and_exercises_tamper_surfaces() -> None:
    result = evidence.run_ag_audit_evidence_privacy_runbook_evidence()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["surface_count"] == 12
    assert result["forbidden_value_labels"] == []
    assert result["forbidden_key_paths"] == []
    assert result["surfaces"]["hash_mismatch"]["integrity_status"] == "FAILED"
    assert result["surfaces"]["orphaned_export"]["continuity_status"] == "FAILED"
    assert result["surfaces"]["manifest_tamper"]["package_id"] is None
    assert result["surfaces"]["untrusted_package"]["package_id"] is None


def test_privacy_runbook_fails_when_docs_and_quality_hook_are_missing(
    tmp_path: Path,
) -> None:
    result = evidence.run_ag_audit_evidence_privacy_runbook_evidence(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "ag_audit_evidence_privacy_runbook_failed"
    assert result["checks"]["docs_present"] is False
    assert result["checks"]["quality_gate_hook_present"] is False
    assert result["checks"]["postgres_evidence_present"] is False


def test_forbidden_value_and_key_helpers_cover_nested_shapes() -> None:
    serialized = (
        f"x={evidence.FORBIDDEN_VALUES['database_url']} "
        f"y={evidence.FORBIDDEN_VALUES['raw_export_body']}"
    )

    assert evidence._forbidden_value_labels(serialized) == [
        "database_password",
        "database_url",
        "raw_export_body",
    ]
    assert evidence._forbidden_key_paths(
        {
            "safe": [
                {"authorization": "redacted"},
                {"nested": {"evidence_manifest": "redacted"}},
                "leaf",
            ]
        }
    ) == ["safe[0].authorization", "safe[1].nested.evidence_manifest"]
    with pytest.raises(ValueError, match="forbidden values"):
        evidence._assert_no_forbidden_values(serialized)


def test_source_helpers_keep_secrets_internal_to_raw_inputs() -> None:
    event = evidence._source_event()
    export = evidence._source_export()

    assert event["message"] == evidence.FORBIDDEN_VALUES["raw_event_message"]
    assert event["details"]["credential"] == "<redacted>"
    assert evidence.FORBIDDEN_VALUES["raw_event_credential"] not in str(event)
    assert export["evidence_manifest"]["raw_body"] == evidence.FORBIDDEN_VALUES[
        "raw_export_body"
    ]
    assert len(export["evidence_hash"]) == 64
    assert evidence._has_issue({"issues": []}, "missing") is False


def test_runbook_and_mapping_helpers_are_complete() -> None:
    runbook = evidence._runbook_actions()

    assert len(runbook) == 9
    assert runbook["manifest_tamper"]["retryable"] is False
    assert runbook["source_unavailable"]["retryable"] is True
    assert evidence._mapping({"ok": True}) == {"ok": True}
    assert evidence._mapping(None) == {}


def test_summary_line_reports_pass_and_failure() -> None:
    passed = evidence.summary_line(
        {
            "status": "PASS",
            "surface_count": 12,
            "checks": {
                "forbidden_values_absent": True,
                "manifest_tamper_rejected": True,
                "runbook_complete": True,
            },
        }
    )
    failed = evidence.summary_line(
        {"status": "FAIL", "failure_code": "failed"}
    )

    assert "runbook=pass" in passed
    assert "privacy=True" in passed
    assert "tamper=True" in passed
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
            "manifest_tamper_rejected": True,
            "runbook_complete": True,
        },
    }
    monkeypatch.setattr(
        evidence,
        "run_ag_audit_evidence_privacy_runbook_evidence",
        lambda: passing,
    )

    assert evidence.main(["--summary"]) == 0
    assert "runbook=pass" in capsys.readouterr().out
    assert evidence.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        evidence,
        "run_ag_audit_evidence_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "failure_code": "test"},
    )
    assert evidence.main([]) == 1
