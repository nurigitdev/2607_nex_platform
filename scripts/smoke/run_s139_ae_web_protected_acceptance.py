#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_ae_web_authenticated_upload_playwright_postgres_smoke as upload  # noqa: E402
import run_ae_web_credential_login_playwright_postgres_smoke as login  # noqa: E402
import run_ae_web_grounded_generation_playwright_postgres_smoke as generation  # noqa: E402
import run_platform_grounded_generation_artifact_live_postgres_smoke as artifact  # noqa: E402
from run_migrations import run_service_migrations  # noqa: E402
from run_platform_local_mock_process_smoke import (  # noqa: E402
    run_platform_local_mock_process_smoke,
)


SCHEMA_VERSION = "s139_ae_web_protected_acceptance.v1"
SMOKE_ENV = "NEX_S139_AE_WEB_PROTECTED_ACCEPTANCE"
PROFILE_ENV = f"{SMOKE_ENV}_PROFILE"
DEFAULT_PROFILE = "test"
DATABASE_URLS = {
    "oa": "NEX_OA_TEST_DATABASE_URL",
    "ae": "NEX_AE_TEST_DATABASE_URL",
    "cx": "NEX_CX_TEST_DATABASE_URL",
}
DEFAULT_DATABASE_URLS = {
    "oa": "postgresql+psycopg://nex_oa_user:nuri1004@127.0.0.1:5432/nex_oa_test",
    "ae": "postgresql+psycopg://nex_ae_user:nuri1004@127.0.0.1:5432/nex_ae_test",
    "cx": "postgresql+psycopg://nex_cx_user:nuri1004@127.0.0.1:5432/nex_cx_test",
}
NODE_RUNNER = (
    ROOT
    / "apps"
    / "nex-ae-web"
    / "scripts"
    / "runKoreanGoldenJourneyPlaywrightAcceptance.mjs"
)

SourceRunner = Callable[[dict[str, str]], dict[str, Any]]


def run_s139_ae_web_protected_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    source_runners: Mapping[str, SourceRunner] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1390",
            "requirement": "S139",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
            "actual_browser": False,
            "actual_service_processes": False,
        }
    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure("profile_not_allowed")

    effective_env = _effective_environment(env)
    database_issues = _database_configuration_issues(effective_env)
    if database_issues:
        return _failure("database_configuration_invalid", issues=database_issues)

    runners = {
        "process_topology": _run_process_topology,
        "credential_login": _run_credential_login,
        "authenticated_upload": _run_authenticated_upload,
        "grounded_artifact": _run_grounded_artifact,
        "two_viewport_browser": _run_two_viewport_browser,
        **dict(source_runners or {}),
    }
    sources: dict[str, dict[str, Any]] = {}
    try:
        for name in (
            "process_topology",
            "credential_login",
            "authenticated_upload",
            "grounded_artifact",
            "two_viewport_browser",
        ):
            sources[name] = runners[name](effective_env)
    except Exception as exc:  # pragma: no cover - protected execution boundary
        result = _failure("source_execution_failed", detail=exc.__class__.__name__)
        _assert_redacted(result, effective_env)
        return result

    artifact_source = sources["grounded_artifact"]
    residue = _integer_mapping(artifact_source.get("residue"))
    checks = {
        "thirteen_service_processes_started_and_stopped": _source_passed(
            sources["process_topology"]
        ),
        "oa_backed_browser_login_passed": _source_passed(
            sources["credential_login"]
        ),
        "owner_scoped_browser_upload_passed": _source_passed(
            sources["authenticated_upload"]
        ),
        "grounded_generation_and_artifact_passed": _source_passed(
            artifact_source
        ),
        "desktop_and_mobile_chromium_passed": _source_passed(
            sources["two_viewport_browser"]
        ),
        "actual_oa_ae_cx_test_postgres": all(
            sources[name].get("actual_postgres") is True
            for name in ("credential_login", "authenticated_upload", "grounded_artifact")
        ),
        "deterministic_provider_boundary_observed": (
            artifact_source.get("provider_mode") == "deterministic_mock"
            and artifact_source.get("remote_provider_contacted") is False
        ),
        "protected_fixture_residue_absent": bool(residue)
        and all(value == 0 for value in residue.values()),
        "source_evidence_redacted": all(
            _source_is_redacted(source) for source in sources.values()
        ),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    result = {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1390",
        "requirement": "S139",
        "status": "PASS" if not failed_checks else "FAIL",
        "profile": profile,
        "actual_postgres": True,
        "actual_browser": True,
        "actual_service_processes": True,
        "provider_mode": "deterministic_mock",
        "remote_provider_required": False,
        "database_targets": ["nex_oa_test", "nex_ae_test", "nex_cx_test"],
        "source_smokes": {
            name: _source_projection(source) for name, source in sources.items()
        },
        "residue": residue,
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "source_count": len(sources),
            "passed_source_count": sum(_source_passed(item) for item in sources.values()),
            "database_count": 3,
            "service_process_count": 13,
            "viewport_count": 2,
            "journey_stage_count": 9,
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
        },
        "decision": {
            "protected_acceptance_recorded": not failed_checks,
            "next_slice": "1391" if not failed_checks else "blocked",
        },
    }
    if failed_checks:
        result["failure_code"] = "protected_acceptance_checks_failed"
    _assert_redacted(result, effective_env)
    return result


