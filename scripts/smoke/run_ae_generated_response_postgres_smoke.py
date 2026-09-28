#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_runtime import redact_database_url  # noqa: E402
from run_ae_cx_async_generation_postgres_smoke import (  # noqa: E402
    _execute_postgres_smoke,
    _migration_current,
    _migration_summary,
    _redact_detail,
    _target_url_allowed,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ae_generated_response_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_GENERATED_RESPONSE_POSTGRES_SMOKE"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
CX_DATABASE_ENV = "NEX_CX_TEST_DATABASE_URL"
AE_DATABASE = "nex_ae_test"
CX_DATABASE = "nex_cx_test"
AE_ROLE = "nex_ae_user"
CX_ROLE = "nex_cx_user"

SmokeExecutor = Callable[..., dict[str, Any]]


def run_ae_generated_response_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    executor: SmokeExecutor | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1070",
            "requirement": "S107",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    ae_url = env.get(AE_DATABASE_ENV, "")
    cx_url = env.get(CX_DATABASE_ENV, "")
    if not ae_url or not cx_url:
        return _failure(
            "database_url_missing",
            f"{AE_DATABASE_ENV} and {CX_DATABASE_ENV} are required.",
        )
    if not _target_url_allowed(ae_url, role=AE_ROLE, database=AE_DATABASE):
        return _failure(
            "ae_target_not_allowed",
            f"AE database target must be {AE_ROLE}@.../{AE_DATABASE}.",
        )
    if not _target_url_allowed(cx_url, role=CX_ROLE, database=CX_DATABASE):
        return _failure(
            "cx_target_not_allowed",
            f"CX database target must be {CX_ROLE}@.../{CX_DATABASE}.",
        )

    try:
        ae_migration = run_service_migrations(
            "nex-ae-api", database_url=ae_url, profile="test"
        )
        cx_migration = run_service_migrations(
            "nex-cx", database_url=cx_url, profile="test"
        )
        evidence = (executor or _execute_postgres_smoke)(
            ae_database_url=ae_url,
            cx_database_url=cx_url,
        )
        evidence["checks"] = {
            "ae_migration_current": _migration_current(ae_migration),
            "cx_migration_current": _migration_current(cx_migration),
            **evidence.get("checks", {}),
        }
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "1070",
                "requirement": "S107",
                "actual_postgres": True,
                "provider_mode": "deterministic-mock",
                "remote_provider_required": False,
                "private_storage_mode": "temporary-local-filesystem",
                "databases": {
                    "ae": redact_database_url(ae_url),
                    "cx": redact_database_url(cx_url),
                },
                "migrations": {
                    "ae": _migration_summary(ae_migration),
                    "cx": _migration_summary(cx_migration),
                },
            }
        )
        evidence["failed_checks"] = [
            name for name, passed in evidence["checks"].items() if not passed
        ]
        evidence["status"] = (
            "PASS" if not evidence["failed_checks"] else "FAIL"
        )
        if evidence["failed_checks"]:
            evidence["failure_code"] = "ae_generated_response_smoke_failed"
        return evidence
    except (MigrationError, SQLAlchemyError, OSError, ValueError, RuntimeError) as exc:
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_urls=(ae_url, cx_url)),
        )
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__)


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1070",
        "requirement": "S107",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return (
            "ae_generated_response_postgres=skipped "
            f"reason={SMOKE_ENV}"
        )
    if result.get("status") != "PASS":
        return (
            "ae_generated_response_postgres=fail "
            f"code={result.get('failure_code', 'checks_failed')}"
        )
    cleanup = result.get("cleanup_counts", {})
    checks = result.get("checks", {})
    return (
        "ae_generated_response_postgres=pass "
        f"checks={sum(value is True for value in checks.values())} "
        f"cleanup={cleanup.get('ae_remaining', '?')}/"
        f"{cleanup.get('cx_remaining', '?')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_generated_response_postgres_smoke()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
