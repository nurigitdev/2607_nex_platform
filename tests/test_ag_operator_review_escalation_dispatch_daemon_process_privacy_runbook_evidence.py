from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence as evidence


def test_dispatch_daemon_process_privacy_runbook_evidence_passes() -> None:
    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence()
    )

    assert result["status"] == "PASS"
    assert result["runbook_schema_version"] == evidence.SCHEMA_VERSION
    assert result["slice"] == "0779"
    assert result["surface_count"] == 4
    assert result["route"]["path"] == evidence.PROCESS_CONTROL_ROUTE
    assert result["route"]["runtime_ready"] is True
    assert result["forbidden_value_labels"] == []
    assert result["forbidden_key_paths"] == []
    assert result["surfaces"]["lifecycle_events"]["blocked_count"] == 1
    assert result["checks"]["process_control_contract_only"] is True
    assert result["checks"]["runbook_ids_ready"] is True
    assert result["checks"]["operator_actions_ready"] is True
    assert result["checks"]["quality_gate_hook_present"] is True
    assert all(result["checks"].values())
    assert "process_privacy_runbook=pass" in evidence.summary_line(result)


def test_dispatch_daemon_process_privacy_runbook_reports_route_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evidence,
        "_runtime_openapi_paths",
        lambda: {evidence.PROCESS_CONTROL_ROUTE: {"post": {"operationId": "wrong"}}},
    )

    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence()
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == (
        "ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_failed"
    )
    assert result["checks"]["runtime_process_control_route_ready"] is False
    assert "failure=ag_operator_review" in evidence.summary_line(result)


def test_dispatch_daemon_process_privacy_runbook_reports_doc_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if str(path).endswith(
            "0778_ag_escalation_dispatch_daemon_process_postgres_smoke.md"
        ):
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)

    result = (
        evidence.run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence()
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["docs_present"] is False
    assert any(not item["present"] for item in result["required_docs"])


def test_dispatch_daemon_process_privacy_runbook_detects_forbidden_shapes() -> None:
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


def test_dispatch_daemon_process_privacy_runbook_seed_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evidence,
        "emit_dispatch_execution_daemon_lifecycle_event",
        lambda *args, **kwargs: SimpleNamespace(ok=False),
    )

    with pytest.raises(ValueError):
        evidence._seed_process_event_store()


def test_dispatch_daemon_process_privacy_runbook_helper_defaults() -> None:
    assert evidence._runbook_paths_ready({}, {}, {}) is False
    assert evidence._redaction_flags_safe([{"ok": True}]) is True


def test_dispatch_daemon_process_privacy_runbook_main(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        evidence,
        "run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence",
        lambda: {
            "status": "PASS",
            "surface_count": 4,
            "checks": {
                "forbidden_values_absent": True,
                "runbook_ids_ready": True,
                "runtime_process_control_route_ready": True,
            },
        },
    )

    assert evidence.main(["--summary"]) == 0
    assert "process_privacy_runbook=pass" in capsys.readouterr().out

    assert evidence.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        evidence,
        "run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert evidence.main(["--summary"]) == 1
