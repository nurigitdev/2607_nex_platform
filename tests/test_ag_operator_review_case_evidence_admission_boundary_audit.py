from __future__ import annotations

import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest

import run_ag_operator_review_case_evidence_admission_boundary_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AG_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0661@127.0.0.1:5432/nex_ag_dev"
        ),
        "NEX_AG_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0661@127.0.0.1:5432/nex_ag_test"
        ),
        "NEX_AG_OPERATIONS_SOURCE_MODE": "postgres",
        "NEX_AG_OPERATIONS_SOURCE_PROFILE": "test",
        "NEX_AG_AE_ARTIFACT_BASE_URL": "http://127.0.0.1:8102/private",
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": "service-token-0661",
        "NEX_AG_TO_NEX_AE_API_SERVICE_TOKEN": "service-token-ae-0661",
        "NEX_SERVICE_TOKEN": "service-token-shared-0661",
    }


def test_ag_operator_review_case_evidence_admission_boundary_passes_repo() -> None:
    evidence = audit.run_ag_operator_review_case_evidence_admission_boundary_audit({})
    boundary = evidence["case_evidence_admission_boundary"]

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0661"
    assert evidence["surface"] == audit.S67_SURFACE
    assert boundary["boundary"] == audit.CASE_EVIDENCE_ADMISSION_BOUNDARY
    assert boundary["create_table_in_slice_0661"] is False
    assert boundary["first_read_model_slice"] == "Slice_0662"
    assert boundary["source_tables"] == [
        {"table_name": "ag_op_cases", "role": "case_context_source"},
        {"table_name": "ag_op_notes", "role": "operator_note_link_source"},
        {
            "table_name": "ag_ev_exports",
            "role": "redacted_evidence_export_link_source",
        },
        {
            "table_name": "service_operational_events",
            "role": "safe_event_correlation_source",
        },
    ]
    assert boundary["planned_read_model_surfaces"] == [
        "/admin/v1/operator-review/cases/{case_id}/evidence-links",
        "/admin/v1/operator-review/cases/{case_id}/action-admission",
    ]
    assert boundary["action_admission_is_preflight_only"] is True
    assert boundary["case_action_mutation_route_remains_source_of_truth"] is True
    assert boundary["cross_service_database_write_allowed"] is False
    assert evidence["refactoring_checkpoint"] == {
        "reuse_ag_op_cases_for_case_context": True,
        "reuse_ag_op_notes_for_note_links": True,
        "reuse_ag_ev_exports_for_redacted_export_links": True,
        "reuse_service_operational_events_for_safe_correlation": True,
        "avoid_new_evidence_link_table_until_queries_are_insufficient": True,
        "derive_action_admission_from_case_action_state_machine": True,
        "keep_action_mutation_route_as_final_authority": True,
        "link_notes_and_exports_by_safe_refs_hashes_and_previews_only": True,
        "store_and_return_free_text_as_hash_and_short_preview_only": True,
        "require_real_nex_ag_test_db_smoke_before_s67_closure": True,
        "do_not_copy_raw_prompts_source_docs_provider_payloads_or_storage_paths": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_name_results"])
    assert evidence["next_slices"] == [
        "Slice_0662",
        "Slice_0663",
        "Slice_0664",
        "Slice_0665",
        "Slice_0666",
        "Slice_0667",
        "Slice_0668",
        "Slice_0669",
        "Slice_0670",
    ]

    summary = audit.summary_line(evidence)
    assert "ag_operator_review_case_evidence_admission_boundary_audit=pass" in summary
    assert f"boundary={audit.CASE_EVIDENCE_ADMISSION_BOUNDARY}" in summary
    assert "evidence=ag_op_notes,ag_ev_exports" in summary
    assert "admission=preflight" in summary
    assert "next=Slice_0662" in summary


def test_ag_operator_review_case_evidence_admission_boundary_redacts_env() -> None:
    env = protected_env()

    evidence = audit.run_ag_operator_review_case_evidence_admission_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0661" not in serialized
    assert "service-token-0661" not in serialized
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
        audit.assert_evidence_redacted("service-token-0661", env)
    with pytest.raises(ValueError, match="Sensitive value leaked"):
        audit.assert_evidence_redacted(
            "raw_evidence_body='full redacted evidence must not leak'",
            {},
        )


def test_ag_operator_review_case_evidence_admission_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = audit.run_ag_operator_review_case_evidence_admission_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_case_evidence_admission_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["s66_closed_baseline_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ag_operator_review_case_evidence_admission_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    _copy_required_paths(tmp_path)
    target = tmp_path / "services" / "nex-ag" / "nex_ag" / "operator_review_cases.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "CASE_ACTION_ALLOWED_FROM",
            "CASE_ACTION_BLOCKED_FROM",
        ),
        encoding="utf-8",
    )

    evidence = audit.run_ag_operator_review_case_evidence_admission_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["case_runtime_present"] is False
    failed = [
        item
        for item in evidence["source_tokens"]
        if item["token_id"] == "action_state_machine"
    ]
    assert failed == [
        {
            "group": "case_runtime",
            "token_id": "action_state_machine",
            "path": "services/nex-ag/nex_ag/operator_review_cases.py",
            "purpose": "Action admission must use the same state-machine source as mutations.",
            "present": False,
        }
    ]


def test_ag_operator_review_case_evidence_admission_boundary_table_name_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_table_name_results",
        lambda: [
            {
                "table_name": "ag_operator_review_case_evidence_admission_snapshots",
                "length": 53,
                "max_length": 30,
                "within_limit": False,
            }
        ],
    )

    evidence = audit.run_ag_operator_review_case_evidence_admission_boundary_audit({})

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_name_lengths_safe"] is False
    assert {
        item["category"] for item in evidence["issues"]
    } >= {"table_name_too_long"}


def test_ag_operator_review_case_evidence_admission_boundary_helpers_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ag_operator_review_case_evidence_admission_boundary_audit({})

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
        "case_evidence_admission_boundary": {
            "boundary": audit.CASE_EVIDENCE_ADMISSION_BOUNDARY
        },
        "paths": [],
        "source_tokens": [],
        "table_name_results": [],
        "checks": {},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_case_evidence_admission_boundary_audit",
        lambda: pass_evidence,
    )
    assert audit.main(["--summary"]) == 0
    assert "ag_operator_review_case_evidence_admission_boundary_audit=pass" in (
        capsys.readouterr().out
    )
    cli_output = tmp_path / "cli" / "evidence.json"
    assert audit.main(["--output", str(cli_output)]) == 0
    assert json.loads(cli_output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    fail_evidence = {
        "status": "FAIL",
        "failure_code": "ag_operator_review_case_evidence_admission_boundary_failed",
        "checks": {"required_paths_present": False},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_case_evidence_admission_boundary_audit",
        lambda: fail_evidence,
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_ag_operator_review_case_evidence_admission_boundary_script_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_ag_operator_review_case_evidence_admission_boundary_audit.py",
            "--summary",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            str(
                ROOT
                / "scripts"
                / "smoke"
                / "run_ag_operator_review_case_evidence_admission_boundary_audit.py"
            ),
            run_name="__main__",
        )

    assert exc_info.value.code == 0
    assert "ag_operator_review_case_evidence_admission_boundary_audit=pass" in (
        capsys.readouterr().out
    )


def _copy_required_paths(tmp_path: Path) -> None:
    for required in audit.REQUIRED_PATHS:
        source = ROOT / required.relative_path
        target = tmp_path / required.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
