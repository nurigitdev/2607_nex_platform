from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ae_scheduler_daemon_executable_runtime_boundary_audit as audit


def protected_env() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0551@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_AE_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0551@127.0.0.1:5432/nex_ae_dev"
        ),
        "NEX_AE_ARTIFACT_STORAGE_ROOT": "/data/nex-platform/ae/artifacts",
        "NEX_AG_AE_ARTIFACT_BASE_URL": "http://127.0.0.1:8102/private",
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": "service-token-0551",
        "NEX_SERVICE_TOKEN": "service-token-shared-0551",
    }


def test_ae_scheduler_daemon_executable_runtime_boundary_audit_passes_repo() -> None:
    evidence = audit.run_ae_scheduler_daemon_executable_runtime_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0551"
    assert evidence["surface"] == audit.S56_EXECUTABLE_SURFACE
    assert evidence["executable_runtime_boundary"] == {
        "artifact_system_of_record": "nex-ae-api",
        "daemon_process_owner": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "runtime_boundary": "protected_bounded_test_profile_only",
        "default_daemon_mode": "disabled",
        "default_command_mode": "plan_only",
        "first_execution_mode": "explicit_bounded_loop",
        "executable_runtime_default_enabled": False,
        "test_profile_required": True,
        "explicit_opt_in_required": True,
        "bounded_max_cycles_required": True,
        "max_cycles_hard_cap": 100,
        "process_lock_required_before_start": True,
        "pid_metadata_required_before_start": True,
        "run_record_required_before_start": True,
        "graceful_shutdown_signal_adapter_required": True,
        "postgres_smoke_required_before_enablement": True,
        "retention_work_must_use_job_queue": True,
        "ag_direct_process_control_allowed": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "physical_delete_automation_enabled": False,
    }
    assert evidence["refactoring_checkpoint"] == {
        "keep_execution_entrypoint_in_daemon_module": True,
        "keep_long_running_loop_out_of_artifacts_module": True,
        "reuse_bounded_loop_adapter_for_cli_execution": True,
        "reuse_runtime_state_shutdown_and_retry_contracts": True,
        "reuse_worker_heartbeat_store_for_observability": True,
        "do_not_run_daemon_as_jobqueue_worker_job": True,
        "keep_jobqueue_for_finite_retention_work": True,
        "metadata_only_ag_projection": True,
        "redacted_cli_summary_only": True,
    }
    assert evidence["checks"] == {
        "required_paths_present": True,
        "s55_closed_baseline_present": True,
        "cli_plan_first_boundary_present": True,
        "bounded_loop_foundation_present": True,
        "lifecycle_guard_foundation_present": True,
        "api_control_boundary_present": True,
        "ag_read_only_lifecycle_present": True,
        "protected_postgres_evidence_present": True,
        "quality_gate_and_docs_present": True,
        "executable_runtime_not_default": True,
        "execute_requires_explicit_opt_in": True,
        "execute_requires_test_profile": True,
        "execute_requires_bounded_max_cycles": True,
        "process_lock_required_before_start": True,
        "graceful_shutdown_signal_required": True,
        "retention_work_uses_job_queue": True,
        "ag_remains_read_only": True,
        "physical_delete_disabled_by_default": True,
        "redacted_evidence_only": True,
    }
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["blocking"] is False for item in evidence["planned_executable_steps"])
    assert evidence["next_slices"] == [
        "Slice_0552",
        "Slice_0553",
        "Slice_0554",
        "Slice_0555",
    ]
    assert "next=Slice_0552" in audit.summary_line(evidence)


def test_ae_scheduler_daemon_executable_runtime_boundary_redacts_env() -> None:
    env = protected_env()

    evidence = audit.run_ae_scheduler_daemon_executable_runtime_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0551" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "service-token-0551" not in serialized
    assert env["NEX_AE_TEST_DATABASE_URL"] not in serialized
    assert audit.summarize_protected_env(env) == {
        "NEX_AE_DATABASE_URL": True,
        "NEX_AE_TEST_DATABASE_URL": True,
        "NEX_AE_ARTIFACT_STORAGE_ROOT": True,
        "NEX_AG_AE_ARTIFACT_BASE_URL": True,
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": True,
        "NEX_SERVICE_TOKEN": True,
    }


