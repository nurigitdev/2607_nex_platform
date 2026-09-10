from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import run_ag_operator_review_workbench_boundary_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AG_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0631@127.0.0.1:5432/nex_ag_dev"
        ),
        "NEX_AG_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0631@127.0.0.1:5432/nex_ag_test"
        ),
        "NEX_AG_OPERATIONS_SOURCE_MODE": "postgres",
        "NEX_AG_OPERATIONS_SOURCE_PROFILE": "test",
        "NEX_AG_AE_ARTIFACT_BASE_URL": "http://127.0.0.1:8102/private",
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": "service-token-0631",
        "NEX_AG_TO_NEX_AE_API_SERVICE_TOKEN": "service-token-ae-0631",
        "NEX_SERVICE_TOKEN": "service-token-shared-0631",
    }


def test_ag_operator_review_workbench_boundary_passes_repo() -> None:
    evidence = audit.run_ag_operator_review_workbench_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0631"
    assert evidence["surface"] == audit.S64_SURFACE
    assert evidence["workbench_boundary"] == {
        "system_of_record": "nex-ag",
        "projection_owner": "nex-ag",
        "mutation_owner": "nex-ag",
        "boundary": "ag_owned_operator_review_workbench_projection",
        "create_table_in_slice_0631": False,
        "first_read_model_slice": "Slice_0632",
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
        "workbench_inputs": [
            "operator_note_hash_preview_records",
            "redacted_evidence_export_manifest_records",
            "operations_dashboard_projection",
            "operations_issue_candidate_projection",
        ],
        "allowed_workbench_reads": [
            "ag_operator_note_records",
            "ag_redacted_evidence_export_records",
            "safe_operations_projection_records",
        ],
        "allowed_workbench_writes": [
            "none_new_in_slice_0631",
            "existing_note_mutations_only_through_operator_review_routes",
            "existing_export_mutations_only_through_operator_review_routes",
        ],
        "forbidden_workbench_payloads": [
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
        ],
        "dashboard_integration_policy": "read_model_before_dashboard_wiring",
        "issue_candidate_policy": "derive_from_safe_counts_and_status_only",
        "operator_auth_policy": "service_token_or_admin_user_claim_required",
        "postgres_smoke_required_before_operational_enablement": True,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
    }
    assert evidence["refactoring_checkpoint"] == {
        "keep_workbench_projection_separate_from_mutation_services": True,
        "reuse_existing_note_and_export_stores_before_new_persistence": True,
        "avoid_new_table_in_slice_0631": True,
        "keep_source_service_records_read_only": True,
        "group_by_target_reference_before_dashboard_wiring": True,
        "attach_rollups_before_issue_candidates": True,
        "store_and_project_hash_preview_or_redacted_manifest_only": True,
        "do_not_project_raw_prompts_source_docs_provider_payloads_or_paths": True,
        "require_admin_or_service_claims_for_workbench_reads": True,
        "require_real_nex_ag_test_db_smoke_before_dashboard_section_closure": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_name_results"])
    assert evidence["next_slices"] == [
        "Slice_0632",
        "Slice_0633",
        "Slice_0634",
        "Slice_0635",
        "Slice_0636",
        "Slice_0637",
        "Slice_0638",
        "Slice_0639",
        "Slice_0640",
    ]

    summary = audit.summary_line(evidence)
    assert "ag_operator_review_workbench_boundary_audit=pass" in summary
    assert "boundary=ag_owned_operator_review_workbench_projection" in summary
    assert "note_table=ag_op_notes" in summary
    assert "export_table=ag_ev_exports" in summary
    assert "next=Slice_0632" in summary


def test_ag_operator_review_workbench_boundary_redacts_env() -> None:
    env = protected_env()

    evidence = audit.run_ag_operator_review_workbench_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0631" not in serialized
    assert "service-token-0631" not in serialized
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
        audit.assert_evidence_redacted("service-token-0631", env)
    with pytest.raises(ValueError, match="Sensitive value leaked"):
        audit.assert_evidence_redacted(
            "postgresql+psycopg://nex_ag_user:secret@127.0.0.1:5432/db",
            {},
        )


def test_ag_operator_review_workbench_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = audit.run_ag_operator_review_workbench_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "ag_operator_review_workbench_boundary_failed"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["operator_review_runtime_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ag_operator_review_workbench_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    _copy_required_paths(tmp_path)
    target = tmp_path / "services" / "nex-ag" / "nex_ag" / "operations.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "build_operations_issue_candidate_projection",
            "build_operations_attention_candidate_projection",
        ),
        encoding="utf-8",
    )

    evidence = audit.run_ag_operator_review_workbench_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["operations_projection_surface_present"] is False
    failed = [
        item
        for item in evidence["source_tokens"]
        if item["token_id"] == "issue_candidate_projection"
    ]
    assert failed == [
        {
            "group": "operations_projection_surface",
            "token_id": "issue_candidate_projection",
            "path": "services/nex-ag/nex_ag/operations.py",
            "purpose": "Workbench attention states should later flow into issue candidates.",
            "present": False,
        }
    ]


def test_ag_operator_review_workbench_boundary_table_name_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_table_name_results",
        lambda: [
            {
                "table_name": "ag_operator_review_workbench_projection_records",
                "length": 45,
                "max_length": 30,
                "within_limit": False,
            }
        ],
    )

    evidence = audit.run_ag_operator_review_workbench_boundary_audit({})

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_name_lengths_safe"] is False
    assert {
        item["category"] for item in evidence["issues"]
    } >= {"table_name_too_long"}


def test_ag_operator_review_workbench_boundary_helpers_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ag_operator_review_workbench_boundary_audit({})

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
        "paths": [],
        "source_tokens": [],
        "table_name_results": [],
        "checks": {},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_workbench_boundary_audit",
        lambda: pass_evidence,
    )
    assert audit.main(["--summary"]) == 0
    assert "ag_operator_review_workbench_boundary_audit=pass" in (
        capsys.readouterr().out
    )
    cli_output = tmp_path / "cli" / "evidence.json"
    assert audit.main(["--output", str(cli_output)]) == 0
    assert json.loads(cli_output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    fail_evidence = {
        "status": "FAIL",
        "failure_code": "ag_operator_review_workbench_boundary_failed",
        "checks": {"required_paths_present": False},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_workbench_boundary_audit",
        lambda: fail_evidence,
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def _copy_required_paths(tmp_path: Path) -> None:
    for required in audit.REQUIRED_PATHS:
        source = ROOT / required.relative_path
        target = tmp_path / required.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
