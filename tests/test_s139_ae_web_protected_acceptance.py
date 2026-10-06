from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import run_s139_ae_web_protected_acceptance as smoke


def _source(
    *,
    actual_postgres: bool = False,
    actual_browser: bool = False,
) -> dict[str, object]:
    return {
        "status": "PASS",
        "actual_postgres": actual_postgres,
        "actual_browser": actual_browser,
        "checks": {"source_passed": True},
        "failed_checks": [],
    }


def _runners() -> dict[str, smoke.SourceRunner]:
    return {
        "process_topology": lambda _env: _source(),
        "credential_login": lambda _env: _source(
            actual_postgres=True, actual_browser=True
        ),
        "authenticated_upload": lambda _env: _source(
            actual_postgres=True, actual_browser=True
        ),
        "grounded_artifact": lambda _env: {
            **_source(actual_postgres=True, actual_browser=True),
            "provider_mode": "deterministic_mock",
            "remote_provider_contacted": False,
            "residue": {"ae_chat": 0, "cx_jobs": 0},
        },
        "two_viewport_browser": lambda _env: {
            **_source(actual_browser=True),
            "runner": {"browser": "chromium"},
            "summary": {"viewport_count": 2},
        },
    }


def test_protected_acceptance_passes_with_all_sources() -> None:
    result = smoke.run_s139_ae_web_protected_acceptance(
        {smoke.SMOKE_ENV: "1"}, source_runners=_runners()
    )

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["database_targets"] == [
        "nex_oa_test",
        "nex_ae_test",
        "nex_cx_test",
    ]
    assert result["summary"] == {
        "source_count": 5,
        "passed_source_count": 5,
        "database_count": 3,
        "service_process_count": 13,
        "viewport_count": 2,
        "journey_stage_count": 9,
        "check_count": 9,
        "passed_check_count": 9,
    }
    assert result["decision"]["next_slice"] == "1391"


def test_disabled_invalid_profile_and_database_fail_closed() -> None:
    disabled = smoke.run_s139_ae_web_protected_acceptance({})
    assert disabled["status"] == "SKIPPED"
    assert disabled["actual_postgres"] is False

    profile = smoke.run_s139_ae_web_protected_acceptance(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )
    assert profile["failure_code"] == "profile_not_allowed"

    invalid = smoke.run_s139_ae_web_protected_acceptance(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_URLS["oa"]: "sqlite:///oa.db",
            smoke.DATABASE_URLS["ae"]: "postgresql://u:p@db/ae_dev",
            smoke.DATABASE_URLS["cx"]: "postgresql://u:p@db/cx_test",
        }
    )
    assert invalid["failure_code"] == "database_configuration_invalid"
    assert invalid["issues"] == ["oa_postgresql_required", "oa_test_database_required", "ae_test_database_required"]


def test_source_failure_exception_and_redaction_fail_closed() -> None:
    runners = _runners()
    runners["credential_login"] = lambda _env: {"status": "FAIL"}
    failed = smoke.run_s139_ae_web_protected_acceptance(
        {smoke.SMOKE_ENV: "1"}, source_runners=runners
    )
    assert failed["status"] == "FAIL"
    assert "oa_backed_browser_login_passed" in failed["failed_checks"]
    assert failed["decision"]["next_slice"] == "blocked"

    runners = _runners()

    def explode(_env: dict[str, str]) -> dict[str, object]:
        raise RuntimeError("private detail must not escape")

    runners["authenticated_upload"] = explode
    exception = smoke.run_s139_ae_web_protected_acceptance(
        {smoke.SMOKE_ENV: "1"}, source_runners=runners
    )
    assert exception["failure_code"] == "source_execution_failed"
    assert exception["detail"] == "RuntimeError"

    unsafe = _runners()
    unsafe["process_topology"] = lambda _env: {
        "status": "PASS",
        "secret": "nuri1004@",
    }
    redacted = smoke.run_s139_ae_web_protected_acceptance(
        {smoke.SMOKE_ENV: "1"}, source_runners=unsafe
    )
    assert redacted["status"] == "FAIL"
    assert "source_evidence_redacted" in redacted["failed_checks"]


