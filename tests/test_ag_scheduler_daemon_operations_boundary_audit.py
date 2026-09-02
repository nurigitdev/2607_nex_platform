from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ag_scheduler_daemon_operations_boundary_audit as audit


def protected_env() -> dict[str, str]:
    return {
        "NEX_AG_AE_ARTIFACT_BASE_URL": "http://127.0.0.1:8102/private",
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": "service-token-0521",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0521@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_AE_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0521@127.0.0.1:5432/nex_ae_dev"
        ),
        "NEX_AE_ARTIFACT_STORAGE_ROOT": "/data/nex-platform/ae/artifacts",
        "NEX_SERVICE_TOKEN": "service-token-shared-0521",
    }


def test_ag_scheduler_daemon_operations_boundary_audit_passes_current_repo() -> None:
    evidence = audit.run_ag_scheduler_daemon_operations_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0521"
    assert evidence["surface"] == audit.S53_OPERATION_SURFACE
    assert evidence["operations_boundary"] == {
        "artifact_system_of_record": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "control_boundary": "ae_api_only",
        "daemon_config_source": "ae_api_scheduler_daemon_config",
        "daemon_control_source": "ae_api_scheduler_daemon_controls",
        "allowed_control_action": "manual_tick_once",
        "start_daemon_allowed": False,
        "continuous_loop_allowed": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "operator_confirmation_required_before_dispatch": True,
        "postgres_smoke_required_before_mutating_slices": True,
    }
    assert evidence["refactoring_checkpoint"] == {
        "extend_ag_client_protocol_before_routes": True,
        "build_projection_before_dispatch": True,
        "reuse_existing_retention_operations_family": True,
        "keep_ae_lease_job_history_as_system_of_record": True,
        "keep_continuous_daemon_loop_deferred": True,
    }
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["s52_closed_baseline_present"] is True
    assert evidence["checks"]["ag_write_boundary_present"] is True
    assert evidence["checks"]["start_daemon_must_remain_blocked"] is True
    assert evidence["checks"]["continuous_loop_deferred"] is True
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["blocking"] is False for item in evidence["planned_operations_steps"])
    assert evidence["next_slices"] == [
        "Slice_0522",
        "Slice_0523",
        "Slice_0524",
        "Slice_0525",
    ]
    assert "next=Slice_0522" in audit.summary_line(evidence)


def test_ag_scheduler_daemon_operations_boundary_audit_redacts_protected_values() -> None:
    env = protected_env()

    evidence = audit.run_ag_scheduler_daemon_operations_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0521" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "service-token-0521" not in serialized
    assert env["NEX_AE_TEST_DATABASE_URL"] not in serialized
    assert audit.summarize_protected_env(env) == {
        "NEX_AG_AE_ARTIFACT_BASE_URL": True,
        "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN": True,
        "NEX_AE_DATABASE_URL": True,
        "NEX_AE_TEST_DATABASE_URL": True,
        "NEX_AE_ARTIFACT_STORAGE_ROOT": True,
        "NEX_SERVICE_TOKEN": True,
    }


def test_ag_scheduler_daemon_operations_boundary_audit_reports_missing_boundaries(
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

    evidence = audit.run_ag_scheduler_daemon_operations_boundary_audit(
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


def test_ag_scheduler_daemon_operations_boundary_audit_reports_token_failure(
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
                "ag_write_boundary",
                source_file,
                "missing-token",
                "not present",
                "Missing token for regression coverage.",
            ),
        ),
    )

    evidence = audit.run_ag_scheduler_daemon_operations_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["ag_write_boundary_present"] is False
    assert evidence["issues"] == [
        {
            "category": "source_token_missing",
            "group": "ag_write_boundary",
            "token_id": "missing-token",
            "path": "source.py",
            "purpose": "Missing token for regression coverage.",
        }
    ]


def test_ag_scheduler_daemon_operations_boundary_audit_helpers_output_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ag_scheduler_daemon_operations_boundary_audit({})

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

    assert audit.relative_label(audit.AG_ARTIFACT_OPERATIONS, audit.ROOT).endswith(
        "services/nex-ag/nex_ag/artifact_operations.py"
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
    assert audit.read_text(audit.AG_ARTIFACT_OPERATIONS)
    assert audit.read_text(tmp_path / "missing.md") == ""
    assert audit.build_planned_operations_steps()[0]["planned_slice"] == "Slice_0522"

    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "ag_scheduler_daemon_operations_boundary_audit=pass" in (
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


def test_ag_scheduler_daemon_operations_boundary_audit_cli_fail_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit,
        "run_ag_scheduler_daemon_operations_boundary_audit",
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
    assert "ag_scheduler_daemon_operations_boundary_audit=fail" in output
    assert "failing_checks=required_paths_present" in output
