from __future__ import annotations

import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest

import run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AG_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0712@127.0.0.1:5432/nex_ag_dev"
        ),
        "NEX_AG_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret-0712@127.0.0.1:5432/nex_ag_test"
        ),
        "NEX_AG_DISPATCH_EXECUTION_WORKER_MODE": "mock",
        "NEX_AG_DISPATCH_EXECUTION_WORKER_PROFILE": "test",
        "NEX_AG_DISPATCH_EXECUTION_BATCH_LIMIT": "5",
        "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE": "mock",
        "NEX_AG_DISPATCH_EXECUTION_PROVIDER_PROFILE": "safe-profile",
        "NEX_AG_NOTIFICATION_WEBHOOK_URL": "https://notify.invalid/hook/secret-0712",
        "NEX_AG_NOTIFICATION_SERVICE_TOKEN": "notify-token-shared-0712",
        "NEX_AG_EXTERNAL_INCIDENT_BASE_URL": "https://incident.invalid/api",
        "NEX_AG_EXTERNAL_INCIDENT_TOKEN": "incident-token-shared-0712",
        "NEX_SERVICE_TOKEN": "service-token-shared-0712",
    }


def test_ag_operator_review_escalation_dispatch_execution_worker_boundary_passes_repo() -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit(
            {}
        )
    )
    boundary = evidence["execution_worker_boundary"]

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0712"
    assert evidence["surface"] == audit.S72_SURFACE
    assert boundary["boundary"] == audit.DISPATCH_EXECUTION_WORKER_BOUNDARY
    assert boundary["create_table_in_slice_0712"] is False
    assert boundary["first_worker_implementation_slice"] == "Slice_0713"
    assert boundary["source_dispatch_table"] == "ag_op_esc_dispatches"
    assert boundary["planned_owned_tables"] == []
    assert boundary["worker_mode_in_s72"] == "bounded_mock_first_only"
    assert boundary["continuous_daemon_in_0712"] is False
    assert boundary["run_once_batch_required_before_daemon"] is True
    assert boundary["explicit_operator_or_smoke_opt_in_required"] is True
    assert boundary["batch_limit_required"] is True
    assert boundary["provider_execution"] == "mock_first_only"
    assert boundary["live_provider_execution_in_s72"] is False
    assert boundary["outbound_network_delivery_in_s72"] is False
    assert boundary["ag_may_send_live_notifications_in_s72"] is False
    assert boundary["ag_may_sync_live_external_incidents_in_s72"] is False
    assert boundary["cross_service_database_write_allowed"] is False
    assert boundary["eligible_source_statuses"] == ["PENDING", "RETRY_WAIT", "FAILED"]
    assert boundary["allowed_worker_actions"] == [
        "START",
        "SUCCEED",
        "FAIL",
        "RETRY",
        "CANCEL",
    ]
    assert evidence["refactoring_checkpoint"] == {
        "reuse_s71_dispatch_outbox_as_worker_input": True,
        "separate_worker_planning_from_live_provider_delivery": True,
        "start_with_bounded_run_once_batches_before_daemon_loop": True,
        "require_explicit_opt_in_for_execution_smoke": True,
        "reuse_dispatch_state_machine_for_worker_transitions": True,
        "persist_only_safe_result_hashes_statuses_and_counters": True,
        "keep_live_notification_delivery_out_of_s72_start": True,
        "keep_live_external_incident_sync_out_of_s72_start": True,
        "keep_raw_provider_payloads_out_of_db_and_evidence": True,
        "record_safe_worker_history_in_operational_events": True,
        "avoid_new_tables_until_result_persistence_slice": True,
        "keep_table_names_short": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["within_limit"] for item in evidence["table_name_results"])
    assert evidence["next_slices"] == [
        "Slice_0713",
        "Slice_0714",
        "Slice_0715",
        "Slice_0716",
        "Slice_0717",
        "Slice_0718",
        "Slice_0719",
        "Slice_0720",
    ]

    summary = audit.summary_line(evidence)
    assert (
        "ag_operator_review_escalation_dispatch_execution_worker_boundary_audit=pass"
        in summary
    )
    assert f"boundary={audit.DISPATCH_EXECUTION_WORKER_BOUNDARY}" in summary
    assert "dispatch_table=ag_op_esc_dispatches" in summary
    assert "worker=bounded_mock_first_only" in summary
    assert "provider=mock_first_only" in summary
    assert "live_delivery=deferred" in summary
    assert "next=Slice_0713" in summary


