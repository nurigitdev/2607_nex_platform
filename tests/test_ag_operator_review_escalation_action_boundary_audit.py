from __future__ import annotations

import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest

import run_ag_operator_review_escalation_action_boundary_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AG_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0691@127.0.0.1:5432/nex_ag_dev"
        ),
        "NEX_AG_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0691@127.0.0.1:5432/nex_ag_test"
        ),
        "NEX_AG_OPERATIONS_SOURCE_MODE": "postgres",
        "NEX_AG_OPERATIONS_SOURCE_PROFILE": "test",
        "NEX_AG_NOTIFICATION_WEBHOOK_URL": "https://notify.invalid/hook/secret-0691",
        "NEX_AG_NOTIFICATION_SERVICE_TOKEN": "notify-token-shared-0691",
        "NEX_AG_EXTERNAL_INCIDENT_BASE_URL": "https://incident.invalid/api",
        "NEX_AG_EXTERNAL_INCIDENT_TOKEN": "incident-token-shared-0691",
        "NEX_SERVICE_TOKEN": "service-token-shared-0691",
    }


def test_ag_operator_review_escalation_action_boundary_passes_repo() -> None:
    evidence = audit.run_ag_operator_review_escalation_action_boundary_audit({})
    boundary = evidence["escalation_action_boundary"]

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0691"
    assert evidence["surface"] == audit.S70_SURFACE
    assert boundary["boundary"] == audit.ESCALATION_ACTION_BOUNDARY
    assert boundary["create_table_in_slice_0691"] is False
    assert boundary["first_persistence_slice"] == "Slice_0692"
    assert boundary["planned_escalation_table"] == "ag_op_escalations"
    assert boundary["source_tables"] == [
        {"table_name": "ag_op_cases", "role": "case_state_source_of_record"},
        {
            "table_name": "service_operational_events",
            "role": "safe_action_history_and_timeline_source",
        },
    ]
    assert boundary["planned_owned_tables"] == [
        {
            "table_name": "ag_op_escalations",
            "role": "operator_acknowledgement_snooze_and_resolution_state",
            "first_slice": "Slice_0692",
        }
    ]
    assert boundary["notification_delivery"] == "still_deferred"
    assert boundary["external_incident_sync"] == "still_deferred"
    assert boundary["ag_may_send_outbound_notifications_in_s70"] is False
    assert boundary["ag_may_sync_external_incident_systems_in_s70"] is False
    assert boundary["cross_service_database_write_allowed"] is False
    assert evidence["refactoring_checkpoint"] == {
        "reuse_s69_escalation_projection_as_candidate_input": True,
        "reuse_existing_case_action_state_machine_for_case_status_changes": True,
        "persist_only_operator_acknowledgement_snooze_and_resolution_state": True,
        "keep_raw_comments_as_hash_and_short_preview_only": True,
        "hash_idempotency_keys_before_storage_or_projection": True,
        "keep_notification_delivery_deferred_in_s70": True,
        "keep_external_incident_sync_deferred_in_s70": True,
        "record_safe_action_history_in_operational_events": True,
        "require_real_nex_ag_test_db_smoke_before_s70_closure": True,
        "keep_table_names_short": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_name_results"])
    assert evidence["next_slices"] == [
        "Slice_0692",
        "Slice_0693",
        "Slice_0694",
        "Slice_0695",
        "Slice_0696",
        "Slice_0697",
        "Slice_0698",
        "Slice_0699",
        "Slice_0700",
    ]

    summary = audit.summary_line(evidence)
    assert "ag_operator_review_escalation_action_boundary_audit=pass" in summary
    assert f"boundary={audit.ESCALATION_ACTION_BOUNDARY}" in summary
    assert "persistence=planned_ag_owned_ack_state" in summary
    assert "notification=deferred" in summary
    assert "next=Slice_0692" in summary


def test_ag_operator_review_escalation_action_boundary_redacts_env() -> None:
    env = protected_env()

    evidence = audit.run_ag_operator_review_escalation_action_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0691" not in serialized
    assert "notify-token-shared-0691" not in serialized
    assert "incident-token-shared-0691" not in serialized
    assert "service-token-shared-0691" not in serialized
    assert env["NEX_AG_TEST_DATABASE_URL"] not in serialized
    assert evidence["protected_env"] == {
        "NEX_AG_DATABASE_URL": True,
        "NEX_AG_TEST_DATABASE_URL": True,
        "NEX_AG_OPERATIONS_SOURCE_MODE": True,
        "NEX_AG_OPERATIONS_SOURCE_PROFILE": True,
        "NEX_AG_NOTIFICATION_WEBHOOK_URL": True,
        "NEX_AG_NOTIFICATION_SERVICE_TOKEN": True,
        "NEX_AG_EXTERNAL_INCIDENT_BASE_URL": True,
        "NEX_AG_EXTERNAL_INCIDENT_TOKEN": True,
        "NEX_SERVICE_TOKEN": True,
    }
    with pytest.raises(ValueError, match="NEX_AG_EXTERNAL_INCIDENT_TOKEN"):
        audit.assert_evidence_redacted("incident-token-shared-0691", env)
    with pytest.raises(ValueError, match="Sensitive value leaked"):
        audit.assert_evidence_redacted(
            "raw_notification_payload={'secret':'do-not-emit'}",
            {},
        )


def test_ag_operator_review_escalation_action_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = audit.run_ag_operator_review_escalation_action_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_escalation_action_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["s69_closed_baseline_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ag_operator_review_escalation_action_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    _copy_required_paths(tmp_path)
    target = tmp_path / "services" / "nex-ag" / "nex_ag" / "operator_review_cases.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "def build_operator_review_case_escalation_projection",
            "def build_operator_review_case_escalation_hidden",
        ),
        encoding="utf-8",
    )

    evidence = audit.run_ag_operator_review_escalation_action_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["s69_escalation_runtime_present"] is False
    failed = [
        item
        for item in evidence["source_tokens"]
        if item["token_id"] == "escalation_projection"
    ]
    assert failed == [
        {
            "group": "s69_escalation_runtime",
            "token_id": "escalation_projection",
            "path": "services/nex-ag/nex_ag/operator_review_cases.py",
            "purpose": "S70 overlays action state on the existing escalation projection.",
            "present": False,
        }
    ]


