from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import run_ae_operator_control_execution_boundary_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0591@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_AE_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0591@127.0.0.1:5432/nex_ae_dev"
        ),
        "NEX_AE_OPERATOR_CONTROL_EXECUTION_SMOKE": "1",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_SMOKE": "1",
        "NEX_AE_SCHEDULER_DAEMON_ENABLE_SUPERVISED_PROCESS": "1",
        "NEX_AG_AE_ARTIFACT_BASE_URL": "http://127.0.0.1:8102/private",
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": "service-token-0591",
        "NEX_SERVICE_TOKEN": "service-token-shared-0591",
    }


def test_ae_operator_control_execution_boundary_audit_passes_repo() -> None:
    evidence = audit.run_ae_operator_control_execution_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0591"
    assert evidence["surface"] == audit.S60_SURFACE
    assert evidence["execution_boundary"] == {
        "artifact_system_of_record": "nex-ae-api",
        "daemon_process_owner": "nex-ae-api",
        "supervisor_execution_owner": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "operator_dispatch_owner": "nex-ag",
        "execution_boundary": "ae_owned_supervisor_execution_test_profile_only",
        "default_execution_mode": "blocked_until_execution_contract",
        "first_execution_mode": "fake_dry_run_supervisor_persistent_dispatch",
        "source_preview_required": True,
        "supported_operator_actions": [
            "status_probe",
            "start_daemon",
            "stop_daemon",
            "restart_daemon",
        ],
        "restart_semantics": "stop_then_start_with_distinct_persisted_results",
        "operator_subject_required": True,
        "idempotency_key_required": True,
        "operator_reason_required": True,
        "operator_approval_required_for_start_restart": True,
        "test_profile_required": True,
        "explicit_opt_in_required_for_start_restart": True,
        "bounded_max_cycles_required": True,
        "supervisor_adapter_required_for_mutation": True,
        "supervisor_result_persistence_required": True,
        "supervised_process_snapshot_compatible": True,
        "postgres_smoke_required_before_ag_enablement": True,
        "production_continuous_start_enabled": False,
        "ag_direct_process_control_allowed": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "physical_delete_automation_enabled": False,
    }
    assert evidence["refactoring_checkpoint"] == {
        "reuse_s59_policy_request_admission_preview": True,
        "keep_execution_contracts_in_daemon_module": True,
        "keep_route_validation_in_artifacts_module": True,
        "reuse_supervisor_command_result_contract": True,
        "reuse_supervisor_store_for_execution_evidence": True,
        "reuse_supervised_process_read_model_for_status": True,
        "avoid_new_long_running_jobqueue_worker": True,
        "keep_jobqueue_for_finite_retention_work": True,
        "keep_ag_as_dispatcher_projection_only": True,
        "metadata_only_operator_execution_evidence": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert evidence["next_slices"] == [
        "Slice_0592",
        "Slice_0593",
        "Slice_0594",
        "Slice_0595",
        "Slice_0596",
        "Slice_0597",
        "Slice_0598",
        "Slice_0599",
        "Slice_0600",
    ]
    assert "next=Slice_0592" in audit.summary_line(evidence)


def test_ae_operator_control_execution_boundary_redacts_env() -> None:
    env = protected_env()

    evidence = audit.run_ae_operator_control_execution_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0591" not in serialized
    assert "service-token-0591" not in serialized
    assert env["NEX_AE_TEST_DATABASE_URL"] not in serialized
    assert evidence["protected_env"] == {
        "NEX_AE_DATABASE_URL": True,
        "NEX_AE_TEST_DATABASE_URL": True,
        "NEX_AE_OPERATOR_CONTROL_EXECUTION_SMOKE": True,
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_SMOKE": True,
        "NEX_AE_SCHEDULER_DAEMON_ENABLE_SUPERVISED_PROCESS": True,
        "NEX_AG_AE_ARTIFACT_BASE_URL": True,
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": True,
        "NEX_SERVICE_TOKEN": True,
    }


def test_ae_operator_control_execution_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = audit.run_ae_operator_control_execution_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ae_operator_control_execution_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["quality_docs_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ae_operator_control_execution_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    for required in audit.REQUIRED_PATHS:
        source = ROOT / required.relative_path
        target = tmp_path / required.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target = tmp_path / "services" / "nex-ag" / "nex_ag" / "artifact_operations.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            '"ag_direct_daemon_process_control_allowed": False',
            '"ag_direct_daemon_process_control_allowed": True',
        ),
        encoding="utf-8",
    )

    evidence = audit.run_ae_operator_control_execution_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["ag_execution_boundary_present"] is False
    failed = [
        item
        for item in evidence["source_tokens"]
        if item["token_id"] == "ag_direct_process_control_disallowed"
    ]
    assert failed == [
        {
            "group": "ag_execution_boundary",
            "token_id": "ag_direct_process_control_disallowed",
            "path": "services/nex-ag/nex_ag/artifact_operations.py",
            "purpose": "AG must not directly control AE daemon processes.",
            "present": False,
        }
    ]


def test_ae_operator_control_execution_boundary_helpers_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ae_operator_control_execution_boundary_audit({})

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
    ):
        with pytest.raises(ValueError, match="Sensitive value leaked"):
            audit._assert_evidence_redacted(leaked, {})

    monkeypatch.setattr(
        audit,
        "run_ae_operator_control_execution_boundary_audit",
        lambda: evidence,
    )
    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "ae_operator_control_execution_boundary_audit=pass" in (
        capsys.readouterr().out
    )

    monkeypatch.setattr(
        audit,
        "run_ae_operator_control_execution_boundary_audit",
        lambda: {
            "status": "FAIL",
            "failure_code": "test",
            "checks": {"required_paths_present": False},
        },
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
