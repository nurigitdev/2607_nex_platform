from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_cx_source_file_materialization_boundary_audit as audit


def protected_env() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0275@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_cx_user:secret-0275@127.0.0.1:5432/nex_cx_test"
        ),
        "NEX_OA_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_oa_user:secret-0275@127.0.0.1:5432/nex_oa_test"
        ),
        "NEX_DATA_ROOT": "/data/nex-platform/private-secret-0275",
        "NEX_CX_SOURCE_STORAGE_ROOT": (
            "/data/nex-platform/private-secret-0275/cx/source-files"
        ),
        "NEX_AE_WEB_AUTHENTICATED_UPLOAD_PLAYWRIGHT_SMOKE_PASSWORD": (
            "browser-secret-0275"
        ),
    }


def test_source_file_materialization_boundary_audit_passes_on_current_repo() -> None:
    evidence = audit.run_cx_source_file_materialization_boundary_audit({})

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["decisions"]["source_file_system_of_record"] == "nex-cx"
    assert evidence["decisions"]["ae_long_term_source_storage"] == "forbidden"
    assert evidence["decisions"]["browser_to_ae_transport_next"] == (
        "multipart_form_data"
    )
    assert evidence["decisions"]["ae_to_cx_transport_near_term"] == (
        "service_authenticated_content_base64_json"
    )
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["source_tokens"])
    assert all(item["blocking"] is False for item in evidence["planned_gaps"])
    assert evidence["checks"]["redacted_evidence_only"] is True
    assert audit.summary_line(evidence).startswith(
        "cx_source_file_materialization_boundary_audit=pass "
    )


def test_source_file_materialization_boundary_audit_does_not_leak_protected_values() -> None:
    env = protected_env()

    evidence = audit.run_cx_source_file_materialization_boundary_audit(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "/data/nex-platform" not in serialized
    assert "secret-0275" not in serialized
    assert "browser-secret-0275" not in serialized
    assert env["NEX_CX_TEST_DATABASE_URL"] not in serialized
    assert env["NEX_CX_SOURCE_STORAGE_ROOT"] not in serialized


def test_source_file_materialization_boundary_audit_reports_missing_static_boundaries(
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
                "cx_storage_config",
                missing,
                "missing-token",
                "missing token value",
                "Missing token for regression coverage.",
            ),
        ),
    )

    evidence = audit.run_cx_source_file_materialization_boundary_audit(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["cx_storage_config_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "required_paths_present" in audit.summary_line(evidence)


def test_source_file_materialization_boundary_audit_helpers_output_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "audit" / "evidence.json"
    evidence = audit.run_cx_source_file_materialization_boundary_audit({})

    audit.write_audit_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    with pytest.raises(ValueError, match="NEX_CX_TEST_DATABASE_URL"):
        audit.assert_evidence_redacted(
            "postgresql+psycopg://nex_cx_user:secret-0275@127.0.0.1:5432/nex_cx_test",
            protected_env(),
        )
    with pytest.raises(ValueError, match="local data path"):
        audit.assert_evidence_redacted("source=/data/nex-platform/cx/file", {})

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

    assert audit.main(["--summary", "--output", str(output_path)]) == 0
    assert "cx_source_file_materialization_boundary_audit=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "write_audit_evidence",
        lambda *_: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert audit.main(["--output", str(tmp_path / "blocked.json")]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_source_file_materialization_boundary_audit_quality_gate_docs_and_readme_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    cx_readme = (root / "services" / "nex-cx" / "README.md").read_text(
        encoding="utf-8"
    )
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0275_cx_source_file_materialization_boundary_audit.md"
    )

    assert "run_cx_source_file_materialization_boundary_audit.py --summary" in quality_gate
    assert "0275_cx_source_file_materialization_boundary_audit.md" in docs_index
    assert "Slice 0275" in cx_readme
    assert slice_doc.exists()