def test_grounded_artifact_filters_live_only_checks_and_reads_residue(
    monkeypatch,
) -> None:
    migrations: list[str] = []
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service, **_kwargs: migrations.append(service),
    )
    monkeypatch.setattr(
        smoke.generation,
        "_execute_live_browser_smoke",
        lambda **kwargs: {
            "checks": {
                "actual_ae_test_database": True,
                "actual_cx_test_database": True,
                "all_live_provider_capabilities_called": False,
                "live_provider_models_frozen": True,
                "artifact_ready": True,
            },
            "hook_present": kwargs["journey_hook"] is smoke.artifact._execute_artifact_journey,
        },
    )
    monkeypatch.setattr(
        smoke.artifact,
        "_read_post_journey_residue",
        lambda _env: {"ae_chat": 0, "cx_jobs": 0},
    )

    result = smoke._run_grounded_artifact(smoke._effective_environment({}))

    assert result["status"] == "PASS"
    assert migrations == ["nex-ae-api", "nex-cx"]
    assert "all_live_provider_capabilities_called" not in result["checks"]
    assert result["checks"]["protected_fixture_residue_absent"] is True


def test_default_source_wrappers_enable_the_protected_profiles(monkeypatch) -> None:
    observed: dict[str, dict[str, str]] = {}
    monkeypatch.setattr(
        smoke,
        "run_platform_local_mock_process_smoke",
        lambda: {"status": "PASS", "actual_process_count": 13},
    )
    monkeypatch.setattr(
        smoke.login,
        "run_ae_web_credential_login_playwright_postgres_smoke",
        lambda env: observed.setdefault("login", env) and {"status": "PASS"},
    )
    monkeypatch.setattr(
        smoke.upload,
        "run_ae_web_authenticated_upload_playwright_postgres_smoke",
        lambda env: observed.setdefault("upload", env) and {"status": "FAIL"},
    )

    assert smoke._run_process_topology({})["actual_process_count"] == 13
    login_result = smoke._run_credential_login({"marker": "login"})
    upload_result = smoke._run_authenticated_upload({"marker": "upload"})

    assert observed["login"][smoke.login.SMOKE_ENV] == "1"
    assert observed["login"][smoke.login.PROFILE_ENV] == "test"
    assert login_result["actual_postgres"] is True
    assert login_result["actual_browser"] is True
    assert observed["upload"][smoke.upload.SMOKE_ENV] == "1"
    assert upload_result["actual_postgres"] is False
    assert upload_result["actual_browser"] is False


def test_two_viewport_runner_and_helpers(monkeypatch) -> None:
    stopped: list[bool] = []
    monkeypatch.setattr(smoke.login, "find_free_port", lambda: 5189)
    monkeypatch.setattr(
        smoke.login,
        "start_web_server",
        lambda _port, _target: SimpleNamespace(
            url="http://127.0.0.1:5189", stop=lambda: stopped.append(True)
        ),
    )
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=json.dumps({"status": "PASS", "runner": {"browser": "chromium"}}),
            returncode=0,
        ),
    )
    result = smoke._run_two_viewport_browser({})
    assert result["status"] == "PASS"
    assert result["returncode"] == 0
    assert stopped == [True]

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="not-json", returncode=1),
    )
    assert smoke._run_two_viewport_browser({})["failure_code"] == "node_json_invalid"
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="[]", returncode=0),
    )
    assert smoke._run_two_viewport_browser({})["failure_code"] == "node_payload_invalid"
    assert smoke._integer_mapping({"zero": 0, "flag": True, "text": "0"}) == {"zero": 0}
    assert smoke._integer_mapping(None) == {}
    assert smoke._source_is_redacted({"status": "PASS"}) is True
    assert smoke._source_is_redacted({"password": "deterministic-password"}) is False
    projection = smoke._source_projection(
        {
            "status": "PASS",
            "runner": {"browser": "chromium"},
            "issues": ["one"],
            "summary": {"viewport_count": 2},
        }
    )
    assert projection["actual_browser"] is True
    assert projection["failed_check_count"] == 1
    assert projection["viewport_count"] == 2


def test_redaction_assertion_rejects_database_and_private_markers() -> None:
    env = smoke._effective_environment({})
    with pytest.raises(AssertionError, match="database URL leaked"):
        smoke._assert_redacted(
            {"database": env[smoke.DATABASE_URLS["oa"]]},
            env,
        )
    with pytest.raises(AssertionError, match="private material"):
        smoke._assert_redacted({"authorization": "authorization: bearer"}, env)


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_source_count": 5,
            "source_count": 5,
            "database_count": 3,
            "service_process_count": 13,
            "viewport_count": 2,
        },
        "decision": {"next_slice": "1391"},
    }
    assert smoke.summary_line(passing) == (
        "s139_ae_web_protected_acceptance=pass sources=5/5 db=3 "
        "processes=13 viewports=2 next=1391"
    )
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    assert smoke.summary_line({"status": "FAIL", "issues": ["x"]}).endswith(
        "checks=1"
    )

    monkeypatch.setattr(
        smoke, "run_s139_ae_web_protected_acceptance", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "next=1391" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_s139_ae_web_protected_acceptance",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
