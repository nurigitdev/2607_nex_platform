from __future__ import annotations

from pathlib import Path

import run_ag_operator_review_escalation_dispatch_daemon_api_boundary_audit as audit


def test_ag_dispatch_daemon_api_boundary_passes_repo() -> None:
    evidence = audit.run_ag_operator_review_escalation_dispatch_daemon_api_boundary_audit()
    boundary = evidence["boundary"]

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0751"
    assert boundary["boundary"] == audit.BOUNDARY
    assert boundary["source_dispatch_table"] == "ag_op_esc_dispatches"
    assert boundary["route_implementation_in_slice_0751"] is False
    assert boundary["background_loop_in_slice_0751"] is False
    assert boundary["new_table_in_slice_0751"] is False
    assert boundary["first_tick_plan_route_slice"] == "Slice_0752"
    assert boundary["first_tick_once_route_slice"] == "Slice_0753"
    assert boundary["first_route_postgres_smoke_slice"] == "Slice_0754"
    assert boundary["allowed_actions"] == ["tick_plan", "tick_once"]
    assert boundary["tick_plan_mutates"] is False
    assert boundary["mutation_allowed_without_confirm"] is False
    assert boundary["auth_boundary"] == "reuse_nex_runtime_validate_authorization_header"
    assert boundary["real_external_endpoint_delivery"] == "deferred_until_full_system"
    assert evidence["api_surface_contract"]["tick_plan_route"] == {
        "path": "/admin/v1/operator-review/dispatch-daemon/tick-plan",
        "method": "GET_OR_POST",
        "mutation": False,
        "uses": "build_dispatch_execution_daemon_tick_plan",
    }
    assert evidence["api_surface_contract"]["tick_once_route"]["method"] == "POST"
    assert evidence["refactoring_checkpoint"] == {
        "route_handlers_should_be_thin": True,
        "reuse_control_request_builder": True,
        "reuse_control_admission_builder": True,
        "reuse_tick_plan_builder": True,
        "reuse_tick_once_executor": True,
        "reuse_operations_runtime_projection": True,
        "keep_provider_transport_injected": True,
        "keep_route_outputs_redacted": True,
        "keep_postgres_smoke_real_test_db": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert evidence["next_slices"] == [
        "Slice_0752",
        "Slice_0753",
        "Slice_0754",
        "Slice_0755",
        "Slice_0756",
        "Slice_0757",
        "Slice_0758",
        "Slice_0759",
        "Slice_0760",
    ]


def test_ag_dispatch_daemon_api_boundary_summary() -> None:
    evidence = audit.run_ag_operator_review_escalation_dispatch_daemon_api_boundary_audit()
    summary = audit.summary_line(evidence)

    assert summary.startswith(
        "ag_operator_review_escalation_dispatch_daemon_api_boundary=pass"
    )
    assert f"boundary={audit.BOUNDARY}" in summary
    assert "routes_in_slice_0751=False" in summary
    assert "tick_plan=Slice_0752" in summary
    assert "tick_once=Slice_0753" in summary


def test_ag_dispatch_daemon_api_boundary_reports_missing(tmp_path: Path) -> None:
    evidence = audit.run_ag_operator_review_escalation_dispatch_daemon_api_boundary_audit(
        tmp_path
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_escalation_dispatch_daemon_api_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["required_tokens_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "daemon_api_boundary=fail" in audit.summary_line(evidence)


def test_ag_dispatch_daemon_api_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    for item in audit.REQUIRED_PATHS:
        path = tmp_path / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = audit.run_ag_operator_review_escalation_dispatch_daemon_api_boundary_audit(
        tmp_path
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["required_tokens_present"] is False
    assert evidence["checks"]["control_foundation_present"] is False
    assert all(item["category"] == "source_token_missing" for item in evidence["issues"])


def test_ag_dispatch_daemon_api_boundary_main(capsys) -> None:
    assert audit.main(["--summary"]) == 0
    assert "daemon_api_boundary=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"audit_schema_version"' in capsys.readouterr().out
