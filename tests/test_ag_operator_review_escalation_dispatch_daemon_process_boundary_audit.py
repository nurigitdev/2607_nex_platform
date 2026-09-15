from __future__ import annotations

from pathlib import Path

import run_ag_operator_review_escalation_dispatch_daemon_process_boundary_audit as audit


def test_ag_dispatch_daemon_process_boundary_passes_repo() -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_process_boundary_audit()
    )
    boundary = evidence["boundary"]

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0771"
    assert evidence["surface"] == audit.S78_SURFACE
    assert boundary["boundary"] == audit.BOUNDARY
    assert boundary["source_dispatch_table"] == "ag_op_esc_dispatches"
    assert boundary["source_event_table"] == "service_operational_events"
    assert boundary["new_table_in_slice_0771"] is False
    assert boundary["daemon_loop_implementation_in_slice_0771"] is False
    assert boundary["subprocess_execution_in_slice_0771"] is False
    assert boundary["protected_process_control_route_in_slice_0771"] is False
    assert boundary["dashboard_mutation_in_slice_0771"] is False
    assert boundary["first_runtime_loop_policy_slice"] == "Slice_0772"
    assert boundary["first_process_metadata_contract_slice"] == "Slice_0773"
    assert boundary["first_executable_cli_slice"] == "Slice_0774"
    assert boundary["first_lifecycle_event_persistence_slice"] == "Slice_0775"
    assert boundary["first_protected_process_control_api_slice"] == "Slice_0776"
    assert boundary["first_process_dashboard_slice"] == "Slice_0777"
    assert boundary["postgres_smoke_slice"] == "Slice_0778"
    assert boundary["privacy_runbook_slice"] == "Slice_0779"
    assert boundary["closure_slice"] == "Slice_0780"
    assert boundary["real_external_endpoint_delivery"] == "deferred_until_full_system"
    assert evidence["process_contract"]["daemon_loop"] == {
        "owner": "nex-ag",
        "entrypoint": "future_executable_cli",
        "tick_executor": "run_dispatch_execution_daemon_tick_once",
        "new_table_required": False,
        "mutation_in_slice_0771": False,
    }
    assert evidence["process_contract"]["process_state"] == {
        "primary_source": "service_operational_events",
        "liveness_source": "service_worker_heartbeats",
        "worker_heartbeat_reuse": "preferred_before_new_table",
        "new_table_required": False,
    }
    assert evidence["process_contract"]["operator_control"][
        "start_stop_mutation_in_slice_0771"
    ] is False
    assert evidence["refactoring_checkpoint"] == {
        "keep_tick_execution_pure": True,
        "isolate_process_loop_from_tick_once_executor": True,
        "keep_cli_thin": True,
        "reuse_operational_event_emitter": True,
        "prefer_worker_heartbeat_store_for_liveness": True,
        "keep_postgres_smoke_real_test_db": True,
        "keep_sensitive_values_redacted": True,
        "avoid_new_table_until_process_query_pressure_is_proven": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_names"])
    assert evidence["next_slices"] == [
        "Slice_0772",
        "Slice_0773",
        "Slice_0774",
        "Slice_0775",
        "Slice_0776",
        "Slice_0777",
        "Slice_0778",
        "Slice_0779",
        "Slice_0780",
    ]


def test_ag_dispatch_daemon_process_boundary_summary() -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_process_boundary_audit()
    )
    summary = audit.summary_line(evidence)

    assert summary.startswith(
        "ag_operator_review_escalation_dispatch_daemon_process_boundary=pass"
    )
    assert f"boundary={audit.BOUNDARY}" in summary
    assert "new_table=False" in summary
    assert "loop_policy=Slice_0772" in summary
    assert "metadata=Slice_0773" in summary
    assert "cli=Slice_0774" in summary


def test_ag_dispatch_daemon_process_boundary_reports_missing(tmp_path: Path) -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_process_boundary_audit(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_escalation_dispatch_daemon_process_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["required_tokens_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "process_boundary=fail" in audit.summary_line(evidence)


def test_ag_dispatch_daemon_process_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    for item in audit.REQUIRED_PATHS:
        path = tmp_path / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_process_boundary_audit(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["required_tokens_present"] is False
    assert evidence["checks"]["tick_execution_baseline_present"] is False
    assert evidence["checks"]["heartbeat_foundation_present"] is False
    assert all(
        item["category"] == "source_token_missing" for item in evidence["issues"]
    )


def test_ag_dispatch_daemon_process_boundary_reports_long_table_name(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "TABLE_NAMES_UNDER_REVIEW",
        ("ag_operator_review_escalation_dispatch_daemon_process_runs_too_long",),
    )

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_process_boundary_audit()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_names_within_limit"] is False
    assert any(item["category"] == "table_name_too_long" for item in evidence["issues"])


def test_ag_dispatch_daemon_process_boundary_group_present_requires_members() -> None:
    assert audit._group_present([], "missing_group") is False
    assert (
        audit._group_present(
            [
                {"group": "candidate", "present": True},
                {"group": "candidate", "present": False},
            ],
            "candidate",
        )
        is False
    )
    assert audit._group_present([{"group": "candidate", "present": True}], "candidate")


def test_ag_dispatch_daemon_process_boundary_main(capsys, monkeypatch) -> None:
    assert audit.main(["--summary"]) == 0
    assert "process_boundary=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"audit_schema_version"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_escalation_dispatch_daemon_process_boundary_audit",
        lambda: {
            "status": "FAIL",
            "failure_code": "forced_failure",
            "issues": [{"category": "source_token_missing"}],
        },
    )
    assert audit.main(["--summary"]) == 1
    assert "process_boundary=fail" in capsys.readouterr().out