def test_ae_scheduler_daemon_executable_runtime_boundary_reports_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.py"
    monkeypatch.setattr(
        audit,
        "REQUIRED_PATHS",
        (
            audit.RequiredPath(
                "missing",
                missing,
                "Missing path for regression coverage.",
            ),
        ),
    )
    monkeypatch.setattr(
        audit,
        "REQUIRED_SOURCE_TOKENS",
        (
            audit.TokenRequirement(
                "missing_group",
                missing,
                "missing-token",
                "missing token value",
                "Missing token for regression coverage.",
            ),
        ),
    )

    evidence = audit.run_ae_scheduler_daemon_executable_runtime_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ae_scheduler_daemon_executable_runtime_boundary_failed"
    )
    assert evidence["checks"]["required_paths_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ae_scheduler_daemon_executable_runtime_boundary_reports_token_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "source.py"
    source_file.write_text("safe baseline", encoding="utf-8")
    monkeypatch.setattr(
        audit,
        "REQUIRED_PATHS",
        (
            audit.RequiredPath(
                "source",
                source_file,
                "Present path for regression coverage.",
            ),
        ),
    )
    monkeypatch.setattr(
        audit,
        "REQUIRED_SOURCE_TOKENS",
        (
            audit.TokenRequirement(
                "cli_plan_first_boundary",
                source_file,
                "missing-token",
                "not present",
                "Missing token for regression coverage.",
            ),
        ),
    )

    evidence = audit.run_ae_scheduler_daemon_executable_runtime_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["cli_plan_first_boundary_present"] is False
    assert evidence["issues"] == [
        {
            "category": "source_token_missing",
            "group": "cli_plan_first_boundary",
            "token_id": "missing-token",
            "path": "source.py",
            "purpose": "Missing token for regression coverage.",
        }
    ]


def test_ae_scheduler_daemon_executable_runtime_boundary_helpers_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ae_scheduler_daemon_executable_runtime_boundary_audit({})

    audit.write_audit_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        audit.assert_evidence_redacted(
            protected_env()["NEX_AE_TEST_DATABASE_URL"],
            protected_env(),
        )
    with pytest.raises(ValueError, match="Sensitive value leaked"):
        audit.assert_evidence_redacted("db=postgresql://user:pass@host/db", {})
    with pytest.raises(ValueError, match="Sensitive value leaked"):
        audit.assert_evidence_redacted("artifact=/data/nex-platform/ae/file", {})

    assert audit.relative_label(audit.AE_DAEMON_CLI, audit.ROOT).endswith(
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py"
    )
    assert audit.relative_label(Path("/outside/audit.py"), tmp_path) == "audit.py"
    assert audit.present_count([{"present": True}, {"present": False}, {}]) == 1
    assert audit.grouped_token_status(
        [
            {"group": "ready", "present": True},
            {"group": "ready", "present": True},
            {"group": "blocked", "present": False},
        ]
    ) == {"blocked": False, "ready": True}
    assert audit.read_text(audit.AE_DAEMON_CLI)
    assert audit.read_text(tmp_path / "missing.md") == ""
    assert audit.build_planned_executable_steps()[0]["planned_slice"] == "Slice_0552"

    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "ae_scheduler_daemon_executable_runtime_boundary_audit=pass" in (
        capsys.readouterr().out
    )

    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "write_audit_evidence",
        lambda *_: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert audit.main(["--output", str(tmp_path / "blocked.json")]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_ae_scheduler_daemon_executable_runtime_boundary_cli_fail_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit,
        "run_ae_scheduler_daemon_executable_runtime_boundary_audit",
        lambda *_: {
            "audit_schema_version": audit.SCHEMA_VERSION,
            "status": "FAIL",
            "paths": [{"present": False}],
            "source_tokens": [{"present": False}],
            "checks": {"required_paths_present": False},
        },
    )

    assert audit.main(["--summary"]) == 1
    output = capsys.readouterr().out
    assert "ae_scheduler_daemon_executable_runtime_boundary_audit=fail" in output
    assert "failing_checks=required_paths_present" in output


def test_ae_scheduler_daemon_executable_runtime_boundary_docs_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    ae_api_readme = (root / "services" / "nex-ae-api" / "README.md").read_text(
        encoding="utf-8"
    )
    ag_readme = (root / "services" / "nex-ag" / "README.md").read_text(
        encoding="utf-8"
    )
    slice_doc = root / "docs" / "slices" / (
        "0551_ae_scheduler_daemon_executable_runtime_boundary_audit.md"
    )

    assert "run_ae_scheduler_daemon_executable_runtime_boundary_audit.py" in quality_gate
    assert "Slice 0551" in docs_index
    assert "Slice 0551 starts S56" in ae_api_readme
    assert "Slice 0551 starts S56" in ag_readme
    assert slice_doc.is_file()
