from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import run_ae_supervised_process_operator_control_boundary_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0581@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_AE_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0581@127.0.0.1:5432/nex_ae_dev"
        ),
        "NEX_AE_SUPERVISED_PROCESS_OPERATOR_CONTROL_SMOKE": "1",
        "NEX_AE_SCHEDULER_DAEMON_ENABLE_SUPERVISED_PROCESS": "1",
        "NEX_AG_AE_ARTIFACT_BASE_URL": "http://127.0.0.1:8102/private",
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": "service-token-0581",
        "NEX_SERVICE_TOKEN": "service-token-shared-0581",
    }


def test_ae_supervised_process_operator_control_boundary_audit_passes_repo() -> None:
    evidence = audit.run_ae_supervised_process_operator_control_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0581"
    assert evidence["surface"] == audit.S59_SURFACE
    assert evidence["operator_control_boundary"] == {
        "artifact_system_of_record": "nex-ae-api",
        "daemon_process_owner": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "operator_dispatch_owner": "nex-ag",
        "runtime_boundary": "ae_owned_guarded_operator_control_test_profile_only",
        "default_operator_control_mode": "blocked_until_policy_contract",
        "first_operator_control_mode": "explicit_operator_test_profile_bounded_subprocess",
        "supported_operator_actions": [
            "status_probe",
            "start_daemon",
            "stop_daemon",
            "restart_daemon",
        ],
        "restart_semantics": "stop_then_start_with_distinct_evidence",
        "operator_subject_required": True,
        "idempotency_key_required": True,
        "operator_reason_required": True,
        "operator_approval_required_for_start_restart": True,
        "test_profile_required": True,
        "explicit_opt_in_required": True,
        "bounded_max_cycles_required": True,
        "status_probe_required_before_mutation": True,
        "process_lock_required_before_start": True,
        "pid_metadata_required_before_stop": True,
        "postgres_smoke_required_before_enablement": True,
        "production_continuous_start_enabled": False,
        "ag_direct_process_control_allowed": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "physical_delete_automation_enabled": False,
    }
    assert evidence["refactoring_checkpoint"] == {
        "keep_policy_contract_in_daemon_module": True,
        "keep_route_validation_in_artifacts_module": True,
        "keep_execution_adapter_in_daemon_module": True,
        "reuse_supervisor_command_result_contract": True,
        "reuse_supervised_process_snapshot_store": True,
        "reuse_bounded_cli_entrypoint_for_start": True,
        "reuse_shutdown_signal_boundary_for_stop": True,
        "keep_ag_as_read_only_operator_dispatcher": True,
        "do_not_use_jobqueue_for_long_running_daemon_process": True,
        "keep_jobqueue_for_finite_retention_work": True,
        "metadata_only_operator_evidence": True,
    }
    assert all(evidence["checks"].values())
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert evidence["next_slices"] == [
        "Slice_0582",
        "Slice_0583",
        "Slice_0584",
        "Slice_0585",
        "Slice_0586",
        "Slice_0587",
        "Slice_0588",
        "Slice_0589",
        "Slice_0590",
    ]
    assert "next=Slice_0582" in audit.summary_line(evidence)


def test_ae_supervised_process_operator_control_boundary_redacts_env() -> None:
    env = protected_env()

    evidence = audit.run_ae_supervised_process_operator_control_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0581" not in serialized
    assert "service-token-0581" not in serialized
    assert env["NEX_AE_TEST_DATABASE_URL"] not in serialized
    assert evidence["protected_env"] == {
        "NEX_AE_DATABASE_URL": True,
        "NEX_AE_TEST_DATABASE_URL": True,
        "NEX_AE_SUPERVISED_PROCESS_OPERATOR_CONTROL_SMOKE": True,
        "NEX_AE_SCHEDULER_DAEMON_ENABLE_SUPERVISED_PROCESS": True,
        "NEX_AG_AE_ARTIFACT_BASE_URL": True,
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": True,
        "NEX_SERVICE_TOKEN": True,
    }


