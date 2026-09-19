from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_recovery_notification_delivery_privacy_runbook_evidence as evidence


def test_delivery_privacy_runbook_evidence_passes() -> None:
    result = (
        evidence.run_ag_recovery_notification_delivery_privacy_runbook_evidence()
    )

    assert result["status"] == "PASS"
    assert result["runbook_schema_version"] == evidence.SCHEMA_VERSION
    assert result["surface_count"] == 9
    assert result["forbidden_value_labels"] == []
    assert result["forbidden_key_paths"] == []
    assert result["checks"]["created_response_redacted"] is True
    assert result["checks"]["replay_response_redacted"] is True
    assert result["checks"]["internal_idempotency_signature_preserved"] is True
    assert result["surfaces"]["confirmation_blocked"]["execution_status"] == (
        "BLOCKED"
    )
    assert result["surfaces"]["mock_executed"]["execution_status"] == (
        "COMPLETED"
    )
    assert result["surfaces"]["completed_noop"]["execution_status"] == "NOOP"
    assert all(result["checks"].values())
    assert "privacy_runbook=pass" in evidence.summary_line(result)


def test_delivery_privacy_reports_missing_doc_and_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_exists = Path.exists
    original_read_text = Path.read_text

    def fake_exists(path: Path) -> bool:
        if str(path).endswith(
            "0847_ag_recovery_notification_delivery_mock_execution.md"
        ):
            return False
        return original_exists(path)

    def fake_read_text(path: Path, *args: object, **kwargs: object) -> str:
        content = original_read_text(path, *args, **kwargs)
        if str(path).endswith("run_quality_gate.sh"):
            return content.replace(
                evidence.EVIDENCE_HOOK,
                "missing-delivery-evidence-hook",
            )
        return content

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "read_text", fake_read_text)

    result = (
        evidence.run_ag_recovery_notification_delivery_privacy_runbook_evidence()
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["docs_present"] is False
    assert result["checks"]["quality_gate_hook_present"] is False


def test_delivery_privacy_reports_missing_postgres_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read_text = Path.read_text

    def fake_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if str(path).endswith(
            "0848_ag_recovery_notification_delivery_postgres_smoke.md"
        ):
            return "no live result"
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    result = (
        evidence.run_ag_recovery_notification_delivery_privacy_runbook_evidence()
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["postgres_live_evidence_present"] is False


def test_delivery_privacy_helpers_detect_forbidden_values_and_keys() -> None:
    payload = {
        "safe": [
            {
                "request_signature": {
                    "provider_token": evidence.FORBIDDEN_VALUES[
                        "provider_token"
                    ]
                }
            }
        ]
    }
    serialized = str(payload)

    assert evidence._forbidden_key_paths(payload) == [
        "safe[0].request_signature",
        "safe[0].request_signature.provider_token",
    ]
    assert evidence._forbidden_key_paths("safe") == []
    assert evidence._forbidden_value_labels(serialized) == ["provider_token"]
    with pytest.raises(ValueError, match="forbidden"):
        evidence._assert_no_forbidden_values(serialized)


def test_delivery_privacy_safe_surface_helpers() -> None:
    assert evidence._mapping(None) == {}
    assert evidence._handoff_surface({}) == {
        "dispatch_handoff_schema_version": None,
        "handoff_status": None,
        "blocking_reasons": [],
        "guardrails": {},
    }
    assert set(evidence._runbook_actions()) == {
        "confirmation_required",
        "non_delivery_marker",
        "live_channel_blocked",
        "idempotency_conflict",
        "provider_retry_wait",
        "completed_noop",
        "source_unavailable",
        "postgres_failure_cleanup",
    }


def test_delivery_privacy_main_and_failure_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        evidence,
        "run_ag_recovery_notification_delivery_privacy_runbook_evidence",
        lambda: {"status": "PASS", "surface_count": 1, "checks": {}},
    )
    assert evidence.main(["--summary"]) == 0
    assert "privacy_runbook=pass" in capsys.readouterr().out
    assert evidence.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        evidence,
        "run_ag_recovery_notification_delivery_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "failure_code": "test"},
    )
    assert evidence.main(["--summary"]) == 1
    assert "privacy_runbook=fail" in capsys.readouterr().out
