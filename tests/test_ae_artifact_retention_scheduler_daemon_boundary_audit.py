from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ae_artifact_retention_scheduler_daemon_boundary_audit as audit


def protected_env() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0511@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_AE_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0511@127.0.0.1:5432/nex_ae_dev"
        ),
        "NEX_AE_ARTIFACT_STORAGE_ROOT": "/data/nex-platform/ae/artifacts",
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": "service-token-0511",
        "NEX_SERVICE_TOKEN": "service-token-shared-0511",
    }


def test_artifact_retention_scheduler_daemon_boundary_audit_passes_current_repo() -> None:
    evidence = audit.run_ae_artifact_retention_scheduler_daemon_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0511"
    assert evidence["daemon_boundary"]["scheduler_daemon_default"] == "disabled"
    assert evidence["daemon_boundary"]["daemon_auto_start_allowed"] is False
    assert evidence["daemon_boundary"]["continuous_loop_allowed_before_lease"] is False
    assert evidence["daemon_boundary"]["first_runtime_mode"] == audit.FIRST_S52_RUNTIME_MODE
    assert evidence["daemon_boundary"]["default_execution_mode"] == "DRY_RUN"
    assert evidence["daemon_boundary"]["ag_direct_database_write_allowed"] is False
    assert evidence["daemon_boundary"]["ag_direct_job_enqueue_allowed"] is False
    assert evidence["refactoring_checkpoint"] == {
        "keep_long_running_scheduler_code_out_of_artifacts_module": True,
        "introduce_lease_repository_before_daemon_loop": True,
        "prefer_manual_once_runner_before_continuous_loop": True,
        "reuse_existing_tick_planner_and_jobqueue_admission": True,
        "reuse_existing_worker_once_adapter": True,
    }
    assert evidence["checks"]["daemon_auto_start_deferred"] is True
    assert evidence["checks"]["first_runtime_mode_manual_once"] is True
    assert evidence["checks"]["lease_required_before_continuous_loop"] is True
    assert evidence["checks"]["physical_delete_automation_remains_disabled"] is True
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["blocking"] is False for item in evidence["planned_daemon_steps"])
    assert "next=Slice_0512" in audit.summary_line(evidence)


def test_artifact_retention_scheduler_daemon_boundary_audit_redacts_protected_values() -> None:
    env = protected_env()

    evidence = audit.run_ae_artifact_retention_scheduler_daemon_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0511" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "service-token-0511" not in serialized
    assert env["NEX_AE_TEST_DATABASE_URL"] not in serialized
    assert audit.summarize_protected_env(env) == {
        "NEX_AE_DATABASE_URL": True,
        "NEX_AE_TEST_DATABASE_URL": True,
        "NEX_AE_ARTIFACT_STORAGE_ROOT": True,
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": True,
        "NEX_SERVICE_TOKEN": True,
    }


def test_artifact_retention_scheduler_daemon_boundary_audit_reports_missing_boundaries(
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

    evidence = audit.run_ae_artifact_retention_scheduler_daemon_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_artifact_retention_scheduler_daemon_boundary_audit_reports_token_failure(
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
                "ae_scheduler_daemon_guard",
                source_file,
                "missing-token",
                "not present",
                "Missing token for regression coverage.",
            ),
        ),
    )

    evidence = audit.run_ae_artifact_retention_scheduler_daemon_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["ae_scheduler_daemon_guard_present"] is False
    assert evidence["issues"] == [
        {
            "category": "source_token_missing",
            "group": "ae_scheduler_daemon_guard",
            "token_id": "missing-token",
            "path": "source.py",
            "purpose": "Missing token for regression coverage.",
        }
    ]


def test_artifact_retention_scheduler_daemon_boundary_audit_helpers_output_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ae_artifact_retention_scheduler_daemon_boundary_audit({})

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

    assert audit.relative_label(audit.AE_API_ARTIFACTS, audit.ROOT).endswith(
        "services/nex-ae-api/nex_ae_api/artifacts.py"
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
    assert audit.read_text(audit.AE_API_ARTIFACTS)
    assert audit.read_text(tmp_path / "missing.md") == ""
    assert all(item["blocking"] is False for item in audit.build_planned_daemon_steps())

    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "ae_artifact_retention_scheduler_daemon_boundary_audit=pass" in (
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


def test_artifact_retention_scheduler_daemon_boundary_audit_cli_fail_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit,
        "run_ae_artifact_retention_scheduler_daemon_boundary_audit",
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
    assert "ae_artifact_retention_scheduler_daemon_boundary_audit=fail" in output
    assert "failing_checks=required_paths_present" in output


def test_artifact_retention_scheduler_daemon_boundary_quality_gate_docs_and_readme_wired() -> None:
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
        root
        / "docs"
        / "slices"
        / "0511_ae_scheduler_daemon_boundary_audit_refactoring_checkpoint.md"
    )

    assert "run_ae_artifact_retention_scheduler_daemon_boundary_audit.py" in quality_gate
    assert "Slice 0511" in docs_index
    assert "Slice 0511 starts S52" in ae_api_readme
    assert "Slice 0511 starts S52" in ag_readme
    assert slice_doc.is_file()