def test_ae_supervised_process_operator_control_boundary_reports_missing(
    tmp_path: Path,
) -> None:
    evidence = audit.run_ae_supervised_process_operator_control_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ae_supervised_process_operator_control_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["quality_docs_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ae_supervised_process_operator_control_boundary_reports_token_failure(
    tmp_path: Path,
) -> None:
    for required in audit.REQUIRED_PATHS:
        source = required.path
        target = tmp_path / source.relative_to(audit.ROOT)
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

    evidence = audit.run_ae_supervised_process_operator_control_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["ag_operator_boundary_present"] is False
    failed = [
        item
        for item in evidence["source_tokens"]
        if item["token_id"] == "ag_direct_process_control_disallowed"
    ]
    assert failed == [
        {
            "group": "ag_operator_boundary",
            "token_id": "ag_direct_process_control_disallowed",
            "path": "services/nex-ag/nex_ag/artifact_operations.py",
            "purpose": "AG must not directly control AE subprocesses.",
            "present": False,
        }
    ]


def test_ae_supervised_process_operator_control_boundary_helpers_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ae_supervised_process_operator_control_boundary_audit({})

    audit.write_audit_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    assert audit._relative_label(audit.AE_DAEMON, audit.ROOT).endswith(
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py"
    )
    assert audit._relative_label(Path("/outside/audit.py"), tmp_path) == "audit.py"
    assert audit._present_count([{"present": True}, {"present": False}, {}]) == 1
    assert audit._present_count(None) == 0
    assert audit._grouped_token_status(
        [
            {"group": "ready", "present": True},
            {"group": "ready", "present": True},
            {"group": "blocked", "present": False},
        ]
    ) == {"blocked": False, "ready": True}
    assert "failing_checks" not in audit.summary_line(
        {"status": "PASS", "paths": [], "source_tokens": [], "checks": None}
    )
    assert audit._read_text(audit.AE_DAEMON)
    assert audit._read_text(tmp_path / "missing.md") == ""

    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        audit._assert_evidence_redacted(
            protected_env()["NEX_AE_TEST_DATABASE_URL"],
            protected_env(),
        )
    with pytest.raises(ValueError, match="Sensitive value leaked"):
        audit._assert_evidence_redacted("db=postgresql://user:pass@host/db", {})
    with pytest.raises(ValueError, match="Sensitive value leaked"):
        audit._assert_evidence_redacted("provider=ed6@c496em", {})

    pass_evidence = {
        "audit_schema_version": audit.SCHEMA_VERSION,
        "status": "PASS",
        "paths": [],
        "source_tokens": [],
        "checks": {},
    }
    monkeypatch.setattr(
        audit,
        "run_ae_supervised_process_operator_control_boundary_audit",
        lambda *_args, **_kwargs: pass_evidence,
    )
    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "ae_supervised_process_operator_control_boundary_audit=pass" in (
        capsys.readouterr().out
    )

    fail_evidence = {
        "audit_schema_version": audit.SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": "ae_supervised_process_operator_control_boundary_failed",
        "paths": [],
        "source_tokens": [],
        "checks": {"required_paths_present": False},
    }
    monkeypatch.setattr(
        audit,
        "run_ae_supervised_process_operator_control_boundary_audit",
        lambda *_args, **_kwargs: fail_evidence,
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_ae_supervised_process_operator_control_boundary_main_reports_redaction_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def raise_redaction(*_args, **_kwargs):
        raise ValueError("NEX_AE_TEST_DATABASE_URL leaked into evidence.")

    monkeypatch.setattr(
        audit,
        "run_ae_supervised_process_operator_control_boundary_audit",
        raise_redaction,
    )

    assert audit.main(["--summary"]) == 1
    assert "ae_supervised_process_operator_control_boundary_audit=fail" in (
        capsys.readouterr().out
    )
