#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-oa",
    ROOT / "services" / "nex-wc",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p5_s5_postgres_smoke as p5_s5
import run_p7_s5_postgres_smoke as p7_s5
import run_p7_s9_postgres_live_golden_b as p7_s9
from nex_oa.authorization_repository import build_authorization_repository_for_runtime
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver
from nex_oa.authorization_service import (
    OaAuthorizationService,
    register_authorization_routes,
)
from nex_oa.memberships import (
    build_tenant_membership_registry_for_runtime,
    register_identity_membership_routes,
)
from nex_oa.subjects import build_subject_registry_for_runtime
from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    redact_database_url,
)
from run_migrations import run_service_migrations

SCHEMA_VERSION = "p7_ca02_work_delegate_denied_postgres.v1"
SMOKE_ENV = "NEX_P7_CA02_WORK_DELEGATE_DENIED_POSTGRES"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
WC_DATABASE_ENV = "NEX_WC_TEST_DATABASE_URL"
OA_DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"


def run_p7_ca02_work_delegate_denied_postgres(
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P7-CA02",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    urls = {
        "ae": env.get(AE_DATABASE_ENV, ""),
        "wc": env.get(WC_DATABASE_ENV, ""),
        "oa": env.get(OA_DATABASE_ENV, ""),
    }
    targets = {
        "ae": ("nex_ae_user", "nex_ae_test"),
        "wc": ("nex_wc_user", "nex_wc_test"),
        "oa": ("nex_oa_user", "nex_oa_test"),
    }
    if any(
        not p7_s9._target_allowed(urls[name], user=user, database=database)
        for name, (user, database) in targets.items()
    ):
        return _failure(
            "target_not_allowed", "AE, WC, and OA test databases are required."
        )
    runtime_environ = {
        **env,
        SERVICE_SPECS["nex-oa"].database_env: urls["oa"],
        "NEX_OA_PERSISTENCE_MODE": "postgres",
    }
    migrations = {}
    persistence = None
    source = None
    result: dict[str, object] = {}
    oa_cleanup: dict[str, int] = {}
    try:
        for service in ("nex-ae-api", "nex-wc", "nex-oa"):
            migrations[service] = run_service_migrations(
                service,
                database_url=urls[
                    {"nex-ae-api": "ae", "nex-wc": "wc", "nex-oa": "oa"}[service]
                ],
                profile="test",
            )
        app = build_service_app(SERVICE_SPECS["nex-oa"])
        persistence = attach_service_persistence_runtime(
            app, SERVICE_SPECS["nex-oa"], environ=runtime_environ
        )
        if persistence.api_engine is None:
            raise RuntimeError("OA PostgreSQL runtime is unavailable")
        subjects = build_subject_registry_for_runtime(persistence)
        memberships = build_tenant_membership_registry_for_runtime(
            persistence, subject_registry=subjects
        )
        repository = build_authorization_repository_for_runtime(persistence)
        service = OaAuthorizationService(
            repository,
            OaEffectiveAuthorizationResolver(repository),
            memberships,
        )
        register_identity_membership_routes(app, registry=memberships)
        register_authorization_routes(app, service=service)
        with TestClient(app) as client:
            source = p7_s9._OaApiAuthorizationSource(
                client,
                scopes=("work:claim", "work:result:submit"),
            )
            result = p5_s5._execute_postgres_smoke(
                urls["ae"],
                verifier=lambda fixture: p7_s5._verify_delegate_wait(
                    fixture,
                    wc_url=urls["wc"],
                    authorization_source=source,
                    expect_authorization_denied=True,
                ),
            )
            oa = p7_s9._oa_observation(persistence.api_engine, source)
            result["checks"] = {
                **dict(result.get("checks") or {}),
                "all_migrations_current": all(
                    len(item.planned) == len(item.applied) + len(item.skipped)
                    for item in migrations.values()
                ),
                "wc_authorization_migration_current": (
                    migrations["nex-wc"].planned[-1]
                    == "1003_wc_work_item_authorization"
                ),
                "oa_no_delegate_scope_confirmed": source.authorization_calls == 1
                and source.observed_gates == ["work:delegate"]
                and oa["membership_count"] == 1,
                "actual_oa_database_identity": oa["database"] == "nex_oa_test"
                and oa["role"] == "nex_oa_user",
            }
    except Exception as exc:  # noqa: BLE001 - protected smoke boundary
        detail = str(exc)
        for url in urls.values():
            detail = p5_s5._redact_detail(detail, database_url=url)
        return _failure(
            "execution_failed",
            f"{getattr(exc, 'error_code', type(exc).__name__)}: {detail}",
        )
    finally:
        if persistence is not None:
            if source is not None:
                oa_cleanup = p7_s9._cleanup_oa(
                    persistence.api_engine, source.tenant_ids
                )
            p7_s9._dispose_runtime(persistence)
    result["checks"] = {
        **dict(result.get("checks") or {}),
        "oa_zero_residue": oa_cleanup.get("oa_remaining", -1) == 0,
    }
    checks = dict(result["checks"])
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P7-CA02",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "profile": "test",
        "source_revision_under_test": p7_s9._source_revision(),
        "actual_postgres": True,
        "actual_remote_provider": False,
        "redacted_database_urls": {
            key: redact_database_url(value) for key, value in urls.items()
        },
        "migration_heads": {
            service: item.planned[-1] for service, item in migrations.items()
        },
        "authorization": {
            "effective_authorization_calls": source.authorization_calls,
            "work_delegate_gate_calls": source.observed_gates.count("work:delegate"),
            "work_delegate_granted": False,
        },
        "checks": checks,
        "row_counts": dict(result.get("row_counts") or {}),
        "cleanup_counts": {
            **dict(result.get("cleanup_counts") or {}),
            **oa_cleanup,
        },
    }


def _failure(code: str, detail: str) -> dict[str, object]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P7-CA02",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
        "actual_remote_provider": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    return (
        "p7_ca02_work_delegate_denied_postgres="
        f"{str(evidence.get('status', 'UNKNOWN')).lower()} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"work_items={(evidence.get('row_counts') or {}).get('wc_work_item', 'not-run')} "
        f"residue={(evidence.get('cleanup_counts') or {}).get('wc_remaining', 'not-run')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the protected P7-CA02 work:delegate denied PostgreSQL smoke."
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    evidence = run_p7_ca02_work_delegate_denied_postgres()
    print(
        json.dumps(evidence, indent=2, sort_keys=True)
        if args.json
        else summary_line(evidence)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
