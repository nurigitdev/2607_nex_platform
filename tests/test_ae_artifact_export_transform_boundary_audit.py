from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import run_ae_artifact_export_transform_boundary_audit as audit


ROOT = Path(__file__).resolve().parents[1]


def protected_env() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0421@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_AE_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0421@127.0.0.1:5432/nex_ae_dev"
        ),
        "NEX_AE_ARTIFACT_STORAGE_ROOT": "/data/nex-platform/ae/artifacts",
        "NEX_SERVICE_TOKEN": "service-token-0421",
        "NEX_AE_TO_CX_SERVICE_TOKEN": "service-token-ae-cx-0421",
    }


def test_ae_artifact_export_transform_boundary_audit_passes_current_repo() -> None:
    evidence = audit.run_ae_artifact_export_transform_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["decisions"]["artifact_transform_owner"] == "nex-ae-api"
    assert evidence["decisions"]["browser_request_surface_owner"] == "nex-ae-web"
    assert evidence["decisions"]["source_generation_owner"] == "nex-cx"
    assert evidence["decisions"]["current_runtime_materialization"] == (
        "markdown_only_synchronous_renderer"
    )
    assert evidence["decisions"]["implemented_materialized_format"] == "MD"
    assert evidence["decisions"]["future_materialized_formats"] == [
        "HTML_PREVIEW",
        "DOCX",
        "PDF",
    ]
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["blocking"] is False for item in evidence["planned_gaps"])
    assert evidence["checks"]["current_runtime_is_markdown_only"] is True
    assert evidence["checks"]["future_export_formats_are_declared"] is True
    assert evidence["checks"]["redacted_evidence_only"] is True
    assert audit.summary_line(evidence).startswith(
        "ae_artifact_export_transform_boundary_audit=pass "
    )
    assert "gaps_ready=8/8" in audit.summary_line(evidence)
    assert "next=complete" in audit.summary_line(evidence)


def test_ae_artifact_export_transform_boundary_audit_does_not_leak_protected_values() -> None:
    env = protected_env()

    evidence = audit.run_ae_artifact_export_transform_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "/data/nex-platform" not in serialized
    assert "secret-0421" not in serialized
    assert "service-token-0421" not in serialized
    assert env["NEX_AE_TEST_DATABASE_URL"] not in serialized
    assert env["NEX_AE_ARTIFACT_STORAGE_ROOT"] not in serialized


def test_ae_artifact_export_transform_boundary_audit_reports_missing_boundaries(
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
                "contract_format_surface",
                missing,
                "missing-token",
                "missing token value",
                "Missing token for regression coverage.",
            ),
        ),
    )

    evidence = audit.run_ae_artifact_export_transform_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["contract_format_surface_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_ae_artifact_export_transform_boundary_audit_reports_token_failure(
    tmp_path: Path,
) -> None:
    for required_path in {item.path for item in audit.REQUIRED_PATHS}:
        target = tmp_path / required_path.relative_to(audit.ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(required_path, target)
    artifacts = tmp_path / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
    artifacts.write_text(
        artifacts.read_text(encoding="utf-8").replace(
            "Slice 0042 supports Markdown rendering only.",
            "Slice 0042 message moved.",
        ),
        encoding="utf-8",
    )

    evidence = audit.run_ae_artifact_export_transform_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    failed_tokens = [
        item["token_id"] for item in evidence["source_tokens"] if not item["present"]
    ]
    assert evidence["status"] == "FAIL"
    assert failed_tokens == ["markdown_only_guard"]
    assert evidence["checks"]["current_runtime_boundary_present"] is False
    assert evidence["checks"]["current_runtime_is_markdown_only"] is False
    assert "current_runtime_boundary_present" in audit.summary_line(evidence)


def test_ae_artifact_export_transform_boundary_audit_helpers_output_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_ae_artifact_export_transform_boundary_audit({})

    audit.write_audit_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        audit.assert_evidence_redacted(
            protected_env()["NEX_AE_TEST_DATABASE_URL"],
            protected_env(),
        )
    with pytest.raises(ValueError, match="local_data_path"):
        audit.assert_evidence_redacted("artifact=/data/nex-platform/ae/file", {})
    with pytest.raises(ValueError, match="database_password"):
        audit.assert_evidence_redacted("password=nuri1004", {})
    with pytest.raises(ValueError, match="provider_api_key"):
        audit.assert_evidence_redacted("provider_api_key=secret-provider-0421", {})
    with pytest.raises(ValueError, match="service_token"):
        audit.assert_evidence_redacted("token=service-token-sample", {})

    assert audit.relative_label(Path("/outside/audit.py"), tmp_path) == "audit.py"
    assert audit.path_for(tmp_path, Path("/outside/audit.py")) == Path("/outside/audit.py")
    assert audit.present_count([{"present": True}, {"present": False}]) == 1
    assert audit.present_count_bool({"a": True, "b": False}) == 1
    assert audit.gap_ready_count(
        [{"already_present": True}, {"already_present": False}]
    ) == 1
    assert audit.next_planned_slice(
        [
            {"already_present": True, "planned_slice": "Slice 0001"},
            {"already_present": False, "planned_slice": "Slice 0002"},
        ]
    ) == "Slice 0002"
    assert audit.next_planned_slice(
        [{"already_present": True, "planned_slice": "Slice 0001"}]
    ) == "complete"
    assert audit.grouped_token_status(
        [
            {"group": "ready", "present": True},
            {"group": "ready", "present": True},
            {"group": "blocked", "present": False},
        ]
    ) == {"blocked": False, "ready": True}
    assert audit.token_is_present(
        [{"token_id": "x", "present": True}, {"token_id": "y", "present": False}],
        "x",
    )
    assert not audit.token_is_present(
        [{"token_id": "x", "present": False}],
        "x",
    )
    assert audit.read_text(audit.ROOT, audit.AE_ARTIFACTS)
    assert audit.read_text(tmp_path, tmp_path / "missing.md") == ""

    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "ae_artifact_export_transform_boundary_audit=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "write_audit_evidence",
        lambda *_: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert audit.main(["--output", str(tmp_path / "blocked.json")]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_ae_artifact_export_transform_boundary_audit_main_returns_fail_for_failed_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fail_evidence = {
        "status": "FAIL",
        "checks": {"required_paths_present": False},
    }
    monkeypatch.setattr(
        audit,
        "run_ae_artifact_export_transform_boundary_audit",
        lambda: fail_evidence,
    )

    assert audit.main(["--summary"]) == 1
    assert "required_paths_present" in capsys.readouterr().out


def test_ae_artifact_export_transform_boundary_audit_quality_gate_docs_and_readmes_wired() -> None:
    quality_gate = (ROOT / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    ae_readme = (ROOT / "services" / "nex-ae-api" / "README.md").read_text(
        encoding="utf-8"
    )
    ae_web_readme = (ROOT / "apps" / "nex-ae-web" / "README.md").read_text(
        encoding="utf-8"
    )
    slice_doc = ROOT / "docs" / "slices" / "0421_ae_artifact_export_transform_boundary_audit.md"

    assert "run_ae_artifact_export_transform_boundary_audit.py --summary" in quality_gate
    assert "0421_ae_artifact_export_transform_boundary_audit.md" in docs_index
    assert "Slice 0421 audits the export/transform boundary" in ae_readme
    assert "Slice 0421 starts S43" in ae_web_readme
    assert slice_doc.exists()
