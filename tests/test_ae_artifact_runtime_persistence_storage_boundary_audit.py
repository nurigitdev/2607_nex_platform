from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ae_artifact_runtime_persistence_storage_boundary_audit as audit


def protected_env() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0401@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_AE_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0401@127.0.0.1:5432/nex_ae_dev"
        ),
        "NEX_DATA_ROOT": "/data/nex-platform/private-0401",
        "NEX_AE_ARTIFACT_STORAGE_ROOT": (
            "/data/nex-platform/private-0401/ae/artifacts"
        ),
        "NEX_AE_TO_CX_SERVICE_TOKEN": "service-token-0401",
    }


def test_artifact_runtime_storage_boundary_audit_passes_current_repo() -> None:
    evidence = audit.run_ae_artifact_runtime_persistence_storage_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["decisions"]["artifact_system_of_record"] == "nex-ae-api"
    assert evidence["decisions"]["current_record_persistence"] == (
        "process_local_memory"
    )
    assert evidence["decisions"]["current_render_payload_storage"] == (
        "process_local_memory"
    )
    assert evidence["decisions"]["durable_record_persistence_target"] == (
        "nex_ae_database"
    )
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["blocking"] is False for item in evidence["planned_gaps"])
    assert evidence["checks"]["redacted_evidence_only"] is True
    assert audit.summary_line(evidence).startswith(
        "ae_artifact_runtime_persistence_storage_boundary_audit=pass "
    )
    assert "next=Slice_0402" in audit.summary_line(evidence)


def test_artifact_runtime_storage_boundary_audit_does_not_leak_protected_values() -> None:
    env = protected_env()

    evidence = audit.run_ae_artifact_runtime_persistence_storage_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "/data/nex-platform" not in serialized
    assert "secret-0401" not in serialized
    assert "service-token-0401" not in serialized
    assert env["NEX_AE_TEST_DATABASE_URL"] not in serialized
    assert env["NEX_AE_ARTIFACT_STORAGE_ROOT"] not in serialized


def test_artifact_runtime_storage_boundary_audit_reports_missing_static_boundaries(
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
                "artifact_route_surface",
                missing,
                "missing-token",
                "missing token value",
                "Missing token for regression coverage.",
            ),
        ),
    )

    evidence = audit.run_ae_artifact_runtime_persistence_storage_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["artifact_route_surface_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_artifact_runtime_storage_boundary_audit_helpers_output_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ae_artifact_runtime_persistence_storage_boundary_audit({})

    audit.write_audit_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        audit.assert_evidence_redacted(
            "postgresql+psycopg://nex_ae_user:secret-0401@127.0.0.1:5432/nex_ae_test",
            protected_env(),
        )
    with pytest.raises(ValueError, match="local data path"):
        audit.assert_evidence_redacted("artifact=/data/nex-platform/ae/file", {})
    with pytest.raises(ValueError, match="database password"):
        audit.assert_evidence_redacted("password=nuri1004", {})

    assert audit.relative_label(Path("/outside/audit.py"), tmp_path) == "audit.py"
    assert audit.present_count([{"present": True}, {"present": False}]) == 1
    assert audit.present_count_bool({"a": True, "b": False}) == 1
    assert audit.grouped_token_status(
        [
            {"group": "ready", "present": True},
            {"group": "ready", "present": True},
            {"group": "blocked", "present": False},
        ]
    ) == {"ready": True, "blocked": False}
    assert "0083_service_job_queue_foundation.sql" in audit.read_text(
        audit.ROOT,
        audit.AE_MIGRATIONS,
    )

    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "ae_artifact_runtime_persistence_storage_boundary_audit=pass" in (
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


def test_artifact_runtime_storage_boundary_audit_quality_gate_docs_and_readme_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    ae_readme = (root / "services" / "nex-ae-api" / "README.md").read_text(
        encoding="utf-8"
    )
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0401_ae_artifact_runtime_persistence_storage_boundary_audit.md"
    )

    assert (
        "run_ae_artifact_runtime_persistence_storage_boundary_audit.py --summary"
        in quality_gate
    )
    assert "0401_ae_artifact_runtime_persistence_storage_boundary_audit.md" in docs_index
    assert "Slice 0401" in ae_readme
    assert slice_doc.exists()
