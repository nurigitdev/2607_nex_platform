from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence as evidence


def test_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence_passes() -> None:
    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence()
    )
    surfaces = result["surfaces"]

    assert result["status"] == "PASS"
    assert result["runbook_schema_version"] == evidence.SCHEMA_VERSION
    assert result["slice"] == "0809"
    assert result["surface_count"] == 7
    assert result["forbidden_value_labels"] == []
    assert result["forbidden_key_paths"] == []
    assert surfaces["liveness_summary"]["liveness_status"] == "STALE"
    assert surfaces["suppress_mutation"]["target_state_status"] == "SUPPRESSED"
    assert surfaces["clear_mutation"]["target_state_status"] == "CLEARED"
    assert surfaces["list_response"]["source_table"] == "ag_op_review_ack_state"
    assert surfaces["recovery_overlay"]["overlay_status"] == "STATE_PRESENT"
    assert surfaces["migration"]["source_table"] == "ag_op_review_ack_state"
    assert result["checks"]["suppression_guardrails_safe"] is True
    assert result["checks"]["clear_guardrails_safe"] is True
    assert result["checks"]["state_redaction_ready"] is True
    assert result["checks"]["route_static_ready"] is True
    assert result["checks"]["route_runtime_ready"] is True
    assert result["checks"]["quality_gate_hook_present"] is True
    assert all(result["checks"].values())
    assert "liveness_ack_state_privacy_runbook=pass" in evidence.summary_line(
        result
    )


def test_dispatch_daemon_liveness_ack_state_privacy_runbook_reports_route_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evidence,
        "_runtime_openapi_paths",
        lambda: {
            evidence.ACK_STATE_ACTION_ROUTE: {"post": {"operationId": "wrong"}},
            evidence.ACK_STATE_LIST_ROUTE: {"get": {"operationId": "wrong"}},
            evidence.ACK_STATE_DETAIL_ROUTE: {"get": {"operationId": "wrong"}},
        },
    )

    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence()
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == (
        "ag_operator_review_escalation_dispatch_daemon_"
        "liveness_ack_state_privacy_runbook_failed"
    )
    assert result["checks"]["route_runtime_ready"] is False
    assert "failure=ag_operator_review" in evidence.summary_line(result)


def test_dispatch_daemon_liveness_ack_state_privacy_runbook_reports_doc_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if str(path).endswith("0808_ag_dispatch_liveness_ack_state_postgres_smoke.md"):
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)

    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence()
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["docs_present"] is False
    assert any(not item["present"] for item in result["required_docs"])


def test_dispatch_daemon_liveness_ack_state_privacy_runbook_reports_long_table_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evidence,
        "AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE",
        "ag_operator_review_liveness_acknowledgement_state_too_long",
    )

    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence()
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["migration_table_name_within_limit"] is False
    assert result["surfaces"]["migration"]["table_name_within_limit"] is False


def test_dispatch_daemon_liveness_ack_state_privacy_runbook_detects_forbidden_shapes() -> None:
    payload = {
        "safe": {
            "raw_idempotency_key": evidence.FORBIDDEN_VALUES[
                "raw_idempotency_key"
            ],
            "redaction": {"raw_idempotency_key_included": True},
        }
    }
    serialized = str(payload)

    assert evidence._forbidden_key_paths(payload, evidence.FORBIDDEN_KEYS) == [
        "safe.raw_idempotency_key"
    ]
    assert evidence._forbidden_value_labels(serialized) == [
        "raw_idempotency_key"
    ]
    assert evidence._redaction_flags_safe(payload) is False
    with pytest.raises(ValueError):
        evidence._assert_no_forbidden_values(serialized)


def test_dispatch_daemon_liveness_ack_state_privacy_runbook_helper_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert evidence._overlay_surface(None) == {"present": False}
    assert evidence._mutation_guardrails_safe({}) is False
    assert evidence._parameter_names({"parameters": ["bad"]}) == set()
    assert evidence._redaction_flags_safe([{"ok": True}]) is True
    assert evidence._mutation_surface({}) == {
        "mutation_status": None,
        "ack_state_id": None,
        "action": None,
        "target_state_status": None,
        "stored_state_status": None,
        "comment_hash_present": False,
        "comment_preview_present": False,
        "idempotency_key_hash_present": False,
        "guardrails": {
            "source_liveness_projection_suppressed": None,
            "raw_comment_stored": None,
            "raw_idempotency_key_stored": None,
            "process_control_invoked": None,
        },
    }

    monkeypatch.setenv("NEX_AG_DISPATCH_DAEMON_ENABLED", "0")
    with evidence._temporary_environ({"NEX_AG_DISPATCH_DAEMON_ENABLED": "1"}):
        assert evidence.os.environ["NEX_AG_DISPATCH_DAEMON_ENABLED"] == "1"
    assert evidence.os.environ["NEX_AG_DISPATCH_DAEMON_ENABLED"] == "0"


def test_dispatch_daemon_liveness_ack_state_privacy_runbook_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        evidence,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence",
        lambda: {
            "status": "PASS",
            "surface_count": 7,
            "surfaces": {"migration": {"source_table": "ag_op_review_ack_state"}},
            "checks": {
                "forbidden_values_absent": True,
                "route_runtime_ready": True,
                "state_redaction_ready": True,
            },
        },
    )

    assert evidence.main(["--summary"]) == 0
    assert "liveness_ack_state_privacy_runbook=pass" in capsys.readouterr().out

    assert evidence.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        evidence,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert evidence.main(["--summary"]) == 1
    assert "liveness_ack_state_privacy_runbook=fail" in capsys.readouterr().out
