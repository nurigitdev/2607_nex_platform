from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_recovery_notification_live_privacy_runbook_evidence as evidence


def test_privacy_runbook_evidence_passes_and_redacts_live_surfaces() -> None:
    result = evidence.run_ag_recovery_notification_live_privacy_runbook_evidence()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["forbidden_value_labels"] == []
    assert result["forbidden_key_paths"] == []
    assert result["surfaces"]["persisted_states"] == {
        "blocked": "PENDING",
        "retry": "RETRY_WAIT",
        "success": "SUCCEEDED",
    }
    assert result["surfaces"]["completed_noop"]["execution_status"] == "NOOP"


def test_privacy_runbook_fails_when_docs_or_quality_hook_are_missing(
    tmp_path: Path,
) -> None:
    quality = tmp_path / evidence.QUALITY_GATE_PATH
    quality.parent.mkdir(parents=True)
    quality.write_text("#!/bin/sh\n", encoding="utf-8")
    postgres = tmp_path / evidence.POSTGRES_EVIDENCE_PATH
    postgres.parent.mkdir(parents=True, exist_ok=True)
    postgres.write_text("no evidence\n", encoding="utf-8")

    result = evidence.run_ag_recovery_notification_live_privacy_runbook_evidence(
        tmp_path
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["docs_present"] is False
    assert result["checks"]["quality_gate_hook_present"] is False
    assert result["checks"]["postgres_loopback_evidence_present"] is False


def test_capture_error_covers_expected_and_unexpected_results() -> None:
    blocked = evidence._capture_error(
        lambda: evidence.build_recovery_notification_live_admission(
            evidence._base_delivery_admission("capture"),
            evidence._live_provider_config(),
        )
    )
    unexpected = evidence._capture_error(lambda: {"ok": True})

    assert blocked["status"] == "BLOCKED"
    assert blocked["retryable"] is False
    assert unexpected == {"status": "UNEXPECTED_SUCCESS"}


def test_forbidden_value_and_key_helpers_cover_nested_shapes() -> None:
    serialized = (
        f"x={evidence.FORBIDDEN_VALUES['endpoint_url']} "
        f"y={evidence.FORBIDDEN_VALUES['provider_token']}"
    )

    assert evidence._forbidden_value_labels(serialized) == [
        "endpoint_path",
        "endpoint_url",
        "provider_token",
    ]
    assert evidence._forbidden_key_paths(
        {
            "safe": [
                {"authorization": "redacted"},
                {"nested": {"endpoint_url": "redacted"}},
                "leaf",
            ]
        }
    ) == ["safe[0].authorization", "safe[1].nested.endpoint_url"]
    with pytest.raises(ValueError, match="forbidden values"):
        evidence._assert_no_forbidden_values(serialized)


def test_summary_line_and_mapping_helpers() -> None:
    passed = evidence.summary_line(
        {
            "status": "PASS",
            "surface_count": 8,
            "checks": {
                "forbidden_values_absent": True,
                "transport_injection_required": True,
                "runbook_complete": True,
            },
        }
    )
    failed = evidence.summary_line(
        {"status": "FAIL", "failure_code": "failed"}
    )

    assert "runbook=pass" in passed
    assert "privacy=True" in passed
    assert "runbook=fail" in failed
    assert evidence._mapping(None) == {}


def test_main_prints_summary_json_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passing = {
        "status": "PASS",
        "surface_count": 1,
        "checks": {
            "forbidden_values_absent": True,
            "transport_injection_required": True,
            "runbook_complete": True,
        },
    }
    monkeypatch.setattr(
        evidence,
        "run_ag_recovery_notification_live_privacy_runbook_evidence",
        lambda: passing,
    )

    assert evidence.main(["--summary"]) == 0
    assert "runbook=pass" in capsys.readouterr().out
    assert evidence.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        evidence,
        "run_ag_recovery_notification_live_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "failure_code": "test"},
    )
    assert evidence.main([]) == 1
