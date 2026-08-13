#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_runtime import load_env_file  # noqa: E402
from run_ae_web_credential_login_browser_live_smoke import (  # noqa: E402
    SCHEMA_VERSION as LIVE_SMOKE_SCHEMA_VERSION,
    assert_live_smoke_evidence_redacted,
    run_ae_web_credential_login_browser_live_smoke,
)
from run_ae_web_credential_login_browser_smoke_boundary import (  # noqa: E402
    DEFAULT_PROFILE,
    PROFILE_ENV,
    SMOKE_ENV as BROWSER_SMOKE_ENV,
)


SCHEMA_VERSION = "ae_web_credential_login_browser_postgres_evidence_hardening.v1"
CONTRACT_SCHEMA_PATH = (
    ROOT
    / "contracts"
    / "schemas"
    / "service"
    / "nex_ae_web"
    / "credential_login_browser_live_smoke_evidence.v1.schema.json"
)

LiveRunner = Callable[[dict[str, str]], dict[str, Any]]


def run_ae_web_credential_login_browser_postgres_evidence_hardening(
    environ: dict[str, str] | None = None,
    *,
    live_runner: LiveRunner = run_ae_web_credential_login_browser_live_smoke,
    contract_schema_path: Path = CONTRACT_SCHEMA_PATH,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(BROWSER_SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{BROWSER_SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        }

    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    live_evidence = live_runner(env)
    if live_evidence.get("status") != "PASS":
        return _failure(
            "live_smoke_not_passed",
            profile=profile,
            live_evidence=live_evidence,
            issues=[
                _issue(
                    "source_status",
                    "$.status",
                    f"live smoke returned {_status(live_evidence)}",
                )
            ],
            env=env,
            contract_schema_path=contract_schema_path,
        )

    contract_schema = load_contract_schema(contract_schema_path)
    issues = [
        *schema_issues(live_evidence, contract_schema),
        *postgres_invariant_issues(live_evidence),
    ]
    if issues:
        return _failure(
            "evidence_hardening_failed",
            profile=profile,
            live_evidence=live_evidence,
            issues=issues,
            env=env,
            contract_schema_path=contract_schema_path,
            contract_schema=contract_schema,
        )

    evidence = _pass_evidence(
        profile=profile,
        live_evidence=live_evidence,
        contract_schema=contract_schema,
        contract_schema_path=contract_schema_path,
    )
    assert_hardening_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, default=str),
        env,
    )
    return evidence