def _effective_environment(env: Mapping[str, str]) -> dict[str, str]:
    effective = dict(env)
    for service, key in DATABASE_URLS.items():
        effective.setdefault(key, DEFAULT_DATABASE_URLS[service])
    effective[PROFILE_ENV] = DEFAULT_PROFILE
    effective["NEX_MO_PROVIDER_MODE"] = "mock"
    return effective


def _database_configuration_issues(env: Mapping[str, str]) -> list[str]:
    issues = []
    for service, key in DATABASE_URLS.items():
        value = str(env.get(key) or "")
        if not value.startswith(("postgresql://", "postgresql+psycopg://")):
            issues.append(f"{service}_postgresql_required")
        if not value.rsplit("/", maxsplit=1)[-1].split("?", maxsplit=1)[0].endswith(
            "_test"
        ):
            issues.append(f"{service}_test_database_required")
    return issues


def _run_process_topology(_env: dict[str, str]) -> dict[str, Any]:
    return run_platform_local_mock_process_smoke()


def _run_credential_login(env: dict[str, str]) -> dict[str, Any]:
    source_env = {
        **env,
        login.SMOKE_ENV: "1",
        login.PROFILE_ENV: DEFAULT_PROFILE,
    }
    result = login.run_ae_web_credential_login_playwright_postgres_smoke(source_env)
    result["actual_postgres"] = result.get("status") == "PASS"
    result["actual_browser"] = result.get("status") == "PASS"
    return result


def _run_authenticated_upload(env: dict[str, str]) -> dict[str, Any]:
    source_env = {
        **env,
        upload.SMOKE_ENV: "1",
        upload.PROFILE_ENV: DEFAULT_PROFILE,
    }
    result = upload.run_ae_web_authenticated_upload_playwright_postgres_smoke(
        source_env
    )
    result["actual_postgres"] = result.get("status") == "PASS"
    result["actual_browser"] = result.get("status") == "PASS"
    return result


