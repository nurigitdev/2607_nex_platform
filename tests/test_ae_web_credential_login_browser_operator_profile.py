from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ae_web_credential_login_browser_operator_profile as smoke
import run_ae_web_credential_login_browser_smoke_boundary as boundary


def protected_env() -> dict[str, str]:
    return {
        boundary.SMOKE_ENV: "1",
        boundary.PROFILE_ENV: boundary.DEFAULT_PROFILE,
        boundary.AE_WEB_URL_ENV: "http://127.0.0.1:5227",
        boundary.AE_API_BASE_URL_ENV: "http://127.0.0.1:8003",
        boundary.AE_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_ae_user:secret-pass-0267@127.0.0.1:5432/nex_ae_test"
        ),
        boundary.OA_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_oa_user:secret-pass-0267@127.0.0.1:5432/nex_oa_test"
        ),
        boundary.TENANT_ID_ENV: "tenant-slice-0267",
        boundary.EMPLOYEE_ID_ENV: "EMP-0267",
        boundary.PASSWORD_ENV: "browser-secret-0267",
    }


def test_operator_profile_passes_in_default_mode() -> None:
    evidence = smoke.run_ae_web_credential_login_browser_operator_profile({})

    assert evidence["status"] == "PASS"
    assert evidence["mode"] == "default"
    assert evidence["checks"]["default_mode_skips_live_db"] is True
    assert evidence["checks"]["protected_mode_env_ready"] is True
    assert all(item["status"] == "deferred" for item in evidence["env"])
    assert smoke.summary_line(evidence) == (
        "ae_web_credential_login_browser_operator_profile=pass "
        "mode=default env=0/7 order=3"
    )


def test_operator_profile_validates_protected_env_without_leaking_values() -> None:
    env = protected_env()
    evidence = smoke.run_ae_web_credential_login_browser_operator_profile(env)
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)

    assert evidence["status"] == "PASS"
    assert evidence["mode"] == "protected"
    assert evidence["checks"]["default_mode_skips_live_db"] is True
    assert evidence["checks"]["protected_mode_env_ready"] is True
    assert not evidence["issues"]
    assert "secret-pass-0267" not in serialized
    assert "browser-secret-0267" not in serialized
    assert "tenant-slice-0267" not in serialized
    assert smoke.summary_line(evidence) == (
        "ae_web_credential_login_browser_operator_profile=pass "
        "mode=protected env=7/7 order=3"
    )


def test_operator_profile_reports_missing_env_and_non_test_database() -> None:
    env = {
        boundary.SMOKE_ENV: "1",
        boundary.AE_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_ae_user:secret@127.0.0.1:5432/nex_ae_dev"
        ),
        boundary.OA_DATABASE_URL_ENV: "://bad",
    }

    evidence = smoke.run_ae_web_credential_login_browser_operator_profile(env)

    assert evidence["status"] == "FAIL"
    statuses = {item["name"]: item["status"] for item in evidence["env"]}
    assert statuses[boundary.AE_DATABASE_URL_ENV] == "database_not_test"
    assert statuses[boundary.OA_DATABASE_URL_ENV] == "database_not_test"
    assert statuses[boundary.PASSWORD_ENV] == "required_env_missing"
    assert evidence["checks"]["test_database_guard"] is False


def test_operator_profile_reports_non_test_profile() -> None:
    env = protected_env()
    env[boundary.PROFILE_ENV] = "dev"

    evidence = smoke.run_ae_web_credential_login_browser_operator_profile(env)

    assert evidence["status"] == "FAIL"
    assert any(
        issue["category"] == "profile_not_allowed"
        for issue in evidence["issues"]
    )


def test_operator_profile_detects_missing_docs_and_quality_wiring(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs" / "runbooks").mkdir(parents=True)
    (tmp_path / "docs" / "runbooks" / smoke.RUNBOOK_PATH.name).write_text(
        "incomplete runbook",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "smoke").mkdir(parents=True)
    (tmp_path / "scripts" / "quality").mkdir(parents=True)
    (tmp_path / "scripts" / "quality" / smoke.QUALITY_GATE_PATH.name).write_text(
        "missing commands",
        encoding="utf-8",
    )

    evidence = smoke.run_ae_web_credential_login_browser_operator_profile(
        {},
        root_dir=tmp_path,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["paths_present"] is False
    assert evidence["checks"]["runbook_complete"] is False
    assert evidence["checks"]["quality_gate_wired"] is False


def test_operator_profile_redaction_output_and_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = protected_env()
    evidence = smoke.run_ae_web_credential_login_browser_operator_profile({})
    output_path = tmp_path / "profile.json"

    smoke.write_operator_profile_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    with pytest.raises(ValueError, match=boundary.PASSWORD_ENV):
        smoke.assert_operator_profile_evidence_redacted(
            f"leaked {env[boundary.PASSWORD_ENV]}",
            env,
        )
    monkeypatch.setattr(smoke, "assert_boundary_evidence_redacted", lambda *_: None)
    with pytest.raises(ValueError, match=boundary.EMPLOYEE_ID_ENV):
        smoke.assert_operator_profile_evidence_redacted(
            f"leaked {env[boundary.EMPLOYEE_ID_ENV]}",
            env,
        )
    assert smoke._is_test_database_url(
        "postgresql+psycopg://user:secret@127.0.0.1:5432/example_test"
    )
    assert not smoke._is_test_database_url(
        "postgresql+psycopg://user:secret@127.0.0.1:5432/example_dev"
    )
    assert not smoke._is_test_database_url("://bad")
    assert smoke._relative_label(Path("/tmp/outside.txt")) == "outside.txt"

    monkeypatch.setenv(boundary.PASSWORD_ENV, env[boundary.PASSWORD_ENV])
    with pytest.raises(ValueError, match=boundary.PASSWORD_ENV):
        smoke.write_operator_profile_evidence(output_path, {"leak": env[boundary.PASSWORD_ENV]})


def test_operator_profile_main_summary_output_and_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "evidence.json"
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_web_credential_login_browser_operator_profile",
        lambda: {
            "profile_schema_version": smoke.SCHEMA_VERSION,
            "status": "PASS",
            "mode": "default",
            "env": [],
            "execution_order": ["operator_profile", "live_smoke", "hardening"],
        },
    )

    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert "operator_profile=pass mode=default" in capsys.readouterr().out
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_ae_web_credential_login_browser_operator_profile",
        lambda: {
            "profile_schema_version": smoke.SCHEMA_VERSION,
            "status": "FAIL",
            "mode": "protected",
            "issues": [{"category": "x"}],
        },
    )
    assert smoke.main(["--summary"]) == 1
    assert "issues=1" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_credential_login_browser_operator_profile",
        lambda: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert smoke.main([]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_operator_profile_is_quality_gate_and_docs_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    ae_web_readme = (root / "apps" / "nex-ae-web" / "README.md").read_text(
        encoding="utf-8"
    )
    runbook = (
        root / "docs" / "runbooks" / "ae_web_credential_login_browser_smoke.md"
    ).read_text(encoding="utf-8")
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0267_ae_web_credential_login_browser_operator_profile.md"
    )

    assert "run_ae_web_credential_login_browser_operator_profile.py --summary" in (
        quality_gate
    )
    assert "0267_ae_web_credential_login_browser_operator_profile.md" in docs_index
    assert "Slice 0267" in ae_web_readme
    assert "run_ae_web_credential_login_browser_postgres_evidence_hardening.py" in (
        runbook
    )
    assert slice_doc.exists()
