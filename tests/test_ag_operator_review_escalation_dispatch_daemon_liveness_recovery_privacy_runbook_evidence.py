from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence as evidence


def test_dispatch_daemon_liveness_recovery_privacy_runbook_evidence_passes() -> None:
    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence()
    )
    surfaces = result["surfaces"]
    persistence = surfaces["persistence_decision"]

    assert result["status"] == "PASS"
    assert result["runbook_schema_version"] == evidence.SCHEMA_VERSION
    assert result["slice"] == "0798"
    assert result["surface_count"] == 8
    assert result["route"]["path"] == evidence.RECOVERY_PLAN_ROUTE
    assert result["route"]["runtime_ready"] is True
    assert result["route"]["static_openapi_hardening_deferred_to_slice_0799"] is True
    assert result["forbidden_value_labels"] == []
    assert result["forbidden_key_paths"] == []
    assert surfaces["stale_recovery"]["liveness_status"] == "STALE"
    assert surfaces["missing_recovery"]["liveness_status"] == "MISSING"
    assert surfaces["dashboard_recovery"]["liveness_status"] == "STALE"
    assert surfaces["audit_details"]["recovery_status"] == "PLANNED"
    assert surfaces["stale_issue_candidate"]["ack_policy_status"] == "ACTIONABLE"
    assert surfaces["missing_issue_candidate"]["ack_policy_status"] == "ACTIONABLE"
    assert persistence["current_state_persisted"] is False
    assert persistence["new_table_in_slice_0798"] is False
    assert persistence["future_table_candidate"] == "ag_op_review_ack_state"
    assert persistence["future_table_name_within_limit"] is True
    assert persistence["policy_statuses"] == ["ACTIONABLE"]
    assert all(result["checks"].values())
    assert "liveness_recovery_privacy_runbook=pass" in evidence.summary_line(result)


def test_dispatch_daemon_liveness_recovery_privacy_runbook_reports_route_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evidence,
        "_runtime_openapi_paths",
        lambda: {
            evidence.RECOVERY_PLAN_ROUTE: {"get": {"operationId": "wrong"}}
        },
    )

    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence()
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == (
        "ag_operator_review_escalation_dispatch_daemon_"
        "liveness_recovery_privacy_runbook_failed"
    )
    assert result["checks"]["runtime_recovery_route_ready"] is False
    assert "failure=ag_operator_review" in evidence.summary_line(result)


def test_dispatch_daemon_liveness_recovery_privacy_runbook_reports_doc_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if str(path).endswith(
            "0797_ag_escalation_dispatch_daemon_liveness_recovery_postgres_smoke.md"
        ):
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)

    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence()
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["docs_present"] is False
    assert any(not item["present"] for item in result["required_docs"])


def test_dispatch_daemon_liveness_recovery_privacy_runbook_reports_long_table_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evidence,
        "FUTURE_ACK_STATE_TABLE",
        "ag_operator_review_acknowledgement_suppression_state_too_long",
    )

    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence()
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["future_table_name_within_limit"] is False
    assert result["surfaces"]["persistence_decision"][
        "future_table_name_within_limit"
    ] is False


def test_dispatch_daemon_liveness_recovery_privacy_runbook_detects_forbidden_shapes() -> None:
    payload = {
        "safe": {
            "raw_operator_comment": evidence.FORBIDDEN_VALUES[
                "raw_operator_comment"
            ],
            "redaction": {"raw_operator_comment_included": True},
        }
    }
    serialized = str(payload)

    assert evidence._forbidden_key_paths(payload, evidence.FORBIDDEN_KEYS) == [
        "safe.raw_operator_comment"
    ]
    assert evidence._forbidden_value_labels(serialized) == [
        "raw_operator_comment"
    ]
    assert evidence._redaction_flags_safe(payload) is False
    with pytest.raises(ValueError):
        evidence._assert_no_forbidden_values(serialized)


def test_dispatch_daemon_liveness_recovery_privacy_runbook_helper_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert evidence._heartbeat_store_with_status("FRESH").get_heartbeat(
        evidence.SERVICE_ID,
        evidence.WORKER_ID,
    )
    assert evidence._liveness_issue_candidate({"issue_candidates": object()}) is None
    assert evidence._liveness_issue_candidate({"issue_candidates": []}) is None
    assert evidence._liveness_issue_candidate(
        {"issue_candidates": [{"rule_id": "other"}]}
    ) is None
    assert evidence._issue_signal(None) == {}
    assert evidence._issue_signal({"signal": "not-a-mapping"}) == {}
    assert evidence._issue_ack_policy(None) == {}
    assert evidence._issue_ack_policy({"signal": "not-a-mapping"}) == {}
    assert evidence._issue_candidate_summary(None) is None
    assert evidence._issue_candidate_summary(
        {
            "rule_id": "operator_review_dispatch_daemon_liveness_attention_required.v1",
            "severity": "ERROR",
            "signal": "not-a-mapping",
        }
    ) == {
        "rule_id": "operator_review_dispatch_daemon_liveness_attention_required.v1",
        "severity": "ERROR",
        "signal_status": None,
        "runbook_ids": [],
        "recommended_operator_actions": [],
        "ack_policy_status": None,
        "ack_policy_new_tables_required": None,
    }
    assert evidence._expected_runbooks_ready({}) is False
    assert evidence._expected_operator_actions_ready({}) is False
    assert evidence._redaction_flags_safe([{"ok": True}]) is True

    monkeypatch.setenv("NEX_AG_DISPATCH_DAEMON_ENABLED", "0")
    with evidence._temporary_environ({"NEX_AG_DISPATCH_DAEMON_ENABLED": "1"}):
        assert evidence.os.environ["NEX_AG_DISPATCH_DAEMON_ENABLED"] == "1"
    assert evidence.os.environ["NEX_AG_DISPATCH_DAEMON_ENABLED"] == "0"


def test_dispatch_daemon_liveness_recovery_privacy_runbook_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        evidence,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence",
        lambda: {
            "status": "PASS",
            "surface_count": 8,
            "surfaces": {
                "persistence_decision": {
                    "future_table_candidate": "ag_op_review_ack_state",
                    "current_state_persisted": False,
                }
            },
            "checks": {
                "forbidden_values_absent": True,
                "runbook_ids_ready": True,
            },
        },
    )

    assert evidence.main(["--summary"]) == 0
    assert "liveness_recovery_privacy_runbook=pass" in capsys.readouterr().out

    assert evidence.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        evidence,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert evidence.main(["--summary"]) == 1
    assert "liveness_recovery_privacy_runbook=fail" in capsys.readouterr().out
