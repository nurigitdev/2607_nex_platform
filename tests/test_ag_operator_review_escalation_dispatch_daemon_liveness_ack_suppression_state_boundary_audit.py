from __future__ import annotations

from pathlib import Path

import run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit as audit


def test_ag_dispatch_daemon_liveness_ack_suppression_state_boundary_passes_repo() -> (
    None
):
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit()
    )
    boundary = evidence["boundary"]

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0801"
    assert evidence["surface"] == audit.S81_SURFACE
    assert boundary == {
        "boundary": audit.BOUNDARY,
        "owner_service": "nex-ag",
        "state_table_candidate": "ag_op_review_ack_state",
        "source_event_table": "service_operational_events",
        "source_heartbeat_table": "service_worker_heartbeats",
        "new_table_in_slice_0801": False,
        "state_mutation_route_in_slice_0801": False,
        "current_liveness_projection_suppressed": False,
        "first_persistence_slice": "Slice_0802",
        "first_state_machine_slice": "Slice_0803",
        "first_protected_action_api_slice": "Slice_0804",
        "first_persisted_read_model_slice": "Slice_0805",
        "first_dashboard_issue_overlay_slice": "Slice_0806",
        "contract_openapi_slice": "Slice_0807",
        "postgres_smoke_slice": "Slice_0808",
        "privacy_runbook_slice": "Slice_0809",
        "closure_slice": "Slice_0810",
    }
    assert evidence["state_contract"] == {
        "state_key": "acknowledgement_key",
        "supported_actions": [
            "acknowledge_once",
            "suppress_for_ttl",
            "acknowledge_source_attention",
            "suppress_source_attention_for_ttl",
        ],
        "state_statuses": [
            "ACKNOWLEDGED",
            "SUPPRESSED",
            "EXPIRED",
            "CLEARED",
        ],
        "default_suppression_ttl_seconds": 1800,
        "max_suppression_ttl_seconds": 86400,
        "idempotency_storage": "sha256_hash_only",
        "operator_comment_storage": "sha256_hash_and_bounded_preview_only",
        "operator_identity_required": True,
        "reason_codes_required": True,
        "expires_at_required_for_ttl_suppression": True,
        "state_overlay_target": "dashboard_issue_candidate_recovery_plan_only",
    }
    assert evidence["storage_decision"]["allowed_fields"] == [
        "ack_state_id",
        "acknowledgement_key",
        "service_id",
        "worker_id",
        "worker_type",
        "liveness_status",
        "action",
        "state_status",
        "operator_ref",
        "reason_codes",
        "comment_hash",
        "comment_preview",
        "idempotency_key_hash",
        "requested_ttl_seconds",
        "suppressed_until",
        "created_at",
        "updated_at",
        "cleared_at",
        "metadata",
    ]
    assert "raw_comment" in evidence["storage_decision"]["forbidden_fields"]
    assert "raw_idempotency_key" in evidence["storage_decision"]["forbidden_fields"]
    assert evidence["separation_of_concerns"] == {
        "liveness_status": (
            "continues_to_be_derived_from_service_worker_heartbeats"
        ),
        "ack_suppression_state": "operator_overlay_state_owned_by_nex_ag",
        "issue_candidate": (
            "may_be_marked_acknowledged_or_suppressed_without_hiding_liveness"
        ),
        "recovery_plan": (
            "may_include_operator_state_overlay_but_remains_read_only"
        ),
        "process_control": "not_invoked_by_ack_or_suppression_actions",
        "audit_events": "safe_summary_only_for_action_history",
    }
    assert evidence["refactoring_checkpoint"] == {
        "reuse_s80_ack_policy_shape": True,
        "reuse_s70_safe_comment_hash_preview_pattern": True,
        "reuse_s70_idempotency_hash_pattern": True,
        "keep_route_handlers_thin": True,
        "keep_state_store_behind_interface": True,
        "keep_postgres_smoke_real_test_db": True,
        "keep_sensitive_values_redacted": True,
        "defer_retention_cleanup_to_s89": True,
    }
    assert evidence["next_slices"] == [
        "Slice_0802",
        "Slice_0803",
        "Slice_0804",
        "Slice_0805",
        "Slice_0806",
        "Slice_0807",
        "Slice_0808",
        "Slice_0809",
        "Slice_0810",
    ]
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_names"])
    assert all(item["boundary_safe"] for item in evidence["storage_fields"])


def test_ag_dispatch_daemon_liveness_ack_suppression_state_boundary_summary() -> (
    None
):
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit()
    )
    summary = audit.summary_line(evidence)

    assert summary.startswith(
        "ag_operator_review_escalation_dispatch_daemon_"
        "liveness_ack_suppression_state_boundary=pass"
    )
    assert f"boundary={audit.BOUNDARY}" in summary
    assert "table=ag_op_review_ack_state" in summary
    assert "new_table=False" in summary
    assert "projection_suppressed=False" in summary
    assert "default_ttl=1800" in summary
    assert "next=Slice_0802" in summary


def test_ag_dispatch_daemon_liveness_ack_suppression_state_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_escalation_dispatch_daemon_liveness_"
        "ack_suppression_state_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["required_tokens_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "liveness_ack_suppression_state_boundary=fail" in audit.summary_line(
        evidence
    )


def test_ag_dispatch_daemon_liveness_ack_suppression_state_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    for item in audit.REQUIRED_PATHS:
        path = tmp_path / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["required_tokens_present"] is False
    assert evidence["checks"]["s80_closed_baseline_present"] is False
    assert evidence["checks"]["ack_policy_runtime_present"] is False
    assert all(
        item["category"] == "source_token_missing" for item in evidence["issues"]
    )


def test_ag_dispatch_daemon_liveness_ack_suppression_state_boundary_reports_long_table_name(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "TABLE_NAMES_UNDER_REVIEW",
        (
            "ag_operator_review_dispatch_daemon_liveness_ack_suppression_state_too_long",
        ),
    )

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_names_within_limit"] is False
    assert any(item["category"] == "table_name_too_long" for item in evidence["issues"])


def test_ag_dispatch_daemon_liveness_ack_suppression_state_boundary_reports_unsafe_storage_field(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_storage_field_results",
        lambda: [
            {
                "field": "raw_comment",
                "classification": "forbidden",
                "allowed": True,
                "boundary_safe": False,
            }
        ],
    )

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["storage_fields_redacted"] is False
    assert any(
        item["category"] == "forbidden_storage_field_marked_allowed"
        for item in evidence["issues"]
    )


def test_ag_dispatch_daemon_liveness_ack_suppression_state_boundary_group_present_requires_members() -> (
    None
):
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


def test_ag_dispatch_daemon_liveness_ack_suppression_state_boundary_main(
    capsys,
    monkeypatch,
) -> None:
    assert audit.main(["--summary"]) == 0
    assert "liveness_ack_suppression_state_boundary=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"audit_schema_version"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        (
            "run_ag_operator_review_escalation_dispatch_daemon_liveness_"
            "ack_suppression_state_boundary_audit"
        ),
        lambda: {
            "status": "FAIL",
            "failure_code": "forced_failure",
            "issues": [{"category": "source_token_missing"}],
        },
    )
    assert audit.main(["--summary"]) == 1
    assert "liveness_ack_suppression_state_boundary=fail" in capsys.readouterr().out
