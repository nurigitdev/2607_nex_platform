from __future__ import annotations

from pathlib import Path

import run_ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit as audit


def test_ag_dispatch_daemon_operations_boundary_passes_repo() -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit()
    )
    boundary = evidence["boundary"]

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0761"
    assert evidence["surface"] == audit.S77_SURFACE
    assert boundary["boundary"] == audit.BOUNDARY
    assert boundary["source_dispatch_table"] == "ag_op_esc_dispatches"
    assert boundary["new_table_in_slice_0761"] is False
    assert boundary["route_implementation_in_slice_0761"] is False
    assert boundary["dashboard_mutation_in_slice_0761"] is False
    assert boundary["background_loop_in_slice_0761"] is False
    assert boundary["first_audit_event_slice"] == "Slice_0762"
    assert boundary["first_control_history_read_model_slice"] == "Slice_0763"
    assert boundary["first_control_history_route_slice"] == "Slice_0764"
    assert boundary["first_dashboard_integration_slice"] == "Slice_0765"
    assert boundary["first_issue_candidate_slice"] == "Slice_0766"
    assert boundary["contract_openapi_slice"] == "Slice_0767"
    assert boundary["postgres_smoke_slice"] == "Slice_0768"
    assert boundary["privacy_runbook_slice"] == "Slice_0769"
    assert boundary["closure_slice"] == "Slice_0770"
    assert boundary["real_external_endpoint_delivery"] == "deferred_until_full_system"
    assert evidence["operations_contract"]["control_audit_event"] == {
        "owner": "nex-ag",
        "store": "OperationalEventStore",
        "persistence_adapter": "SqlAlchemyOperationalEventStore",
        "raw_request_payloads_allowed": False,
        "raw_provider_payloads_allowed": False,
    }
    assert evidence["operations_contract"]["control_history"]["new_table_required"] is False
    assert evidence["operations_contract"]["dashboard"]["mutation"] is False
    assert evidence["operations_contract"]["issue_candidates"]["mutation"] is False
    assert evidence["refactoring_checkpoint"] == {
        "keep_route_handlers_thin": True,
        "extract_control_event_builder_before_route_wiring": True,
        "reuse_operational_event_emitter": True,
        "reuse_existing_dashboard_projection": True,
        "reuse_existing_issue_candidate_projection": True,
        "keep_history_read_model_query_pure": True,
        "keep_postgres_smoke_real_test_db": True,
        "keep_sensitive_values_redacted": True,
        "avoid_new_table_until_query_pressure_is_proven": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_names"])
    assert evidence["next_slices"] == [
        "Slice_0762",
        "Slice_0763",
        "Slice_0764",
        "Slice_0765",
        "Slice_0766",
        "Slice_0767",
        "Slice_0768",
        "Slice_0769",
        "Slice_0770",
    ]


def test_ag_dispatch_daemon_operations_boundary_summary() -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit()
    )
    summary = audit.summary_line(evidence)

    assert summary.startswith(
        "ag_operator_review_escalation_dispatch_daemon_operations_boundary=pass"
    )
    assert f"boundary={audit.BOUNDARY}" in summary
    assert "new_table=False" in summary
    assert "audit_event=Slice_0762" in summary
    assert "history=Slice_0763" in summary
    assert "dashboard=Slice_0765" in summary


def test_ag_dispatch_daemon_operations_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_escalation_dispatch_daemon_operations_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["required_tokens_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "operations_boundary=fail" in audit.summary_line(evidence)


def test_ag_dispatch_daemon_operations_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    for item in audit.REQUIRED_PATHS:
        path = tmp_path / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["required_tokens_present"] is False
    assert evidence["checks"]["operational_event_foundation_present"] is False
    assert all(
        item["category"] == "source_token_missing" for item in evidence["issues"]
    )


def test_ag_dispatch_daemon_operations_boundary_reports_long_table_name(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "TABLE_NAMES_UNDER_REVIEW",
        ("ag_operator_review_escalation_dispatches_too_long",),
    )

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_names_within_limit"] is False
    assert any(item["category"] == "table_name_too_long" for item in evidence["issues"])


def test_ag_dispatch_daemon_operations_boundary_main(capsys, monkeypatch) -> None:
    assert audit.main(["--summary"]) == 0
    assert "operations_boundary=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"audit_schema_version"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_escalation_dispatch_daemon_operations_boundary_audit",
        lambda: {
            "status": "FAIL",
            "failure_code": "forced_failure",
            "issues": [{"category": "source_token_missing"}],
        },
    )
    assert audit.main(["--summary"]) == 1
    assert "operations_boundary=fail" in capsys.readouterr().out
