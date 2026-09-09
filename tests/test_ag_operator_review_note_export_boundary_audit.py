from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import run_ag_operator_review_note_export_boundary_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AG_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0621@127.0.0.1:5432/nex_ag_dev"
        ),
        "NEX_AG_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0621@127.0.0.1:5432/nex_ag_test"
        ),
        "NEX_AG_OPERATIONS_SOURCE_MODE": "postgres",
        "NEX_AG_OPERATIONS_SOURCE_PROFILE": "test",
        "NEX_AG_AE_ARTIFACT_BASE_URL": "http://127.0.0.1:8102/private",
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": "service-token-0621",
        "NEX_AG_TO_NEX_AE_API_SERVICE_TOKEN": "service-token-ae-0621",
        "NEX_SERVICE_TOKEN": "service-token-shared-0621",
    }


def test_ag_operator_review_note_export_boundary_passes_repo() -> None:
    evidence = audit.run_ag_operator_review_note_export_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0621"
    assert evidence["surface"] == audit.S63_SURFACE
    assert evidence["operator_review_boundary"] == {
        "system_of_record": "nex-ag",
        "persistence_owner": "nex-ag",
        "source_record_owners": ["nex-ae-api", "nex-cx", "nex-mo", "nex-oa"],
        "boundary": "ag_owned_operator_review_notes_redacted_exports",
        "create_table_in_slice_0621": False,
        "first_schema_slice": "Slice_0622",
        "candidate_note_table": "ag_op_notes",
        "candidate_note_table_length": 11,
        "candidate_export_table": "ag_ev_exports",
        "candidate_export_table_length": 13,
        "max_table_name_length": 30,
        "target_reference_columns": [
            "target_service",
            "target_kind",
            "target_id",
            "trace_id",
            "request_id",
        ],
        "target_reference_columns_indexable": True,
        "note_storage_shape": "hash_and_short_preview_only",
        "note_preview_max_chars": 240,
        "export_storage_shape": "redacted_manifest_plus_hashes",
        "export_payload_body_storage_deferred": True,
        "allowed_ag_writes": [
            "operator_note_metadata",
            "operator_note_hash",
            "operator_note_preview",
            "redacted_evidence_manifest",
            "export_request_metadata",
            "export_hashes",
        ],
        "forbidden_write_payloads": [
            "raw_operator_note_text",
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
        ],
        "ag_may_write_own_review_records": True,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
        "oa_admin_claim_required": True,
        "idempotency_key_required_for_create": True,
        "test_profile_postgres_smoke_required": True,
    }
    assert evidence["refactoring_checkpoint"] == {
        "separate_operator_review_records_from_source_projections": True,
        "keep_ag_owned_write_models_in_nex_ag": True,
        "keep_source_records_read_only_through_service_apis": True,
        "split_target_reference_into_indexable_columns": True,
        "add_repository_before_route_wiring": True,
        "store_free_text_as_hash_and_short_preview_only": True,
        "store_exports_as_redacted_manifest_plus_hashes": True,
        "defer_export_payload_file_storage_until_manifest_is_stable": True,
        "require_oa_admin_claims_for_create_routes": True,
        "require_idempotency_keys_for_mutating_routes": True,
        "require_real_nex_ag_test_db_smoke_before_dashboard_write_enablement": True,
        "do_not_mutate_ae_cx_mo_oa_records": True,
        "do_not_copy_raw_prompts_source_docs_provider_payloads_or_storage_paths": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_name_results"])
    assert evidence["next_slices"] == [
        "Slice_0622",
        "Slice_0623",
        "Slice_0624",
        "Slice_0625",
        "Slice_0626",
        "Slice_0627",
        "Slice_0628",
        "Slice_0629",
        "Slice_0630",
    ]

    summary = audit.summary_line(evidence)
    assert "ag_operator_review_note_export_boundary_audit=pass" in summary
    assert "note_table=ag_op_notes" in summary
    assert "export_table=ag_ev_exports" in summary
    assert "next=Slice_0622" in summary


def test_ag_operator_review_note_export_boundary_redacts_env() -> None:
    env = protected_env()

    evidence = audit.run_ag_operator_review_note_export_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0621" not in serialized
    assert "service-token-0621" not in serialized
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


def test_ag_operator_review_note_export_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = audit.run_ag_operator_review_note_export_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "ag_operator_review_note_export_boundary_failed"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["quality_docs_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ag_operator_review_note_export_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    _copy_required_paths(tmp_path)
    target = (
        tmp_path
        / "services"
        / "nex-ag"
        / "nex_ag"
        / "generation_quality_disposition.py"
    )
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "operator_note_hash",
            "operator_note_digest",
        ),
        encoding="utf-8",
    )

    evidence = audit.run_ag_operator_review_note_export_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["ag_existing_owned_write_pattern_present"] is False
    failed = [
        item
        for item in evidence["source_tokens"]
        if item["token_id"] == "operator_note_hash"
    ]
    assert failed == [
        {
            "group": "ag_existing_owned_write_pattern",
            "token_id": "operator_note_hash",
            "path": "services/nex-ag/nex_ag/generation_quality_disposition.py",
            "purpose": "Free-text operator notes should store a hash for correlation.",
            "present": False,
        }
    ]


def test_ag_operator_review_note_export_boundary_table_name_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_table_name_results",
        lambda: [
            {
                "table_name": "ag_operator_review_note_and_evidence_export_records",
                "length": 51,
                "max_length": 30,
                "within_limit": False,
            }
        ],
    )

    evidence = audit.run_ag_operator_review_note_export_boundary_audit({})

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_name_lengths_safe"] is False
    assert {
        item["category"] for item in evidence["issues"]
    } >= {"table_name_too_long"}


def test_ag_operator_review_note_export_boundary_helpers_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ag_operator_review_note_export_boundary_audit({})

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
    assert audit._table_name_results() == [
        {
            "table_name": "ag_op_notes",
            "length": 11,
            "max_length": 30,
            "within_limit": True,
        },
        {
            "table_name": "ag_ev_exports",
            "length": 13,
            "max_length": 30,
            "within_limit": True,
        },
    ]

    with pytest.raises(ValueError, match="NEX_AG_TEST_DATABASE_URL"):
        audit.assert_evidence_redacted(
            protected_env()["NEX_AG_TEST_DATABASE_URL"],
            protected_env(),
        )
    for leaked in (
        "db=postgresql://user:pass@host/db",
        "Authorization: Bearer token",
        "provider=ed6@c496em",
        "password=nuri1004",
        "/data/nex-platform/ag/export.json",
        "idempotency_key=unsafe",
        "raw_operator_note_text='full note'",
        "raw_prompt_text='prompt'",
        "raw_generation_output_text='answer'",
        "raw_source_document_text='source'",
        "raw_provider_payload={}",
        "source_service_record_blob={}",
        "artifact_binary_payload=YWJjZGVmZ2hpamtsbW5vcA==",
    ):
        with pytest.raises(ValueError, match="Sensitive value leaked"):
            audit.assert_evidence_redacted(leaked, {})

    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_note_export_boundary_audit",
        lambda: evidence,
    )
    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "ag_operator_review_note_export_boundary_audit=pass" in (
        capsys.readouterr().out
    )

    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_note_export_boundary_audit",
        lambda: {
            "status": "FAIL",
            "failure_code": "test",
            "checks": {"required_paths_present": False},
        },
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def _copy_required_paths(tmp_path: Path) -> None:
    for required in audit.REQUIRED_PATHS:
        source = ROOT / required.relative_path
        target = tmp_path / required.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
