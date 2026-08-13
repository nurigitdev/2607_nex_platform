from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ae_credential_login_postgres_smoke as credential_smoke
import run_ae_web_credential_login_browser_live_smoke as smoke
import run_ae_web_credential_login_browser_smoke_boundary as boundary


def protected_env() -> dict[str, str]:
    return {
        boundary.SMOKE_ENV: "1",
        boundary.PROFILE_ENV: boundary.DEFAULT_PROFILE,
        boundary.AE_WEB_URL_ENV: "http://127.0.0.1:5227",
        boundary.AE_API_BASE_URL_ENV: "http://127.0.0.1:8003",
        boundary.AE_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_ae_user:secret-pass-0265@127.0.0.1:5432/nex_ae_test"
        ),
        boundary.OA_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_oa_user:secret-pass-0265@127.0.0.1:5432/nex_oa_test"
        ),
        boundary.TENANT_ID_ENV: "tenant-slice-0265",
        boundary.EMPLOYEE_ID_ENV: "EMP-0265",
        boundary.PASSWORD_ENV: "browser-secret-0265",
    }


def readiness_pass() -> dict[str, object]:
    return {
        "readiness_schema_version": (
            "ae_web_credential_login_browser_execution_readiness.v1"
        ),
        "status": "PASS",
    }


def credential_pass_evidence() -> dict[str, object]:
    return {
        "smoke_schema_version": "ae_credential_login_postgres_smoke.v1",
        "status": "PASS",
        "profile": "test",
        "services": ["nex-ae-api", "nex-oa"],
        "database_envs": {
            "ae": boundary.AE_DATABASE_URL_ENV,
            "oa": boundary.OA_DATABASE_URL_ENV,
        },
        "redacted_database_urls": {
            "ae": "postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test",
            "oa": "postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test",
        },
        "migrations": {
            "ae": {"planned_count": 3, "skipped_count": 3},
            "oa": {"planned_count": 5, "skipped_count": 5},
        },
        "request_id": "request-0265",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "db_observations": {
            "ae_marker_rows": 1,
            "oa_credential_count": 1,
            "oa_session_count": 1,
            "oa_session_status": "REVOKED",
            "oa_session_revoked_at_present": True,
        },
        "credential_login_observations": {
            "ae_endpoint": "POST /api/v1/auth/session/login",
            "oa_endpoint": "POST /internal/v1/auth/user-login",
            "oa_client_operations": [
                "login_with_credentials",
                "introspect_session",
                "introspect_session",
                "revoke_session",
                "introspect_session",
            ],
            "password_verified": True,
            "browser_cookie_value_kind": "opaque_oa_session_id",
            "browser_cookie_material_in_evidence": False,
            "owner_scope_authority": "claim",
        },
        "checks": {
            "cookie_set_after_login": True,
            "cookie_removed_after_logout": True,
            "protected_owner_scope_claim_derived": True,
            "db_session_revoked": True,
        },
        "cleanup_observations": {
            "oa_rows": {"deleted_credentials": 1, "deleted_sessions": 1}
        },
    }


def harness_pass_evidence() -> dict[str, object]:
    return {
        "smoke_schema_version": (
            "ae_web_credential_login_browser_harness_smoke_runner.v1"
        ),
        "status": "PASS",
        "harness": {
            "mode": "deterministic_fake_fetch",
            "route_guard_status": "allowed",
            "fetch_call_count": 3,
            "login_route": "/api/v1/auth/session/login",
            "current_session_status": "anonymous",
            "authenticated_session_status": "authenticated",
            "logout_session_status": "anonymous",
        },
        "checks": {
            "route_guard_allowed": True,
            "logout_returns_anonymous": True,
        },
    }


def test_browser_live_smoke_skips_by_default() -> None:
    evidence = smoke.run_ae_web_credential_login_browser_live_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.summary_line(evidence) == (
        "ae_web_credential_login_browser_live_smoke=skipped "
        f"reason={boundary.SMOKE_ENV}"
    )


