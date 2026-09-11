from __future__ import annotations

import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest

import run_ag_operator_review_case_workbench_boundary_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AG_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0651@127.0.0.1:5432/nex_ag_dev"
        ),
        "NEX_AG_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0651@127.0.0.1:5432/nex_ag_test"
        ),
        "NEX_AG_OPERATIONS_SOURCE_MODE": "postgres",
        "NEX_AG_OPERATIONS_SOURCE_PROFILE": "test",
        "NEX_AG_AE_ARTIFACT_BASE_URL": "http://127.0.0.1:8102/private",
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": "service-token-0651",
        "NEX_AG_TO_NEX_AE_API_SERVICE_TOKEN": "service-token-ae-0651",
        "NEX_SERVICE_TOKEN": "service-token-shared-0651",
    }


def test_ag_operator_review_case_workbench_boundary_passes_repo() -> None:
    evidence = audit.run_ag_operator_review_case_workbench_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0651"
    assert evidence["surface"] == audit.S66_SURFACE
    assert evidence["case_workbench_boundary"] == {
        "system_of_record": "nex-ag",
        "projection_owner": "nex-ag",
        "boundary": "ag_owned_operator_review_case_workbench_projection",
        "create_table_in_slice_0651": False,
        "first_read_model_slice": "Slice_0652",
        "case_queue_source_table": "ag_op_cases",
        "case_queue_source_table_length": 11,
        "timeline_source_table": "service_operational_events",
        "timeline_source_table_length": 26,
        "action_history_policy": "operational_events_first_no_action_table_in_s66",
        "source_tables": [
            {"table_name": "ag_op_cases", "role": "case_queue_source"},
            {
                "table_name": "service_operational_events",
                "role": "case_action_timeline_source",
            },
            {"table_name": "ag_op_notes", "role": "operator_note_metadata"},
            {
                "table_name": "ag_ev_exports",
                "role": "redacted_evidence_export_metadata",
            },
        ],
        "read_model_surfaces": [
            "/admin/v1/operator-review/cases",
            "/admin/v1/operator-review/cases/{case_id}",
            "/admin/v1/operator-review/cases/rollups",
            "planned:/admin/v1/operator-review/cases/queue",
            "planned:/admin/v1/operator-review/cases/{case_id}/timeline",
            "planned:/admin/v1/operator-review/cases/{case_id}/evidence-links",
            "planned:/admin/v1/operator-review/cases/{case_id}/action-admission",
        ],
        "queue_filters": [
            "case_status",
            "case_priority",
            "assignee_id",
            "target_service",
            "target_kind",
            "target_id",
            "trace_id",
            "latest_action_type",
            "attention_status",
            "updated_from",
            "updated_to",
        ],
        "timeline_event_types": [
            "ag.operator_review_case.recorded",
            "ag.operator_review_case_action.recorded",
        ],
        "evidence_link_sources": [
            "operator_review_workbench_target",
            "operator_review_note_ref",
            "redacted_evidence_export_ref",
        ],
        "allowed_payload_shape": [
            "case_id",
            "case_status",
            "case_priority",
            "target_reference",
            "operator_ref",
            "assignment_ref",
            "safe_reason_codes",
            "hashes",
            "bounded_previews",
            "redaction_flags",
            "safe_event_details",
        ],
        "forbidden_payloads": [
            "raw_operator_note_text",
            "raw_evidence_body",
            "raw_action_comment",
            "raw_resolution_text",
            "raw_prompt_text",
            "raw_generation_output_text",
            "raw_source_document_text",
            "raw_provider_payload",
            "database_url",
            "service_token",
            "provider_api_key",
            "local_storage_path",
            "artifact_binary_payload",
            "raw_idempotency_key",
        ],
        "operator_auth_policy": "service_token_or_admin_user_claim_required",
        "postgres_smoke_required_before_s66_closure": True,
        "ag_may_write_own_case_records": True,
        "case_workbench_is_read_model_first": True,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
    }
    assert evidence["refactoring_checkpoint"] == {
        "keep_case_queue_read_model_separate_from_mutation_service": True,
        "reuse_ag_op_cases_instead_of_new_queue_table": True,
        "reuse_service_operational_events_for_timeline": True,
        "defer_action_history_table_until_event_queries_are_insufficient": True,
        "link_notes_and_exports_by_safe_refs_only": True,
        "keep_source_service_records_read_only": True,
        "expose_action_admission_before_new_mutations": True,
        "store_and_return_free_text_as_hash_and_short_preview_only": True,
        "require_real_nex_ag_test_db_smoke_before_s66_closure": True,
        "do_not_copy_raw_prompts_source_docs_provider_payloads_or_storage_paths": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_name_results"])
    assert evidence["next_slices"] == [
        "Slice_0652",
        "Slice_0653",
        "Slice_0654",
        "Slice_0655",
        "Slice_0656",
        "Slice_0657",
        "Slice_0658",
        "Slice_0659",
        "Slice_0660",
    ]

    summary = audit.summary_line(evidence)
    assert "ag_operator_review_case_workbench_boundary_audit=pass" in summary
    assert "boundary=ag_owned_operator_review_case_workbench_projection" in summary
    assert "case_table=ag_op_cases" in summary
    assert "timeline=service_operational_events" in summary
    assert "next=Slice_0652" in summary


def test_ag_operator_review_case_workbench_boundary_redacts_env() -> None:
    env = protected_env()

    evidence = audit.run_ag_operator_review_case_workbench_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0651" not in serialized
    assert "service-token-0651" not in serialized
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
        audit.assert_evidence_redacted("service-token-0651", env)
    with pytest.raises(ValueError, match="Sensitive value leaked"):
        audit.assert_evidence_redacted(
            "raw_action_comment='full operator action text'",
            {},
        )


def test_ag_operator_review_case_workbench_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = audit.run_ag_operator_review_case_workbench_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "ag_operator_review_case_workbench_boundary_failed"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["s65_closed_baseline_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ag_operator_review_case_workbench_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    _copy_required_paths(tmp_path)
    target = tmp_path / "services" / "nex-ag" / "nex_ag" / "operator_review_cases.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "ag.operator_review_case_action.recorded",
            "ag.operator_review_case_action.hidden",
        ),
        encoding="utf-8",
    )

    evidence = audit.run_ag_operator_review_case_workbench_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["case_runtime_present"] is False
    failed = [
        item
        for item in evidence["source_tokens"]
        if item["token_id"] == "case_action_event"
    ]
    assert failed == [
        {
            "group": "case_runtime",
            "token_id": "case_action_event",
            "path": "services/nex-ag/nex_ag/operator_review_cases.py",
            "purpose": "Timeline projection must read redaction-safe action events.",
            "present": False,
        }
    ]


