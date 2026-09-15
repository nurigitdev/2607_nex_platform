from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence as evidence


def test_dispatch_daemon_liveness_privacy_runbook_evidence_passes() -> None:
    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence()
    )

    assert result["status"] == "PASS"
    assert result["runbook_schema_version"] == evidence.SCHEMA_VERSION
    assert result["slice"] == "0789"
    assert result["surface_count"] == 6
    assert result["route"]["path"] == evidence.LIVENESS_ROUTE
    assert result["route"]["runtime_ready"] is True
    assert result["forbidden_value_labels"] == []
    assert result["forbidden_key_paths"] == []
    assert result["surfaces"]["stale_liveness"]["liveness_status"] == "STALE"
    assert result["surfaces"]["missing_liveness"]["liveness_status"] == "MISSING"
    assert result["surfaces"]["stale_issue_candidate"]["signal_status"] == "STALE"
    assert result["surfaces"]["missing_issue_candidate"]["signal_status"] == "MISSING"
    assert result["checks"]["runbook_ids_ready"] is True
    assert result["checks"]["operator_actions_ready"] is True
    assert result["checks"]["quality_gate_hook_present"] is True
    assert all(result["checks"].values())
    assert "liveness_privacy_runbook=pass" in evidence.summary_line(result)


def test_dispatch_daemon_liveness_privacy_runbook_reports_route_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evidence,
        "_runtime_openapi_paths",
        lambda: {evidence.LIVENESS_ROUTE: {"get": {"operationId": "wrong"}}},
    )

    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence()
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == (
        "ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_failed"
    )
    assert result["checks"]["runtime_liveness_route_ready"] is False
    assert "failure=ag_operator_review" in evidence.summary_line(result)


def test_dispatch_daemon_liveness_privacy_runbook_reports_doc_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if str(path).endswith(
            "0788_ag_escalation_dispatch_daemon_liveness_postgres_smoke.md"
        ):
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)

    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence()
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["docs_present"] is False
    assert any(not item["present"] for item in result["required_docs"])


def test_dispatch_daemon_liveness_privacy_runbook_detects_forbidden_shapes() -> None:
    payload = {
        "safe": {
            "database_url": evidence.FORBIDDEN_VALUES["database_url"],
            "redaction": {"raw_request_payload_included": True},
        }
    }
    serialized = str(payload)

    assert evidence._forbidden_key_paths(payload, evidence.FORBIDDEN_KEYS) == [
        "safe.database_url"
    ]
    assert evidence._forbidden_value_labels(serialized) == [
        "database_password",
        "database_url",
    ]
    assert evidence._redaction_flags_safe(payload) is False
    with pytest.raises(ValueError):
        evidence._assert_no_forbidden_values(serialized)


def test_dispatch_daemon_liveness_privacy_runbook_helper_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert evidence._liveness_issue_candidate({"issue_candidates": object()}) is None
    assert evidence._liveness_issue_candidate({"issue_candidates": []}) is None
    assert evidence._liveness_issue_candidate(
        {"issue_candidates": [{"rule_id": "other"}]}
    ) is None
    assert evidence._issue_signal(None) == {}
    assert evidence._issue_signal({"signal": "not-a-mapping"}) == {}
    assert evidence._issue_signal_status(None) is None
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
    }
    assert evidence._runbook_paths_ready({}) is False
    assert evidence._redaction_flags_safe([{"ok": True}]) is True

    monkeypatch.setenv("NEX_AG_DISPATCH_DAEMON_ENABLED", "0")
    with evidence._temporary_environ({"NEX_AG_DISPATCH_DAEMON_ENABLED": "1"}):
        assert evidence.os.environ["NEX_AG_DISPATCH_DAEMON_ENABLED"] == "1"
    assert evidence.os.environ["NEX_AG_DISPATCH_DAEMON_ENABLED"] == "0"


def test_dispatch_daemon_liveness_privacy_runbook_main(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        evidence,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence",
        lambda: {
            "status": "PASS",
            "surface_count": 6,
            "checks": {
                "forbidden_values_absent": True,
                "runbook_ids_ready": True,
                "runtime_liveness_route_ready": True,
            },
        },
    )

    assert evidence.main(["--summary"]) == 0
    assert "liveness_privacy_runbook=pass" in capsys.readouterr().out

    assert evidence.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        evidence,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert evidence.main(["--summary"]) == 1