def test_browser_live_smoke_credential_env_defaults_without_optional_aliases() -> None:
    credential_env = smoke._credential_environ({})

    assert credential_env[credential_smoke.SMOKE_ENV] == "1"
    assert credential_smoke.TENANT_ID_ENV not in credential_env
    assert credential_smoke.EMPLOYEE_ID_ENV not in credential_env
    assert credential_smoke.PASSWORD_ENV not in credential_env


def test_browser_live_smoke_runs_readiness_credential_and_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_credential_env: dict[str, str] = {}
    captured_harness_env: dict[str, str] = {}
    env = protected_env()

    def fake_credential(environ: dict[str, str]) -> dict[str, object]:
        captured_credential_env.update(environ)
        return credential_pass_evidence()

    def fake_harness(environ: dict[str, str]) -> dict[str, object]:
        captured_harness_env.update(environ)
        return harness_pass_evidence()

    evidence = smoke.run_ae_web_credential_login_browser_live_smoke(
        env,
        readiness_runner=lambda environ: readiness_pass(),
        credential_runner=fake_credential,
        harness_runner=fake_harness,
    )
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)

    assert captured_credential_env[credential_smoke.SMOKE_ENV] == "1"
    assert captured_credential_env[credential_smoke.SMOKE_PROFILE_ENV] == "test"
    assert captured_credential_env[credential_smoke.TENANT_ID_ENV] == (
        "tenant-slice-0265"
    )
    assert captured_credential_env[credential_smoke.EMPLOYEE_ID_ENV] == "EMP-0265"
    assert captured_credential_env[credential_smoke.PASSWORD_ENV] == (
        "browser-secret-0265"
    )
    assert captured_harness_env[boundary.SMOKE_ENV] == "1"
    assert captured_harness_env[boundary.PASSWORD_ENV] == "browser-secret-0265"
    assert evidence["status"] == "PASS"
    assert evidence["services"] == ["nex-ae-web", "nex-ae-api", "nex-oa"]
    assert evidence["checks"]["actual_test_database_smoke_executed"] is True
    assert evidence["checks"]["ae_test_database_connected"] is True
    assert evidence["checks"]["oa_test_database_connected"] is True
    assert evidence["checks"]["route_guard_allowed"] is True
    assert evidence["credential_login_observations"]["password_verified"] is True
    assert evidence["browser_harness_observations"]["route_guard_status"] == "allowed"
    assert "browser-secret-0265" not in serialized
    assert "secret-pass-0265" not in serialized
    assert "tenant-slice-0265" not in serialized
    assert "EMP-0265" not in serialized
    assert smoke.summary_line(evidence) == (
        "ae_web_credential_login_browser_live_smoke=pass "
        "profile=test "
        "ae_db=NEX_AE_TEST_DATABASE_URL "
        "oa_db=NEX_OA_TEST_DATABASE_URL "
        "route_guard=allowed "
        "oa_session_status=REVOKED "
        "live_db=true"
    )

    output_path = tmp_path / "smoke" / "0265.json"
    monkeypatch.setenv(boundary.PASSWORD_ENV, env[boundary.PASSWORD_ENV])
    smoke.write_live_smoke_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"


