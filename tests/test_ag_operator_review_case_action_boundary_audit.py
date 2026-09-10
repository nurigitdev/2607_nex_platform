from __future__ import annotations

import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest

import run_ag_operator_review_case_action_boundary_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AG_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0641@127.0.0.1:5432/nex_ag_dev"
        ),
        "NEX_AG_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0641@127.0.0.1:5432/nex_ag_test"
        ),
        "NEX_AG_OPERATIONS_SOURCE_MODE": "postgres",
        "NEX_AG_OPERATIONS_SOURCE_PROFILE": "test",
        "NEX_AG_AE_ARTIFACT_BASE_URL": "http://127.0.0.1:8102/private",
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": "service-token-0641",
        "NEX_AG_TO_NEX_AE_API_SERVICE_TOKEN": "service-token-ae-0641",
        "NEX_SERVICE_TOKEN": "service-token-shared-0641",
    }


def test_ag_operator_review_case_action_boundary_passes_repo() -> None:
    evidence = audit.run_ag_operator_review_case_action_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0641"
    assert evidence["surface"] == audit.S65_SURFACE
    assert evidence["case_action_boundary"] == {
        "system_of_record": "nex-ag",
        "persistence_owner": "nex-ag",
        "action_owner": "nex-ag",
        "boundary": "ag_owned_operator_review_cases_actions",
        "create_table_in_slice_0641": False,
        "first_schema_slice": "Slice_0642",
        "candidate_case_table": "ag_op_cases",
        "candidate_case_table_length": 11,
        "reserved_future_action_event_table": "ag_op_case_events",
        "reserved_future_action_event_table_length": 17,
        "action_history_policy": "operational_events_first_no_action_table_in_s65",
        "source_tables": [
            {"table_name": "ag_op_notes", "role": "operator_note_metadata"},
            {
                "table_name": "ag_ev_exports",
                "role": "redacted_evidence_export_metadata",
            },
        ],
        "source_record_owners": ["nex-ae-api", "nex-cx", "nex-mo", "nex-oa"],
        "target_reference_columns": [
            "target_service",
            "target_kind",
            "target_id",
            "trace_id",
            "request_id",
        ],
        "target_reference_columns_indexable": True,
        "case_statuses": [
            "OPEN",
            "ACKNOWLEDGED",
            "ASSIGNED",
            "RESOLVED",
            "DISMISSED",
            "REOPENED",
        ],
        "case_action_commands": [
            "CREATE_CASE",
            "ACKNOWLEDGE",
            "ASSIGN",
            "RESOLVE",
            "DISMISS",
            "REOPEN",
        ],
        "case_intake_sources": [
            "operator_review_workbench_target",
            "operator_review_attention_required_issue_candidate",
            "operator_review_note_ref",
            "redacted_evidence_export_ref",
        ],
        "allowed_ag_case_writes": [
            "case_status",
            "case_priority",
            "case_assignment_ref",
            "target_reference",
            "safe_reason_codes",
            "resolution_hash",
            "resolution_preview",
            "idempotency_key_hash",
        ],
        "forbidden_case_payloads": [
            "raw_operator_note_text",
            "raw_evidence_body",
            "raw_prompt_text",
            "raw_generation_output_text",
            "raw_source_document_text",
            "raw_provider_payload",
            "database_url",
            "service_token",
            "provider_api_key",
            "local_storage_path",
            "source_service_record_blob",
            "artifact_binary_payload",
            "raw_idempotency_key",
            "external_notification_secret",
        ],
        "case_comment_storage_shape": "hash_and_short_preview_only",
        "operator_auth_policy": "service_token_or_admin_user_claim_required",
        "idempotency_key_required_for_mutating_actions": True,
        "notification_delivery_deferred": True,
        "external_incident_sync_deferred": True,
        "postgres_smoke_required_before_operational_enablement": True,
        "ag_may_write_own_case_records": True,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
    }
    assert evidence["refactoring_checkpoint"] == {
        "keep_case_records_separate_from_note_and_export_records": True,
        "keep_source_service_records_read_only": True,
        "reuse_workbench_target_refs_for_case_intake": True,
        "split_target_reference_into_indexable_columns": True,
        "add_case_repository_before_route_wiring": True,
        "model_actions_as_idempotent_state_transitions": True,
        "emit_action_audit_events_without_raw_comments": True,
        "store_free_text_as_hash_and_short_preview_only": True,
        "defer_action_history_table_until_operational_events_are_insufficient": True,
        "defer_notifications_and_external_incident_sync": True,
        "require_admin_or_service_claims_for_mutating_actions": True,
        "require_real_nex_ag_test_db_smoke_before_case_closure": True,
        "do_not_mutate_ae_cx_mo_oa_records": True,
        "do_not_copy_raw_prompts_source_docs_provider_payloads_or_storage_paths": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_name_results"])
    assert evidence["next_slices"] == [
        "Slice_0642",
        "Slice_0643",
        "Slice_0644",
        "Slice_0645",
        "Slice_0646",
        "Slice_0647",
        "Slice_0648",
        "Slice_0649",
        "Slice_0650",
    ]

    summary = audit.summary_line(evidence)
    assert "ag_operator_review_case_action_boundary_audit=pass" in summary
    assert "boundary=ag_owned_operator_review_cases_actions" in summary
    assert "case_table=ag_op_cases" in summary
    assert "action_history=operational_events_first" in summary
    assert "next=Slice_0642" in summary


def test_ag_operator_review_case_action_boundary_redacts_env() -> None:
    env = protected_env()

    evidence = audit.run_ag_operator_review_case_action_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0641" not in serialized
    assert "service-token-0641" not in serialized
    assert env["NEX_AG_TEST_DATABASE_URL"] not in serialized
    assert evidence["protected_env"] == {
        "NEX_AG_DATABASE_URL": True,
        "NEX_AG_TEST_DATABASE_URL": True,
        "NEX_AG_OPERATIONS_SOURCE_MODE": True,
        "NEX_AG_OPERATIONS_SOURCE_PROFILE": True,
        "NEX_AG_AE_ARTIFACT_BASE_URL": True,
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": True,
        "NEX_AG_TO_NEX_AE_API_SERVICE_TOKEN": True,
        "NEX_SERVICE_TOKEN": True,
    }
    with pytest.raises(ValueError, match="NEX_AG_AE_ARTIFACT_SERVICE_TOKEN"):
        audit.assert_evidence_redacted("service-token-0641", env)
    with pytest.raises(ValueError, match="Sensitive value leaked"):
        audit.assert_evidence_redacted(
            "external_notification_secret='notify-secret-0641'",
            {},
        )


def test_ag_operator_review_case_action_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = audit.run_ag_operator_review_case_action_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "ag_operator_review_case_action_boundary_failed"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["s64_closed_baseline_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ag_operator_review_case_action_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    _copy_required_paths(tmp_path)
    target = tmp_path / "services" / "nex-ag" / "nex_ag" / "operations.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "operator_review_attention_required.v1",
            "operator_review_attention_case_required.v1",
        ),
        encoding="utf-8",
    )

    evidence = audit.run_ag_operator_review_case_action_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["operations_issue_surface_present"] is False
    failed = [
        item
        for item in evidence["source_tokens"]
        if item["token_id"] == "issue_rule_id"
    ]
    assert failed == [
        {
            "group": "operations_issue_surface",
            "token_id": "issue_rule_id",
            "path": "services/nex-ag/nex_ag/operations.py",
            "purpose": "S65 case intake should consume the existing operator-review issue signal.",
            "present": False,
        }
    ]


