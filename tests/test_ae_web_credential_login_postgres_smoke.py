from __future__ import annotations

import json

import pytest

import run_ae_web_credential_login_postgres_smoke as smoke


def source_pass_evidence() -> dict[str, object]:
    return {
        "smoke_schema_version": "ae_credential_login_postgres_smoke.v1",
        "status": "PASS",
        "profile": "test",
        "services": ["nex-ae-api", "nex-oa"],
        "database_envs": {
            "ae": "NEX_AE_TEST_DATABASE_URL",
            "oa": "NEX_OA_TEST_DATABASE_URL",
        },
        "redacted_database_urls": {
            "ae": "postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test",
            "oa": "postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test",
        },
        "migrations": {
            "ae": {"planned_count": 1},
            "oa": {"planned_count": 2},
        },
        "request_id": "request-a",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "db_observations": {
            "ae_marker_rows": 1,
            "oa_credential_count": 1,
            "oa_session_count": 1,
            "oa_session_status": "REVOKED",
        },
        "credential_login_observations": {
            "ae_endpoint": "POST /api/v1/auth/session/login",
            "oa_endpoint": "POST /internal/v1/auth/user-login",
            "oa_client_operations": [
                "login_with_credentials",
                "introspect_session",
                "revoke_session",
            ],
            "password_verified": True,
            "browser_cookie_value_kind": "opaque_oa_session_id",
            "browser_cookie_material_in_evidence": False,
            "owner_scope_authority": "claim",
        },
        "checks": {
            "credential_status_ok": True,
            "login_status_ok": True,
            "login_password_verified": True,
            "credential_persisted": True,
            "session_persisted": True,
            "raw_payload_absent": True,
        },
        "cleanup_observations": {
            "oa_rows": {"deleted_credentials": 1, "deleted_sessions": 1}
        },
    }


def test_ae_web_credential_login_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_ae_web_credential_login_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.summary_line(evidence) == (
        "ae_web_credential_login_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ae_web_credential_login_postgres_smoke_maps_source_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_env: dict[str, str] = {}

    def fake_source(environ: dict[str, str]) -> dict[str, object]:
        captured_env.update(environ)
        return source_pass_evidence()

    monkeypatch.setattr(smoke, "run_ae_credential_login_postgres_smoke", fake_source)
    env = {
        smoke.SMOKE_ENV: "1",
        smoke.SMOKE_PROFILE_ENV: "test",
        smoke.TENANT_ID_ENV: "tenant-secret-smoke",
        smoke.SUBJECT_ID_ENV: "subject-secret-smoke",
        smoke.EMPLOYEE_ID_ENV: "EMP-SECRET-SMOKE",
        smoke.AE_DATABASE_ENV: (
            "postgresql+psycopg://nex_ae_user:nuri1004@127.0.0.1:5432/nex_ae_test"
        ),
        smoke.OA_DATABASE_ENV: (
            "postgresql+psycopg://nex_oa_user:nuri1004@127.0.0.1:5432/nex_oa_test"
        ),
    }

    evidence = smoke.run_ae_web_credential_login_postgres_smoke(env)
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)

    assert captured_env["NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE"] == "1"
    assert captured_env["NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE_PROFILE"] == "test"
    assert captured_env["NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE_TENANT_ID"] == (
        "tenant-secret-smoke"
    )
    assert evidence["status"] == "PASS"
    assert evidence["services"] == ["nex-ae-web", "nex-ae-api", "nex-oa"]
    assert evidence["web_surface"]["missing_anchor_count"] == 0
    assert evidence["web_surface"]["credential_payload_builder_present"] is True
    assert evidence["route_guard_observations"] == {
        "schema_version": "ae_web_session_route_guard.v1",
        "guard_status_after_login": "allowed",
        "owner_scope_source_after_login": "session-claims",
        "protected_route_count": 4,
        "browser_payload_owner_authoritative": False,
    }
    assert evidence["checks"]["web_login_surface_present"] is True
    assert evidence["checks"]["web_password_not_stored"] is True
    assert "nuri1004" not in serialized
    assert "tenant-secret-smoke" not in serialized
    assert "subject-secret-smoke" not in serialized
    assert "EMP-SECRET-SMOKE" not in serialized
    assert smoke.summary_line(evidence) == (
        "ae_web_credential_login_postgres_smoke=pass "
        "profile=test "
        "ae_db=NEX_AE_TEST_DATABASE_URL "
        "oa_db=NEX_OA_TEST_DATABASE_URL "
        "route_guard=allowed "
        "oa_credential_count=1 "
        "oa_session_status=REVOKED"
    )


def test_ae_web_credential_login_postgres_smoke_maps_source_non_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_ae_credential_login_postgres_smoke",
        lambda environ: {
            "smoke_schema_version": "ae_credential_login_postgres_smoke.v1",
            "status": "FAIL",
            "profile": "test",
            "services": ["nex-ae-api", "nex-oa"],
            "failure_code": "configuration_invalid",
            "detail": "missing database URL env",
        },
    )

    failed = smoke.run_ae_web_credential_login_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert failed["status"] == "FAIL"
    assert failed["failure_code"] == "configuration_invalid"
    assert smoke.summary_line(failed) == (
        "ae_web_credential_login_postgres_smoke=fail reason=configuration_invalid"
    )

    monkeypatch.setattr(
        smoke,
        "run_ae_credential_login_postgres_smoke",
        lambda environ: {
            "smoke_schema_version": "ae_credential_login_postgres_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "source disabled",
        },
    )

    skipped = smoke.run_ae_web_credential_login_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert skipped["status"] == "SKIPPED"
    assert skipped["skip_reason"] == "source disabled"


def test_ae_web_credential_login_postgres_smoke_redaction_and_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(ValueError, match=smoke.AE_DATABASE_ENV):
        smoke.assert_smoke_evidence_redacted(
            "postgresql+psycopg://nex_ae_user:nuri1004@127.0.0.1:5432/nex_ae_test",
            {
                smoke.AE_DATABASE_ENV: (
                    "postgresql+psycopg://nex_ae_user:nuri1004@127.0.0.1:5432/nex_ae_test"
                )
            },
        )

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_web_credential_login_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert "ae_web_credential_login_postgres_smoke=skipped" in capsys.readouterr().out

    assert smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out
