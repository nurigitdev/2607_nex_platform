from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence as runbook


def test_dispatch_daemon_api_runbook_evidence_passes() -> None:
    evidence = (
        runbook.run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence()
    )

    assert evidence["status"] == "PASS"
    assert evidence["runbook_schema_version"] == runbook.SCHEMA_VERSION
    assert evidence["route_count"] == 3
    assert all(evidence["checks"].values())
    assert evidence["control_request_contract"]["forbidden_present"] == []
    assert "runtime_routes_ready=True" in runbook.summary_line(evidence)


def test_route_evidence_reports_missing_runtime_route() -> None:
    path = "/admin/v1/operator-review/dispatch-daemon/tick-plan"
    item = runbook._route_evidence(
        path,
        "get",
        runbook.ROUTES[(path, "get")],
        {path: {"get": {"operationId": "getAgOperatorReviewDispatchDaemonTickPlan"}}},
        {},
    )

    assert item["static_ready"] is True
    assert item["runtime_ready"] is False
    assert item["runtime_operation_id"] is None


def test_dispatch_daemon_api_runbook_evidence_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "/admin/v1/operator-review/dispatch-daemon/tick-plan"
    bad_paths = {path: {"get": {"operationId": "wrong"}}}
    monkeypatch.setattr(runbook, "_load_static_openapi_paths", lambda root: bad_paths)
    monkeypatch.setattr(runbook, "_runtime_openapi_paths", lambda: bad_paths)
    monkeypatch.setattr(
        runbook,
        "_control_request_properties",
        lambda root: {"provider_payload", "enabled"},
    )
    monkeypatch.setattr(Path, "exists", lambda self: True)

    evidence = (
        runbook.run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_escalation_dispatch_daemon_api_runbook_failed"
    )
    assert evidence["checks"]["static_routes_ready"] is False
    assert evidence["checks"]["sensitive_control_fields_absent"] is False
    assert "failure=ag_operator_review" in runbook.summary_line(evidence)


def test_dispatch_daemon_api_runbook_evidence_main(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        runbook,
        "run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence",
        lambda: {
            "status": "PASS",
            "route_count": 3,
            "checks": {
                "runtime_routes_ready": True,
                "sensitive_control_fields_absent": True,
            },
        },
    )

    assert runbook.main(["--summary"]) == 0
    assert "api_runbook=pass" in capsys.readouterr().out

    assert runbook.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runbook,
        "run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert runbook.main(["--summary"]) == 1