def test_ag_operator_review_escalation_dispatch_execution_worker_boundary_redacts_env() -> None:
    env = protected_env()

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit(
            env
        )
    )
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0712" not in serialized
    assert "notify-token-shared-0712" not in serialized
    assert "incident-token-shared-0712" not in serialized
    assert "service-token-shared-0712" not in serialized
    assert env["NEX_AG_TEST_DATABASE_URL"] not in serialized
    assert evidence["protected_env"] == {
        "NEX_AG_DATABASE_URL": True,
        "NEX_AG_TEST_DATABASE_URL": True,
        "NEX_AG_DISPATCH_EXECUTION_WORKER_MODE": True,
        "NEX_AG_DISPATCH_EXECUTION_WORKER_PROFILE": True,
        "NEX_AG_DISPATCH_EXECUTION_BATCH_LIMIT": True,
        "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE": True,
        "NEX_AG_DISPATCH_EXECUTION_PROVIDER_PROFILE": True,
        "NEX_AG_NOTIFICATION_WEBHOOK_URL": True,
        "NEX_AG_NOTIFICATION_SERVICE_TOKEN": True,
        "NEX_AG_EXTERNAL_INCIDENT_BASE_URL": True,
        "NEX_AG_EXTERNAL_INCIDENT_TOKEN": True,
        "NEX_SERVICE_TOKEN": True,
    }
    with pytest.raises(ValueError, match="NEX_AG_NOTIFICATION_SERVICE_TOKEN"):
        audit.assert_evidence_redacted("notify-token-shared-0712", env)
    with pytest.raises(ValueError, match="Sensitive value leaked"):
        audit.assert_evidence_redacted(
            "raw_provider_payload={'secret':'do-not-emit'}",
            {},
        )


def test_ag_operator_review_escalation_dispatch_execution_worker_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit(
            {},
            root_dir=tmp_path,
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_escalation_dispatch_execution_worker_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["s71_closed_baseline_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ag_operator_review_escalation_dispatch_execution_worker_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    _copy_required_paths(tmp_path)
    target = tmp_path / "services" / "nex-ag" / "nex_ag" / "operator_review_cases.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "def apply_operator_review_escalation_dispatch_action",
            "def apply_operator_review_escalation_dispatch_hidden",
        ),
        encoding="utf-8",
    )

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit(
            {},
            root_dir=tmp_path,
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["dispatch_outbox_runtime_present"] is False
    failed = [
        item
        for item in evidence["source_tokens"]
        if item["token_id"] == "dispatch_state_machine"
    ]
    assert failed == [
        {
            "group": "dispatch_outbox_runtime",
            "token_id": "dispatch_state_machine",
            "path": "services/nex-ag/nex_ag/operator_review_cases.py",
            "purpose": "Worker execution must reuse the existing dispatch state machine.",
            "present": False,
        }
    ]


def test_ag_operator_review_escalation_dispatch_execution_worker_boundary_table_name_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "TABLE_NAMES_UNDER_REVIEW",
        (
            "ag_operator_review_escalation_dispatch_execution_worker_results",
        ),
    )

    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit(
            {}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_name_lengths_safe"] is False
    assert {item["category"] for item in evidence["issues"]} >= {
        "table_name_too_long"
    }


def test_ag_operator_review_escalation_dispatch_execution_worker_boundary_helpers_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = (
        audit.run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit(
            {}
        )
    )

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
        "execution_worker_boundary": {
            "boundary": audit.DISPATCH_EXECUTION_WORKER_BOUNDARY
        },
        "paths": [],
        "source_tokens": [],
        "table_name_results": [],
        "checks": {},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit",
        lambda: pass_evidence,
    )
    assert audit.main(["--summary"]) == 0
    assert (
        "ag_operator_review_escalation_dispatch_execution_worker_boundary_audit=pass"
        in capsys.readouterr().out
    )
    cli_output = tmp_path / "cli" / "evidence.json"
    assert audit.main(["--output", str(cli_output)]) == 0
    assert json.loads(cli_output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    fail_evidence = {
        "status": "FAIL",
        "failure_code": (
            "ag_operator_review_escalation_dispatch_execution_worker_boundary_failed"
        ),
        "checks": {"required_paths_present": False},
    }
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit",
        lambda: fail_evidence,
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_ag_operator_review_escalation_dispatch_execution_worker_boundary_script_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.py",
            "--summary",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            str(
                ROOT
                / "scripts"
                / "smoke"
                / "run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.py"
            ),
            run_name="__main__",
        )

    assert exc_info.value.code == 0
    assert (
        "ag_operator_review_escalation_dispatch_execution_worker_boundary_audit=pass"
        in capsys.readouterr().out
    )


def _copy_required_paths(tmp_path: Path) -> None:
    for required in audit.REQUIRED_PATHS:
        source = ROOT / required.relative_path
        target = tmp_path / required.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
