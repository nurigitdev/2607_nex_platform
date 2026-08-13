from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ae_web_credential_login_browser_execution_readiness as readiness
import run_ae_web_credential_login_browser_smoke_boundary as boundary


def protected_env() -> dict[str, str]:
    return {
        boundary.SMOKE_ENV: "1",
        boundary.PROFILE_ENV: boundary.DEFAULT_PROFILE,
        boundary.AE_WEB_URL_ENV: "http://127.0.0.1:5227",
        boundary.AE_API_BASE_URL_ENV: "http://127.0.0.1:8003",
        boundary.AE_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_ae_user:secret-pass-0264@127.0.0.1:5432/nex_ae_test"
        ),
        boundary.OA_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_oa_user:secret-pass-0264@127.0.0.1:5432/nex_oa_test"
        ),
        boundary.TENANT_ID_ENV: "tenant-slice-0264",
        boundary.EMPLOYEE_ID_ENV: "EMP-0264",
        boundary.PASSWORD_ENV: "browser-secret-0264",
    }


def test_execution_readiness_passes_by_default_without_live_db_connection() -> None:
    evidence = readiness.run_ae_web_credential_login_browser_execution_readiness({})

    assert evidence["status"] == "PASS"
    assert evidence["boundary"]["status"] == "SKIPPED"
    assert evidence["execution_plan"]["execution_slice"] == "Slice 0265"
    assert evidence["execution_plan"]["postgres_hardening_slice"] == "Slice 0266"
    assert evidence["execution_plan"]["must_connect_test_databases_when_smoke_enabled"] == [
        boundary.AE_DATABASE_URL_ENV,
        boundary.OA_DATABASE_URL_ENV,
    ]
    assert evidence["dependencies"]["playwright_required_for_current_runner"] is False
    assert evidence["checks"]["playwright_dependency_deferred"] is True
    assert all(item["present"] for item in evidence["paths"])
    assert all(item["present"] for item in evidence["anchors"])
    assert readiness.summary_line(evidence).startswith(
        "ae_web_credential_login_browser_execution_readiness=pass "
    )


def test_execution_readiness_fails_when_enabled_boundary_is_invalid() -> None:
    evidence = readiness.run_ae_web_credential_login_browser_execution_readiness(
        {boundary.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["boundary"]["status"] == "FAIL"
    assert evidence["checks"]["boundary_not_failed"] is False
    assert "boundary_not_failed" in readiness.summary_line(evidence)


def test_execution_readiness_passes_with_protected_env_without_leaking_values() -> None:
    env = protected_env()

    evidence = readiness.run_ae_web_credential_login_browser_execution_readiness(env)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert evidence["boundary"]["status"] == "PASS"
    assert "secret-pass-0264" not in serialized
    assert "browser-secret-0264" not in serialized
    assert env[boundary.AE_DATABASE_URL_ENV] not in serialized
    assert env[boundary.OA_DATABASE_URL_ENV] not in serialized


def test_execution_readiness_reports_missing_paths_anchors_and_wiring(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing.py"
    monkeypatch.setattr(
        readiness,
        "REQUIRED_PATHS",
        (
            readiness.ReadinessPath(
                "missing_runner",
                missing_path,
                "Missing path for regression coverage.",
            ),
        ),
    )

    evidence = readiness.run_ae_web_credential_login_browser_execution_readiness(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["paths"] == [
        {
            "name": "missing_runner",
            "path": "missing.py",
            "present": False,
            "purpose": "Missing path for regression coverage.",
        }
    ]
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["credential_login_anchors_present"] is False
    assert evidence["checks"]["quality_gate_wired"] is False
    assert evidence["checks"]["package_script_wired"] is False


def test_execution_readiness_reports_missing_node_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(readiness.shutil, "which", lambda command: None)

    evidence = readiness.run_ae_web_credential_login_browser_execution_readiness(
        {},
        node_command="node-missing",
    )

    assert evidence["status"] == "FAIL"
    assert evidence["dependencies"]["node_available"] is False
    assert evidence["checks"]["node_available"] is False


def test_execution_readiness_redaction_and_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env = protected_env()
    monkeypatch.setattr(readiness, "assert_boundary_evidence_redacted", lambda *_: None)

    with pytest.raises(ValueError, match=boundary.EMPLOYEE_ID_ENV):
        readiness.assert_readiness_evidence_redacted(
            f"leaked {env[boundary.EMPLOYEE_ID_ENV]}",
            env,
        )

    evidence = readiness.run_ae_web_credential_login_browser_execution_readiness({})
    output_path = tmp_path / "readiness" / "evidence.json"
    readiness.write_readiness_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"
    assert readiness.relative_label(Path("/outside/readiness.py"), tmp_path) == (
        "readiness.py"
    )


def test_execution_readiness_main_summary_output_and_redaction_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "evidence.json"

    assert readiness.main(["--summary", "--output", str(output_path)]) == 0
    assert "ae_web_credential_login_browser_execution_readiness=pass" in (
        capsys.readouterr().out
    )
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    assert readiness.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        readiness,
        "write_readiness_evidence",
        lambda *_: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert readiness.main(["--output", str(tmp_path / "blocked.json")]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_execution_readiness_checker_is_quality_gate_and_docs_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0264_ae_web_credential_login_browser_execution_readiness.md"
    ).read_text(encoding="utf-8")

    assert "run_ae_web_credential_login_browser_execution_readiness.py --summary" in (
        quality_gate
    )
    assert "0264_ae_web_credential_login_browser_execution_readiness.md" in docs_index
    assert readiness.SCHEMA_VERSION in slice_doc
    assert "Slice 0265" in slice_doc
    assert "Slice 0266" in slice_doc
