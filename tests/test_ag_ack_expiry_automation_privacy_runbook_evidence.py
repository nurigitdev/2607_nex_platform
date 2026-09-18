from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_ack_expiry_automation_privacy_runbook_evidence as evidence


def test_privacy_runbook_evidence_passes() -> None:
    result = evidence.run_ag_ack_expiry_automation_privacy_runbook_evidence()

    assert result["status"] == "PASS"
    assert result["runbook_schema_version"] == evidence.SCHEMA_VERSION
    assert result["surface_count"] == 8
    assert result["forbidden_value_labels"] == []
    assert result["forbidden_key_paths"] == []
    assert result["surfaces"]["disabled"]["plan_status"] == "DISABLED"
    assert result["surfaces"]["blocked"]["blocked_reason"] == (
        "confirm_tick_required"
    )
    assert result["surfaces"]["completed"]["applied_count"] == 1
    assert result["surfaces"]["conflict"]["conflict_count"] == 1
    assert all(result["checks"].values())
    assert "privacy_runbook=pass" in evidence.summary_line(result)


def test_privacy_runbook_reports_missing_doc_and_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_exists = Path.exists
    original_read_text = Path.read_text

    def fake_exists(path: Path) -> bool:
        if str(path).endswith("0828_ag_ack_expiry_automation_postgres_smoke.md"):
            return False
        return original_exists(path)

    def fake_read_text(path: Path, *args: object, **kwargs: object) -> str:
        content = original_read_text(path, *args, **kwargs)
        if str(path).endswith("run_quality_gate.sh"):
            return content.replace(evidence.EVIDENCE_HOOK, "missing-evidence-hook")
        return content

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "read_text", fake_read_text)

    result = evidence.run_ag_ack_expiry_automation_privacy_runbook_evidence()

    assert result["status"] == "FAIL"
    assert result["checks"]["docs_present"] is False
    assert result["checks"]["quality_gate_hook_present"] is False


def test_privacy_runbook_reports_missing_live_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read_text = Path.read_text

    def fake_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if str(path).endswith("0828_ag_ack_expiry_automation_postgres_smoke.md"):
            return "no live result"
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    result = evidence.run_ag_ack_expiry_automation_privacy_runbook_evidence()

    assert result["status"] == "FAIL"
    assert result["checks"]["postgres_live_evidence_present"] is False


def test_privacy_helpers_detect_forbidden_values_and_keys() -> None:
    payload = {
        "safe": [
            {
                "raw_comment": evidence.FORBIDDEN_VALUES["raw_comment"],
            }
        ]
    }
    serialized = str(payload)

    assert evidence._forbidden_key_paths(payload) == ["safe[0].raw_comment"]
    assert evidence._forbidden_key_paths("safe") == []
    assert evidence._forbidden_value_labels(serialized) == ["raw_comment"]
    with pytest.raises(ValueError, match="forbidden"):
        evidence._assert_no_forbidden_values(serialized)


def test_privacy_helper_surfaces_and_failure_guard() -> None:
    assert evidence._cli_surface({"plan": None}) == {
        "result_status": None,
        "action": None,
        "plan_status": None,
        "planned_candidate_count": None,
        "tick_status": None,
        "blocked_reason": None,
        "candidate_count": None,
        "applied_count": None,
        "conflict_count": None,
        "lifecycle_events": [],
        "database_bound": False,
    }
    assert evidence._event_surface([]) == {
        "event_count": 0,
        "event_types": [],
        "details": [],
    }

    monkey = evidence.execute_liveness_ack_expiry_automation_cli
    try:
        evidence.execute_liveness_ack_expiry_automation_cli = lambda *_a, **_k: {}
        with pytest.raises(AssertionError, match="did not fail"):
            evidence._capture_failure(object())
    finally:
        evidence.execute_liveness_ack_expiry_automation_cli = monkey


def test_privacy_runbook_main_and_failure_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        evidence,
        "run_ag_ack_expiry_automation_privacy_runbook_evidence",
        lambda: {"status": "PASS", "surface_count": 1, "checks": {}},
    )
    assert evidence.main(["--summary"]) == 0
    assert "privacy_runbook=pass" in capsys.readouterr().out
    assert evidence.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        evidence,
        "run_ag_ack_expiry_automation_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "failure_code": "test"},
    )
    assert evidence.main(["--summary"]) == 1
    assert "privacy_runbook=fail" in capsys.readouterr().out