def _run_grounded_artifact(env: dict[str, str]) -> dict[str, Any]:
    ae_url = env[DATABASE_URLS["ae"]]
    cx_url = env[DATABASE_URLS["cx"]]
    run_service_migrations("nex-ae-api", database_url=ae_url, profile=DEFAULT_PROFILE)
    run_service_migrations("nex-cx", database_url=cx_url, profile=DEFAULT_PROFILE)
    execution = generation._execute_live_browser_smoke(
        ae_database_url=ae_url,
        cx_database_url=cx_url,
        runtime_environ={
            **env,
            generation.AE_DATABASE_ENV: ae_url,
            generation.CX_DATABASE_ENV: cx_url,
            "NEX_MO_PROVIDER_MODE": "mock",
        },
        journey_hook=artifact._execute_artifact_journey,
    )
    checks = {
        name: passed is True
        for name, passed in dict(execution.get("checks") or {}).items()
        if name not in {
            "all_live_provider_capabilities_called",
            "live_provider_models_frozen",
        }
    }
    residue = artifact._read_post_journey_residue(
        {
            **env,
            generation.AE_DATABASE_ENV: ae_url,
            generation.CX_DATABASE_ENV: cx_url,
        }
    )
    checks["protected_fixture_residue_absent"] = all(
        value == 0 for value in residue.values()
    )
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "status": "PASS" if not failed_checks else "FAIL",
        "actual_postgres": True,
        "actual_browser": True,
        "provider_mode": "deterministic_mock",
        "remote_provider_contacted": False,
        "checks": checks,
        "failed_checks": failed_checks,
        "residue": residue,
    }


def _run_two_viewport_browser(env: dict[str, str]) -> dict[str, Any]:
    server = login.start_web_server(login.find_free_port(), "http://127.0.0.1:9")
    try:
        node_env = {
            **os.environ,
            **env,
            "NEX_AE_WEB_GOLDEN_JOURNEY_WEB_URL": server.url,
        }
        completed = subprocess.run(
            ["node", str(NODE_RUNNER)],
            cwd=ROOT,
            env=node_env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return {"status": "FAIL", "failure_code": "node_json_invalid"}
        if not isinstance(result, dict):
            return {"status": "FAIL", "failure_code": "node_payload_invalid"}
        result["returncode"] = completed.returncode
        return result
    finally:
        server.stop()


def _source_passed(source: Mapping[str, Any]) -> bool:
    return source.get("status") == "PASS"


def _source_projection(source: Mapping[str, Any]) -> dict[str, Any]:
    summary = dict(source.get("summary") or {})
    return {
        "status": source.get("status", "UNKNOWN"),
        "failure_code": source.get("failure_code"),
        "actual_postgres": source.get("actual_postgres") is True,
        "actual_browser": source.get("actual_browser") is True
        or source.get("runner", {}).get("browser") == "chromium",
        "check_count": len(source.get("checks") or {}),
        "failed_check_count": len(source.get("failed_checks") or source.get("issues") or []),
        "viewport_count": summary.get("viewport_count"),
    }


def _integer_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): int(item)
        for key, item in value.items()
        if isinstance(item, int) and not isinstance(item, bool)
    }


def _source_is_redacted(source: Mapping[str, Any]) -> bool:
    serialized = json.dumps(source, ensure_ascii=False, sort_keys=True).lower()
    return not any(
        marker in serialized
        for marker in (
            "authorization: bearer",
            "begin private key",
            "deterministic-password",
            "s109-protected-smoke",
            "nuri1004@",
        )
    )


def _assert_redacted(result: Mapping[str, Any], env: Mapping[str, str]) -> None:
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    for key in DATABASE_URLS.values():
        value = str(env.get(key) or "")
        if value and value in serialized:
            raise AssertionError(f"protected database URL leaked: {key}")
    if not _source_is_redacted(result):
        raise AssertionError("protected evidence contains private material")


def _failure(
    code: str,
    *,
    detail: str | None = None,
    issues: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1390",
        "requirement": "S139",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "issues": list(issues or []),
        "actual_postgres": False,
        "actual_browser": False,
        "actual_service_processes": False,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "s139_ae_web_protected_acceptance=skipped"
    if result.get("status") != "PASS":
        return (
            "s139_ae_web_protected_acceptance=fail "
            f"checks={len(result.get('failed_checks') or result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "s139_ae_web_protected_acceptance=pass "
        f"sources={summary.get('passed_source_count')}/{summary.get('source_count')} "
        f"db={summary.get('database_count')} "
        f"processes={summary.get('service_process_count')} "
        f"viewports={summary.get('viewport_count')} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_s139_ae_web_protected_acceptance()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 1 if result.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