def load_contract_schema(path: Path = CONTRACT_SCHEMA_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object schema.")
    return payload


def schema_issues(
    live_evidence: Mapping[str, Any],
    contract_schema: Mapping[str, Any],
) -> list[dict[str, str]]:
    validator = Draft202012Validator(dict(contract_schema))
    return [
        _issue("contract_schema", _json_path(error.absolute_path), error.validator)
        for error in sorted(validator.iter_errors(live_evidence), key=str)
    ]


def postgres_invariant_issues(
    live_evidence: Mapping[str, Any],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    database_envs = _mapping(live_evidence.get("database_envs"))
    migrations = _mapping(live_evidence.get("migrations"))
    db_observations = _mapping(live_evidence.get("db_observations"))
    credential_observations = _mapping(
        live_evidence.get("credential_login_observations")
    )
    browser_harness = _mapping(live_evidence.get("browser_harness_observations"))
    execution = _mapping(live_evidence.get("execution_observations"))
    checks = _mapping(live_evidence.get("checks"))
    cleanup = _mapping(live_evidence.get("cleanup_observations"))
    oa_cleanup = _mapping(cleanup.get("oa_rows"))

    if database_envs != {
        "ae": "NEX_AE_TEST_DATABASE_URL",
        "oa": "NEX_OA_TEST_DATABASE_URL",
    }:
        issues.append(_issue("postgres_envs", "$.database_envs", "expected_ae_oa_test"))

    for service_key, expected_service_id in (
        ("ae", "nex-ae-api"),
        ("oa", "nex-oa"),
    ):
        migration = _mapping(migrations.get(service_key))
        if migration.get("service_id") != expected_service_id:
            issues.append(
                _issue(
                    "migration_service",
                    f"$.migrations.{service_key}.service_id",
                    "service_mismatch",
                )
            )
        if migration.get("profile") != "test" or migration.get("dry_run") is not False:
            issues.append(
                _issue(
                    "migration_execution",
                    f"$.migrations.{service_key}",
                    "must_be_test_write_mode",
                )
            )
        planned_count = _int_value(migration.get("planned_count"))
        applied_count = len(migration.get("applied", []))
        skipped_count = _int_value(migration.get("skipped_count"))
        if planned_count < applied_count + skipped_count:
            issues.append(
                _issue(
                    "migration_counts",
                    f"$.migrations.{service_key}",
                    "planned_count_too_small",
                )
            )

    if db_observations.get("ae_marker_rows") != 1:
        issues.append(_issue("db_readback", "$.db_observations.ae_marker_rows", "expected_1"))
    if db_observations.get("oa_credential_count") != 1:
        issues.append(
            _issue("db_readback", "$.db_observations.oa_credential_count", "expected_1")
        )
    if db_observations.get("oa_session_status") != "REVOKED":
        issues.append(
            _issue(
                "session_revocation",
                "$.db_observations.oa_session_status",
                "expected_revoked",
            )
        )
    if credential_observations.get("password_verified") is not True:
        issues.append(
            _issue(
                "credential_login",
                "$.credential_login_observations.password_verified",
                "expected_true",
            )
        )
    if browser_harness.get("route_guard_status") != "allowed":
        issues.append(
            _issue(
                "browser_harness",
                "$.browser_harness_observations.route_guard_status",
                "expected_allowed",
            )
        )
    if execution.get("actual_test_database_smoke_executed") is not True:
        issues.append(
            _issue(
                "postgres_execution",
                "$.execution_observations.actual_test_database_smoke_executed",
                "expected_true",
            )
        )
    if cleanup.get("ae_marker_rows_after_delete") != 0:
        issues.append(
            _issue(
                "cleanup",
                "$.cleanup_observations.ae_marker_rows_after_delete",
                "expected_0",
            )
        )
    for key in (
        "deleted_sessions",
        "deleted_credentials",
        "deleted_memberships",
        "deleted_subjects",
        "deleted_tenants",
    ):
        if _int_value(oa_cleanup.get(key)) < 1:
            issues.append(
                _issue("cleanup", f"$.cleanup_observations.oa_rows.{key}", "expected_min_1")
            )
    for key, value in checks.items():
        if value is not True:
            issues.append(_issue("checks", f"$.checks.{key}", "expected_true"))
    return issues


def _pass_evidence(
    *,
    profile: str,
    live_evidence: Mapping[str, Any],
    contract_schema: Mapping[str, Any],
    contract_schema_path: Path,
) -> dict[str, Any]:
    db_observations = _mapping(live_evidence.get("db_observations"))
    credential_observations = _mapping(
        live_evidence.get("credential_login_observations")
    )
    browser_harness = _mapping(live_evidence.get("browser_harness_observations"))
    cleanup = _mapping(live_evidence.get("cleanup_observations"))
    checks = {
        "live_smoke_passed": live_evidence.get("status") == "PASS",
        "contract_schema_valid": True,
        "test_database_envs_exact": _mapping(live_evidence.get("database_envs"))
        == {"ae": "NEX_AE_TEST_DATABASE_URL", "oa": "NEX_OA_TEST_DATABASE_URL"},
        "postgres_migrations_current_or_applied": True,
        "db_readback_proven": (
            db_observations.get("ae_marker_rows") == 1
            and db_observations.get("oa_credential_count") == 1
        ),
        "credential_password_verified": (
            credential_observations.get("password_verified") is True
        ),
        "session_revocation_readback": (
            db_observations.get("oa_session_status") == "REVOKED"
        ),
        "browser_route_guard_allowed": (
            browser_harness.get("route_guard_status") == "allowed"
        ),
        "cleanup_proven": cleanup.get("ae_marker_rows_after_delete") == 0,
        "redacted_evidence": True,
    }
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "profile": profile,
        "source_smoke": {
            "schema_version": live_evidence.get("smoke_schema_version"),
            "status": live_evidence.get("status"),
        },
        "contract": {
            "schema_path": relative_label(contract_schema_path),
            "schema_id": contract_schema.get("$id"),
            "validated": True,
        },
        "postgres_evidence": {
            "database_envs": _mapping(live_evidence.get("database_envs")),
            "redacted_database_urls": _mapping(
                live_evidence.get("redacted_database_urls")
            ),
            "migrations": _mapping(live_evidence.get("migrations")),
            "db_observations": db_observations,
            "credential_login_observations": {
                "password_verified": credential_observations.get("password_verified")
                is True,
                "owner_scope_authority": credential_observations.get(
                    "owner_scope_authority"
                ),
            },
            "browser_harness_observations": {
                "route_guard_status": browser_harness.get("route_guard_status"),
                "fetch_call_count": browser_harness.get("fetch_call_count"),
            },
            "cleanup_observations": cleanup,
        },
        "checks": checks,
        "issue_count": 0,
    }


def _failure(
    failure_code: str,
    *,
    profile: str,
    live_evidence: Mapping[str, Any],
    issues: list[dict[str, str]],
    env: Mapping[str, str],
    contract_schema_path: Path,
    contract_schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "profile": profile,
        "failure_code": failure_code,
        "source_smoke": {
            "schema_version": live_evidence.get("smoke_schema_version"),
            "status": live_evidence.get("status"),
        },
        "contract": {
            "schema_path": relative_label(contract_schema_path),
            "schema_id": contract_schema.get("$id") if contract_schema else None,
            "validated": False,
        },
        "issue_count": len(issues),
        "issues": issues,
        "checks": {
            "live_smoke_passed": live_evidence.get("status") == "PASS",
            "contract_schema_valid": False,
            "redacted_evidence": True,
        },
    }
    assert_hardening_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, default=str),
        env,
    )
    return evidence