def test_ag_operator_review_escalation_action_boundary_table_name_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_table_name_results",
        lambda: [
            {
                "table_name": "ag_operator_review_escalation_acknowledgement_history",
                "length": 55,
                "max_length": 30,
                "within_limit": False,
            }
        ],
    )

    evidence = audit.run_ag_operator_review_escalation_action_boundary_audit({})

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_name_lengths_safe"] is False
    assert {item["category"] for item in evidence["issues"]} >= {"table_name_too_long"}


def test_ag_operator_review_escalation_action_boundary_helpers_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ag_operator_review_escalation_action_boundary_audit({})

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
        "escalation_action_boundary": {
            "boundary": audit.ESCALATION_ACTION_BOUNDARY
        },
        "paths": [],
        "source_tokens": [],
        "table_name_results": [],
        "checks": {},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_escalation_action_boundary_audit",
        lambda: pass_evidence,
    )
    assert audit.main(["--summary"]) == 0
    assert "ag_operator_review_escalation_action_boundary_audit=pass" in (
        capsys.readouterr().out
    )
    cli_output = tmp_path / "cli" / "evidence.json"
    assert audit.main(["--output", str(cli_output)]) == 0
    assert json.loads(cli_output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    fail_evidence = {
        "status": "FAIL",
        "failure_code": "ag_operator_review_escalation_action_boundary_failed",
        "checks": {"required_paths_present": False},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_escalation_action_boundary_audit",
        lambda: fail_evidence,
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_ag_operator_review_escalation_action_boundary_script_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_ag_operator_review_escalation_action_boundary_audit.py",
            "--summary",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            str(
                ROOT
                / "scripts"
                / "smoke"
                / "run_ag_operator_review_escalation_action_boundary_audit.py"
            ),
            run_name="__main__",
        )

    assert exc_info.value.code == 0
    assert "ag_operator_review_escalation_action_boundary_audit=pass" in (
        capsys.readouterr().out
    )


def _copy_required_paths(tmp_path: Path) -> None:
    for required in audit.REQUIRED_PATHS:
        source = ROOT / required.relative_path
        target = tmp_path / required.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
