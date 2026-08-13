from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ae_web_credential_login_browser_smoke_boundary as boundary


def protected_env() -> dict[str, str]:
    return {
        boundary.SMOKE_ENV: "1",
        boundary.PROFILE_ENV: boundary.DEFAULT_PROFILE,
        boundary.AE_WEB_URL_ENV: "http://127.0.0.1:5227",
        boundary.AE_API_BASE_URL_ENV: "http://127.0.0.1:8003",
        boundary.AE_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_ae_user:secret-pass-0262@127.0.0.1:5432/nex_ae_test"
        ),
        boundary.OA_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_oa_user:secret-pass-0262@127.0.0.1:5432/nex_oa_test"
        ),
        boundary.TENANT_ID_ENV: "tenant-slice-0262",
        boundary.EMPLOYEE_ID_ENV: "EMP-0262",
        boundary.PASSWORD_ENV: "browser-secret-0262",
    }


def test_boundary_skips_by_default_but_keeps_execution_contract() -> None:
    evidence = boundary.run_ae_web_credential_login_browser_smoke_boundary({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["boundary"]["next_execution_slice"] == "Slice 0263"
    assert evidence["evidence_requirements"]["must_attempt_postgresql_connections"] == [
        boundary.AE_DATABASE_URL_ENV,
        boundary.OA_DATABASE_URL_ENV,
    ]
    assert evidence["evidence_requirements"]["must_prove_oa_credential_login"] is True
    assert evidence["evidence_requirements"]["must_prove_ae_cookie_session_facade"] is True
    assert len(evidence["required_env"]) == len(boundary.REQUIRED_ENV_SPECS)
    assert len(evidence["required_phases"]) == len(boundary.REQUIRED_PHASES)
    assert boundary.summary_line(evidence) == (
        "ae_web_credential_login_browser_boundary=skipped "
        f"reason={boundary.SMOKE_ENV} boundary=pass "
        f"phases={len(boundary.REQUIRED_PHASES)}"
    )


def test_boundary_fails_when_enabled_without_required_test_inputs() -> None:
    evidence = boundary.run_ae_web_credential_login_browser_smoke_boundary(
        {boundary.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert {issue["env"] for issue in evidence["issues"]} == {
        spec.name for spec in boundary.REQUIRED_ENV_SPECS
    }
    assert boundary.summary_line(evidence) == (
        "ae_web_credential_login_browser_boundary=fail "
        f"issues={len(evidence['issues'])}"
    )


def test_boundary_rejects_non_test_profile() -> None:
    env = protected_env()
    env[boundary.PROFILE_ENV] = "dev"

    evidence = boundary.run_ae_web_credential_login_browser_smoke_boundary(env)

    assert evidence["status"] == "FAIL"
    assert evidence["issues"][0] == {
        "error_code": "profile_not_allowed",
        "detail": f"{boundary.PROFILE_ENV} must be test.",
        "env": boundary.PROFILE_ENV,
    }


def test_boundary_passes_with_protected_env_and_safe_browser_config() -> None:
    env = protected_env()
    browser_config = {
        "config_schema_version": "ae_web_runtime_config.v1",
        "client_mode": "fetch",
        "ae_base_url": "/ae-api",
        "features": {"fetch_clients_enabled": True},
        "session_route": "/api/v1/auth/session",
        "login_route": "/api/v1/auth/session/login",
        "logout_route": "/api/v1/auth/session/logout",
    }

    evidence = boundary.run_ae_web_credential_login_browser_smoke_boundary(
        env,
        browser_config=browser_config,
    )

    serialized = json.dumps(evidence, ensure_ascii=False)
    assert evidence["status"] == "PASS"
    assert evidence["browser_runtime_contract"]["provided"] is True
    assert evidence["browser_routes"] == list(boundary.REQUIRED_BROWSER_ROUTES)
    assert evidence["issues"] == []
    assert all(item["configured"] for item in evidence["required_env"])
    assert "secret-pass-0262" not in serialized
    assert "browser-secret-0262" not in serialized
    assert env[boundary.AE_DATABASE_URL_ENV] not in serialized
    assert env[boundary.OA_DATABASE_URL_ENV] not in serialized
    assert "ae_web_credential_login_browser_boundary=pass profile=test env=7/7" in (
        boundary.summary_line(evidence)
    )


def test_boundary_rejects_server_only_browser_config_keys() -> None:
    browser_config = {
        "config_schema_version": "ae_web_runtime_config.v1",
        "api-key": "should-not-render",
        "database_url": "postgresql://should-not-render",
        "password": "should-not-render",
        "features": {
            "fetch_clients_enabled": True,
            "providerUrl": "http://dgx.example.test",
        },
        "nested": [{"sessionCookie": "raw-cookie"}],
    }

    evidence = boundary.run_ae_web_credential_login_browser_smoke_boundary(
        {},
        browser_config=browser_config,
    )

    assert evidence["status"] == "FAIL"
    assert {
        "browser_config_top_level_key_unsupported",
        "browser_config_key_server_only",
        "browser_config_nested_key_server_only",
    }.issubset({issue["error_code"] for issue in evidence["issues"]})
    assert "features.providerUrl" in {issue["field"] for issue in evidence["issues"]}
    assert "nested[0].sessionCookie" in {
        issue["field"] for issue in evidence["issues"]
    }
    assert "api-key" in {issue["field"] for issue in evidence["issues"]}
    assert "password" in {issue["field"] for issue in evidence["issues"]}


def test_boundary_loads_browser_config_from_json_and_path(tmp_path: Path) -> None:
    config = {"config_schema_version": "ae_web_runtime_config.v1"}
    config_path = tmp_path / "browser-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    assert boundary.load_browser_config_json(json.dumps(config)) == config
    assert boundary.load_browser_config_path(config_path) == config
    assert boundary.load_browser_config_json(None) is None
    assert boundary.load_browser_config_path(None) is None
    with pytest.raises(ValueError):
        boundary.load_browser_config_json("[]")
    with pytest.raises(ValueError):
        bad_path = tmp_path / "bad-browser-config.json"
        bad_path.write_text("[]", encoding="utf-8")
        boundary.load_browser_config_path(bad_path)


def test_boundary_redaction_guard_rejects_leaked_env_values() -> None:
    env = protected_env()

    with pytest.raises(ValueError, match=boundary.PASSWORD_ENV):
        boundary.assert_boundary_evidence_redacted(
            f"leaked {env[boundary.PASSWORD_ENV]}",
            env,
        )


def test_boundary_write_evidence_rechecks_redaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env = protected_env()
    monkeypatch.setenv(boundary.PASSWORD_ENV, env[boundary.PASSWORD_ENV])
    evidence = boundary.run_ae_web_credential_login_browser_smoke_boundary(env)
    output_path = tmp_path / "evidence" / "boundary.json"

    boundary.write_boundary_evidence(output_path, evidence)

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["status"] == "PASS"

    with pytest.raises(ValueError):
        boundary.write_boundary_evidence(
            tmp_path / "bad.json",
            {"status": "FAIL", "detail": env[boundary.PASSWORD_ENV]},
        )


def test_boundary_main_handles_summary_output_and_bad_inputs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(boundary.SMOKE_ENV, raising=False)

    assert boundary.main(["--summary"]) == 0
    assert "ae_web_credential_login_browser_boundary=skipped" in (
        capsys.readouterr().out
    )

    assert boundary.main(["--browser-config-json", "[]", "--summary"]) == 1
    assert "error=ValueError" in capsys.readouterr().out

    config_path = tmp_path / "safe-config.json"
    config_path.write_text('{"config_schema_version": "ae_web_runtime_config.v1"}')
    output_path = tmp_path / "boundary.json"
    assert boundary.main(
        [
            "--browser-config-path",
            str(config_path),
            "--output",
            str(output_path),
        ]
    ) == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "SKIPPED"

    assert boundary.main(
        [
            "--browser-config-json",
            '{"config_schema_version": "ae_web_runtime_config.v1"}',
            "--browser-config-path",
            str(config_path),
        ]
    ) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_boundary_checker_is_quality_gate_and_docs_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0262_ae_web_credential_login_browser_smoke_boundary.md"
    ).read_text(encoding="utf-8")

    assert "run_ae_web_credential_login_browser_smoke_boundary.py --summary" in (
        quality_gate
    )
    assert "0262_ae_web_credential_login_browser_smoke_boundary.md" in docs_index
    assert boundary.SMOKE_ENV in slice_doc
    assert boundary.AE_DATABASE_URL_ENV in slice_doc
    assert boundary.OA_DATABASE_URL_ENV in slice_doc
