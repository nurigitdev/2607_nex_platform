from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import run_ae_operator_control_execution_worker_boundary_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0601@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_AE_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0601@127.0.0.1:5432/nex_ae_dev"
        ),
        "NEX_AE_OPERATOR_CONTROL_EXECUTION_WORKER_SMOKE": "1",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_SMOKE": "1",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_READ_MODEL_POSTGRES_SMOKE": "1",
        "NEX_AG_AE_ARTIFACT_BASE_URL": "http://127.0.0.1:8102/private",
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": "service-token-0601",
        "NEX_SERVICE_TOKEN": "service-token-shared-0601",
    }


def test_ae_operator_control_execution_worker_boundary_audit_passes_repo() -> None:
    evidence = audit.run_ae_operator_control_execution_worker_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0601"
    assert evidence["surface"] == audit.S61_SURFACE
    assert evidence["worker_boundary"] == {
        "artifact_system_of_record": "nex-ae-api",
        "operator_control_execution_owner": "nex-ae-api",
        "worker_execution_owner": "nex-ae-api",
        "worker_state_persistence_owner": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "operator_dispatch_owner": "nex-ag",
        "worker_boundary": "ae_owned_bounded_fake_dry_run_worker_test_profile_only",
        "default_worker_mode": "blocked_until_worker_contract",
        "first_worker_mode": "fake_dry_run_supervisor_persistent_dispatch_worker",
        "source_execution_state_required": True,
        "source_execution_state_status_required": "ADMITTED",
        "uses_s60_execution_request_contract": True,
        "uses_s60_execution_state_machine": True,
        "uses_existing_supervisor_runner": True,
        "uses_fake_supervisor_adapter_first": True,
        "persists_execution_state": True,
        "persists_execution_transition": True,
        "persists_supervisor_result_metadata": True,
        "restart_semantics": "stop_then_start_with_distinct_persisted_results",
        "operator_subject_required": True,
        "idempotency_key_required": True,
        "operator_reason_required": True,
        "operator_approval_required_for_start_restart": True,
        "test_profile_required": True,
        "explicit_opt_in_required_for_start_restart": True,
        "bounded_max_cycles_required": True,
        "admitted_to_executing_transition_required": True,
        "executing_to_terminal_transition_required": True,
        "postgres_smoke_required_before_ag_enablement": True,
        "real_subprocess_start_stop_enabled": False,
        "production_continuous_start_enabled": False,
        "job_queue_enqueue_allowed_for_operator_control": False,
        "ag_direct_worker_execution_allowed": False,
        "ag_direct_process_control_allowed": False,
        "ag_direct_database_write_allowed": False,
        "physical_delete_automation_enabled": False,
    }
    assert evidence["refactoring_checkpoint"] == {
        "separate_worker_contract_from_route_handler": True,
        "keep_worker_contracts_in_daemon_module": True,
        "keep_route_validation_in_artifacts_module": True,
        "reuse_s60_execution_request_state_transition_contracts": True,
        "reuse_supervisor_command_result_contract": True,
        "reuse_fake_supervisor_adapter_for_first_worker": True,
        "reuse_operator_control_execution_store": True,
        "do_not_reuse_scheduled_purge_worker_for_process_control": True,
        "avoid_new_long_running_jobqueue_worker": True,
        "keep_jobqueue_for_finite_retention_work": True,
        "keep_ag_as_read_only_worker_projection": True,
        "metadata_only_safe_projection": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert evidence["next_slices"] == [
        "Slice_0602",
        "Slice_0603",
        "Slice_0604",
        "Slice_0605",
        "Slice_0606",
        "Slice_0607",
        "Slice_0608",
        "Slice_0609",
        "Slice_0610",
    ]
    summary = audit.summary_line(evidence)
    assert "ae_operator_control_execution_worker_boundary_audit=pass" in summary
    assert "next=Slice_0602" in summary


def test_ae_operator_control_execution_worker_boundary_redacts_env() -> None:
    env = protected_env()

    evidence = audit.run_ae_operator_control_execution_worker_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0601" not in serialized
    assert "service-token-0601" not in serialized
    assert env["NEX_AE_TEST_DATABASE_URL"] not in serialized
    assert evidence["protected_env"] == {
        "NEX_AE_DATABASE_URL": True,
        "NEX_AE_TEST_DATABASE_URL": True,
        "NEX_AE_OPERATOR_CONTROL_EXECUTION_WORKER_SMOKE": True,
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_SMOKE": True,
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_READ_MODEL_POSTGRES_SMOKE": True,
        "NEX_AG_AE_ARTIFACT_BASE_URL": True,
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": True,
        "NEX_SERVICE_TOKEN": True,
    }


def test_ae_operator_control_execution_worker_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = audit.run_ae_operator_control_execution_worker_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ae_operator_control_execution_worker_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["quality_docs_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ae_operator_control_execution_worker_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    for required in audit.REQUIRED_PATHS:
        source = ROOT / required.relative_path
        target = tmp_path / required.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target = (
        tmp_path
        / "services"
        / "nex-ae-api"
        / "nex_ae_api"
        / "artifact_retention_scheduler_daemon.py"
    )
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            '"ADMITTED": ["EXECUTING", "BLOCKED"]',
            '"ADMITTED": ["BLOCKED"]',
        ),
        encoding="utf-8",
    )

    evidence = audit.run_ae_operator_control_execution_worker_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["ae_execution_state_machine_present"] is False
    failed = [
        item
        for item in evidence["source_tokens"]
        if item["token_id"] == "admitted_to_executing_or_blocked"
    ]
    assert failed == [
        {
            "group": "ae_execution_state_machine",
            "token_id": "admitted_to_executing_or_blocked",
            "path": (
                "services/nex-ae-api/nex_ae_api/"
                "artifact_retention_scheduler_daemon.py"
            ),
            "purpose": "An admitted state may only move to executing or blocked.",
            "present": False,
        }
    ]


def test_ae_operator_control_execution_worker_boundary_helpers_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ae_operator_control_execution_worker_boundary_audit({})

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

    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        audit._assert_evidence_redacted(
            protected_env()["NEX_AE_TEST_DATABASE_URL"],
            protected_env(),
        )
    for leaked in (
        "db=postgresql://user:pass@host/db",
        "Authorization: Bearer token",
        "provider=ed6@c496em",
        "password=nuri1004",
        "/data/nex-platform/private",
        "idempotency_key=unsafe",
        "raw_execution_payload",
    ):
        with pytest.raises(ValueError, match="Sensitive value leaked"):
            audit._assert_evidence_redacted(leaked, {})

    monkeypatch.setattr(
        audit,
        "run_ae_operator_control_execution_worker_boundary_audit",
        lambda: evidence,
    )
    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "ae_operator_control_execution_worker_boundary_audit=pass" in (
        capsys.readouterr().out
    )

    monkeypatch.setattr(
        audit,
        "run_ae_operator_control_execution_worker_boundary_audit",
        lambda: {
            "status": "FAIL",
            "failure_code": "test",
            "checks": {"required_paths_present": False},
        },
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