def test_ag_operator_review_case_workbench_boundary_table_name_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_table_name_results",
        lambda: [
            {
                "table_name": "ag_operator_review_case_workbench_timeline_snapshots",
                "length": 52,
                "max_length": 30,
                "within_limit": False,
            }
        ],
    )

    evidence = audit.run_ag_operator_review_case_workbench_boundary_audit({})

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_name_lengths_safe"] is False
    assert {
        item["category"] for item in evidence["issues"]
    } >= {"table_name_too_long"}


def test_ag_operator_review_case_workbench_boundary_helpers_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ag_operator_review_case_workbench_boundary_audit({})

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
        "case_workbench_boundary": {"boundary": audit.CASE_WORKBENCH_BOUNDARY},
        "paths": [],
        "source_tokens": [],
        "table_name_results": [],
        "checks": {},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_case_workbench_boundary_audit",
        lambda: pass_evidence,
    )
    assert audit.main(["--summary"]) == 0
    assert "ag_operator_review_case_workbench_boundary_audit=pass" in (
        capsys.readouterr().out
    )
    cli_output = tmp_path / "cli" / "evidence.json"
    assert audit.main(["--output", str(cli_output)]) == 0
    assert json.loads(cli_output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    fail_evidence = {
        "status": "FAIL",
        "failure_code": "ag_operator_review_case_workbench_boundary_failed",
        "checks": {"required_paths_present": False},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_case_workbench_boundary_audit",
        lambda: fail_evidence,
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_ag_operator_review_case_workbench_boundary_script_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ag_operator_review_case_workbench_boundary_audit.py", "--summary"],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            str(
                ROOT
                / "scripts"
                / "smoke"
                / "run_ag_operator_review_case_workbench_boundary_audit.py"
            ),
            run_name="__main__",
        )

    assert exc_info.value.code == 0
    assert "ag_operator_review_case_workbench_boundary_audit=pass" in (
        capsys.readouterr().out
    )


def _copy_required_paths(tmp_path: Path) -> None:
    for required in audit.REQUIRED_PATHS:
        source = ROOT / required.relative_path
        target = tmp_path / required.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
