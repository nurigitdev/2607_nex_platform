from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ae_scheduler_daemon_process_boundary_audit as audit


def protected_env() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0541@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_AE_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0541@127.0.0.1:5432/nex_ae_dev"
        ),
        "NEX_AE_ARTIFACT_STORAGE_ROOT": "/data/nex-platform/ae/artifacts",
        "NEX_AG_AE_ARTIFACT_BASE_URL": "http://127.0.0.1:8102/private",
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": "service-token-0541",
        "NEX_SERVICE_TOKEN": "service-token-shared-0541",
    }


def test_ae_scheduler_daemon_process_boundary_audit_passes_current_repo() -> None:
    evidence = audit.run_ae_scheduler_daemon_process_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0541"
    assert evidence["surface"] == audit.S55_PROCESS_SURFACE
    assert evidence["process_boundary"] == {
        "artifact_system_of_record": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "daemon_process_owner": "nex-ae-api",
        "daemon_process_model": "ae_owned_external_process",
        "daemon_role": "coordinator",
        "job_queue_role": "finite_retention_work_execution",
        "job_queue_execution_boundary": "finite_retention_jobs_only",
        "daemon_as_jobqueue_job_allowed": False,
        "api_embedded_long_running_loop_allowed": False,
        "retention_work_must_use_job_queue": True,
        "worker_slot_reserved_for_finite_jobs": True,
        "control_surface": "ae_api_and_daemon_runtime_state",
        "ag_control_boundary": "ae_api_only",
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "default_daemon_mode": "disabled",
        "default_execution_mode": "DRY_RUN",
        "runtime_state_store_required_before_start": True,
        "heartbeat_store_required_for_observability": True,
        "bounded_loop_required_before_continuous_loop": True,
        "graceful_shutdown_required_before_start": True,
        "postgres_smoke_required_before_enablement": True,
    }
    assert evidence["refactoring_checkpoint"] == {
        "keep_loop_entrypoint_out_of_artifacts_module": True,
        "reuse_one_cycle_runner_for_each_daemon_iteration": True,
        "reuse_scheduler_tick_job_admission": True,
        "do_not_run_daemon_as_jobqueue_worker_job": True,
        "keep_worker_slots_for_finite_retention_jobs": True,
        "persist_control_decisions_before_process_start": True,
        "metadata_only_ag_projection": True,
    }
    assert evidence["checks"]["s54_closed_baseline_present"] is True
    assert evidence["checks"]["daemon_coordinator_boundary_present"] is True
    assert evidence["checks"]["queue_execution_boundary_present"] is True
    assert evidence["checks"]["daemon_is_coordinator_not_worker"] is True
    assert evidence["checks"]["retention_work_uses_job_queue"] is True
    assert evidence["checks"]["daemon_not_jobqueue_long_running_job"] is True
    assert evidence["checks"]["api_embedded_long_loop_disallowed"] is True
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["blocking"] is False for item in evidence["planned_process_steps"])
    assert evidence["next_slices"] == [
        "Slice_0542",
        "Slice_0543",
        "Slice_0544",
        "Slice_0545",
    ]
    assert "next=Slice_0542" in audit.summary_line(evidence)


def test_ae_scheduler_daemon_process_boundary_audit_redacts_protected_values() -> None:
    env = protected_env()

    evidence = audit.run_ae_scheduler_daemon_process_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0541" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "service-token-0541" not in serialized
    assert env["NEX_AE_TEST_DATABASE_URL"] not in serialized
    assert audit.summarize_protected_env(env) == {
        "NEX_AE_DATABASE_URL": True,
        "NEX_AE_TEST_DATABASE_URL": True,
        "NEX_AE_ARTIFACT_STORAGE_ROOT": True,
        "NEX_AG_AE_ARTIFACT_BASE_URL": True,
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": True,
        "NEX_SERVICE_TOKEN": True,
    }


def test_ae_scheduler_daemon_process_boundary_audit_reports_missing_boundaries(
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

    evidence = audit.run_ae_scheduler_daemon_process_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "ae_scheduler_daemon_process_boundary_failed"
    assert evidence["checks"]["required_paths_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ae_scheduler_daemon_process_boundary_audit_reports_token_failure(
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
                "queue_execution_boundary",
                source_file,
                "missing-token",
                "not present",
                "Missing token for regression coverage.",
            ),
        ),
    )

    evidence = audit.run_ae_scheduler_daemon_process_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["queue_execution_boundary_present"] is False
    assert evidence["issues"] == [
        {
            "category": "source_token_missing",
            "group": "queue_execution_boundary",
            "token_id": "missing-token",
            "path": "source.py",
            "purpose": "Missing token for regression coverage.",
        }
    ]


def test_ae_scheduler_daemon_process_boundary_audit_helpers_output_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ae_scheduler_daemon_process_boundary_audit({})

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

    assert audit.relative_label(audit.AE_SCHEDULER, audit.ROOT).endswith(
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py"
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
    assert audit.read_text(audit.AE_SCHEDULER)
    assert audit.read_text(tmp_path / "missing.md") == ""
    assert audit.build_planned_process_steps()[0]["planned_slice"] == "Slice_0542"

    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "ae_scheduler_daemon_process_boundary_audit=pass" in (
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


def test_ae_scheduler_daemon_process_boundary_audit_cli_fail_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit,
        "run_ae_scheduler_daemon_process_boundary_audit",
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
    assert "ae_scheduler_daemon_process_boundary_audit=fail" in output
    assert "failing_checks=required_paths_present" in output


def test_ae_scheduler_daemon_process_boundary_quality_gate_docs_and_readme_wired() -> None:
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
    slice_doc = (
        root / "docs" / "slices" / "0541_ae_scheduler_daemon_process_boundary_audit.md"
    )

    assert "run_ae_scheduler_daemon_process_boundary_audit.py" in quality_gate
    assert "Slice 0541" in docs_index
    assert "Slice 0541 starts S55" in ae_api_readme
    assert "Slice 0541 starts S55" in ag_readme
    assert slice_doc.is_file()