def test_browser_live_smoke_fails_before_children_when_boundary_invalid() -> None:
    def forbidden_child(environ: dict[str, str]) -> dict[str, object]:
        raise AssertionError("children must not run")

    evidence = smoke.run_ae_web_credential_login_browser_live_smoke(
        {boundary.SMOKE_ENV: "1"},
        readiness_runner=forbidden_child,
        credential_runner=forbidden_child,
        harness_runner=forbidden_child,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "boundary_invalid"
    assert evidence["source_smokes"]["boundary"]["status"] == "FAIL"
    assert evidence["source_smokes"]["credential_postgres"]["status"] == "NOT_RUN"


def test_browser_live_smoke_maps_readiness_failure() -> None:
    env = protected_env()
    evidence = smoke.run_ae_web_credential_login_browser_live_smoke(
        env,
        readiness_runner=lambda environ: {"status": "FAIL"},
        credential_runner=lambda environ: (_ for _ in ()).throw(
            AssertionError("credential must not run")
        ),
        harness_runner=lambda environ: (_ for _ in ()).throw(
            AssertionError("harness must not run")
        ),
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "readiness_failed"
    assert evidence["checks"]["boundary_passed"] is True
    assert evidence["checks"]["readiness_passed"] is False


@pytest.mark.parametrize(
    ("source_status", "expected_reason"),
    [
        ("FAIL", "credential_postgres_fail"),
        ("SKIPPED", "credential_postgres_skipped"),
    ],
)
def test_browser_live_smoke_maps_credential_non_pass(
    source_status: str,
    expected_reason: str,
) -> None:
    env = protected_env()
    evidence = smoke.run_ae_web_credential_login_browser_live_smoke(
        env,
        readiness_runner=lambda environ: readiness_pass(),
        credential_runner=lambda environ: {
            "smoke_schema_version": "ae_credential_login_postgres_smoke.v1",
            "status": source_status,
            "failure_code": "configuration_invalid",
        },
        harness_runner=lambda environ: (_ for _ in ()).throw(
            AssertionError("harness must not run")
        ),
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == expected_reason
    assert evidence["source_smokes"]["credential_postgres"]["status"] == source_status


def test_browser_live_smoke_maps_harness_failure() -> None:
    env = protected_env()
    evidence = smoke.run_ae_web_credential_login_browser_live_smoke(
        env,
        readiness_runner=lambda environ: readiness_pass(),
        credential_runner=lambda environ: credential_pass_evidence(),
        harness_runner=lambda environ: {
            "smoke_schema_version": (
                "ae_web_credential_login_browser_harness_smoke_runner.v1"
            ),
            "status": "FAIL",
            "reason": "node_failed",
        },
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "browser_harness_fail"
    assert smoke.summary_line(evidence) == (
        "ae_web_credential_login_browser_live_smoke=fail "
        "reason=browser_harness_fail"
    )


def test_browser_live_smoke_rejects_inconsistent_pass_and_secret_leaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = protected_env()
    bad_credential = credential_pass_evidence()
    bad_credential["checks"] = {"db_session_revoked": True}

    with pytest.raises(ValueError, match="pass evidence failed"):
        smoke.run_ae_web_credential_login_browser_live_smoke(
            env,
            readiness_runner=lambda environ: readiness_pass(),
            credential_runner=lambda environ: bad_credential,
            harness_runner=lambda environ: harness_pass_evidence(),
        )

    with pytest.raises(ValueError, match=boundary.PASSWORD_ENV):
        smoke.assert_live_smoke_evidence_redacted(
            f"leaked {env[boundary.PASSWORD_ENV]}",
            env,
        )

    monkeypatch.setattr(smoke, "assert_boundary_evidence_redacted", lambda *_: None)
    with pytest.raises(ValueError, match=credential_smoke.PASSWORD_ENV):
        smoke.assert_live_smoke_evidence_redacted(
            f"leaked {env[boundary.PASSWORD_ENV]}",
            {
                credential_smoke.PASSWORD_ENV: env[boundary.PASSWORD_ENV],
            },
        )


def test_browser_live_smoke_main_summary_output_and_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "evidence.json"
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_web_credential_login_browser_live_smoke",
        lambda: {"smoke_schema_version": smoke.SCHEMA_VERSION, "status": "SKIPPED"},
    )

    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert "ae_web_credential_login_browser_live_smoke=skipped" in (
        capsys.readouterr().out
    )
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "SKIPPED"

    monkeypatch.setattr(
        smoke,
        "run_ae_web_credential_login_browser_live_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "boundary_invalid",
        },
    )
    assert smoke.main(["--summary"]) == 1
    assert "reason=boundary_invalid" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_credential_login_browser_live_smoke",
        lambda: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert smoke.main([]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_browser_live_smoke_is_quality_gate_and_docs_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    ae_web_readme = (root / "apps" / "nex-ae-web" / "README.md").read_text(
        encoding="utf-8"
    )
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0265_ae_web_credential_login_browser_live_smoke_execution.md"
    )

    assert "run_ae_web_credential_login_browser_live_smoke.py --summary" in (
        quality_gate
    )
    assert "0265_ae_web_credential_login_browser_live_smoke_execution.md" in (
        docs_index
    )
    assert "Slice 0265" in ae_web_readme
    assert slice_doc.exists()