def assert_hardening_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    assert_live_smoke_evidence_redacted(serialized_evidence, environ)


def write_hardening_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    assert_hardening_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def _issue(category: str, path: str, reason: str) -> dict[str, str]:
    return {"category": category, "path": path, "reason": reason}


def _json_path(path: object) -> str:
    parts = list(path)
    if not parts:
        return "$"
    rendered = "$"
    for part in parts:
        rendered += f"[{part}]" if isinstance(part, int) else f".{part}"
    return rendered


def _status(evidence: Mapping[str, Any]) -> str:
    return str(evidence.get("status", "UNKNOWN"))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _int_value(value: object) -> int:
    return value if isinstance(value, int) else 0


def relative_label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_web_credential_login_browser_postgres_evidence_hardening=skipped "
            f"reason={BROWSER_SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        postgres_evidence = _mapping(evidence.get("postgres_evidence"))
        db_observations = _mapping(postgres_evidence.get("db_observations"))
        browser_harness = _mapping(
            postgres_evidence.get("browser_harness_observations")
        )
        return (
            "ae_web_credential_login_browser_postgres_evidence_hardening=pass "
            f"profile={evidence['profile']} "
            f"schema={LIVE_SMOKE_SCHEMA_VERSION} "
            f"route_guard={browser_harness.get('route_guard_status')} "
            f"oa_session_status={db_observations.get('oa_session_status')} "
            "issues=0"
        )
    return (
        "ae_web_credential_login_browser_postgres_evidence_hardening=fail "
        f"reason={evidence.get('failure_code')} "
        f"issues={evidence.get('issue_count')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Harden AE Web credential-login browser PostgreSQL evidence."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_env_file(ROOT / ".env.local")
        evidence = run_ae_web_credential_login_browser_postgres_evidence_hardening()
        if args.output:
            write_hardening_evidence(args.output, evidence)
        print(
            summary_line(evidence)
            if args.summary
            else json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
        )
        return 1 if evidence["status"] == "FAIL" else 0
    except ValueError as exc:
        print(
            "ae_web_credential_login_browser_postgres_evidence_hardening=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