def test_ag_operator_review_case_action_boundary_table_name_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_table_name_results",
        lambda: [
            {
                "table_name": "ag_operator_review_case_action_transition_history",
                "length": 49,
                "max_length": 30,
                "within_limit": False,
            }
        ],
    )

    evidence = audit.run_ag_operator_review_case_action_boundary_audit({})

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_name_lengths_safe"] is False
    assert {
        item["category"] for item in evidence["issues"]
    } >= {"table_name_too_long"}


def test_ag_operator_review_case_action_boundary_helpers_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ag_operator_review_case_action_boundary_audit({})

    audit.write_audit_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    assert audit._present_count([{"present": True}, {"present": False}, {}]) == 1
    assert audit._present_count(None) == 0
    assert audit._grouped_token_status(
        [
            {"group": "ready", "present": True},
            {"group": "ready", "present": True},
            {"group": "blocked", "present": False},
        ]
    ) == {"blocked": False, "ready": True}
    assert audit._read_text(ROOT / "docs" / "README.md")
    assert audit._read_text(tmp_path / "missing.md") == ""

    pass_evidence = {
        "status": "PASS",
        "case_action_boundary": {"boundary": audit.CASE_ACTION_BOUNDARY},
        "paths": [],
        "source_tokens": [],
        "table_name_results": [],
        "checks": {},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_case_action_boundary_audit",
        lambda: pass_evidence,
    )
    assert audit.main(["--summary"]) == 0
    assert "ag_operator_review_case_action_boundary_audit=pass" in (
        capsys.readouterr().out
    )
    cli_output = tmp_path / "cli" / "evidence.json"
    assert audit.main(["--output", str(cli_output)]) == 0
    assert json.loads(cli_output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    fail_evidence = {
        "status": "FAIL",
        "failure_code": "ag_operator_review_case_action_boundary_failed",
        "checks": {"required_paths_present": False},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_case_action_boundary_audit",
        lambda: fail_evidence,
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_ag_operator_review_case_action_boundary_script_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ag_operator_review_case_action_boundary_audit.py", "--summary"],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            str(ROOT / "scripts" / "smoke" / "run_ag_operator_review_case_action_boundary_audit.py"),
            run_name="__main__",
        )

    assert exc_info.value.code == 0
    assert "ag_operator_review_case_action_boundary_audit=pass" in (
        capsys.readouterr().out
    )


def _copy_required_paths(tmp_path: Path) -> None:
    for required in audit.REQUIRED_PATHS:
        source = ROOT / required.relative_path
        target = tmp_path / required.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
