#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/nex-ae-api",
    ROOT / "services/_shared",
    ROOT / "domains/mybee",
    ROOT / "scripts/db",
):
    sys.path.insert(0, str(path))

from nex_ae_api.m1_installed_skill_runtime import M1InstalledSkillRuntime
from nex_ae_api.mybee_m1_skill_runtime import build_mybee_m1_verified_skill_catalog
from nex_ae_api.product_runtime_profile import load_verified_product_runtime_config
from nex_runtime import redact_database_url
from run_migrations import run_service_migrations

SCHEMA_VERSION = "w70_cp_m1_e2e_fx_01a5_postgres_gate.v1"
ENABLE_ENV = "NEX_AE_M1_INSTALLED_RUNTIME_POSTGRES_GATE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REPORT = ROOT / "reports/smoke/w70-cp-m1-e2e-fx-01a5-postgres-gate.json"


def run_gate(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ENABLE_ENV) != "1":
        return _result(
            status="SKIPPED",
            actual_postgres=False,
            detail=f"{ENABLE_ENV} is not enabled.",
        )
    database_url = str(env.get(DATABASE_ENV) or "")
    if not _allowed_target(database_url):
        return _result(
            status="FAIL",
            actual_postgres=False,
            detail=f"target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
        )
    tenant_id = f"w70-m1-{uuid4().hex[:16]}"
    engine = create_engine(database_url, pool_pre_ping=True)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    runtime_env = {
        **env,
        "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
            ROOT
            / "deployment/environments/ae-product-capability-registry.mybee-m1.v1.json"
        ),
        "NEX_OA_BASE_URL": env.get("NEX_OA_BASE_URL", "http://127.0.0.1:1"),
        "NEX_EOS_BASE_URL": env.get("NEX_EOS_BASE_URL", "http://127.0.0.1:1"),
        "NEX_AE_TO_OA_SERVICE_TOKEN": env.get(
            "NEX_AE_TO_OA_SERVICE_TOKEN", "protected-gate-token"
        ),
        "NEX_AE_TO_EOS_SERVICE_TOKEN": env.get(
            "NEX_AE_TO_EOS_SERVICE_TOKEN", "protected-gate-token"
        ),
        "NEX_AE_NSL_STATE_ROOT": str(Path("/tmp") / tenant_id),
    }
    try:
        migration = run_service_migrations(
            "nex-ae-api", database_url=database_url, profile="test"
        )
        with engine.connect() as connection:
            database, role = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
        catalog = build_mybee_m1_verified_skill_catalog(runtime_env)
        runtime = M1InstalledSkillRuntime(
            sessions,
            catalog=catalog,
            config=load_verified_product_runtime_config(runtime_env),
        )
        gateway = runtime.dependencies.artifact_gateway
        artifacts: list[dict[str, Any]] = []
        replay_equal = True
        for selection in catalog.selections:
            binding = selection.capability.capability["local_skill_binding"]
            values = {
                "tenant_id": tenant_id,
                "skill_id": selection.release_skill.skill_id,
                "exact_version": selection.release_skill.skill_version,
                "expected_semantic_hash": selection.release_skill.semantic_hash,
                "runtime_contract_ref": binding["runtime_contract_ref"],
                "trust_policy_id": selection.release_skill.trust_policy_id,
                "environment": "staging",
                "observed_at": catalog.admitted_at,
            }
            first = gateway.resolve_verified(**values)
            second = gateway.resolve_verified(**values)
            artifacts.append(first)
            replay_equal = replay_equal and first == second
        with engine.connect() as connection:
            persisted = (
                connection.execute(
                    text(
                        "SELECT skill_id, artifact_hash FROM ae_nsl_artifact "
                        "WHERE tenant_id = :tenant_id ORDER BY skill_id"
                    ),
                    {"tenant_id": tenant_id},
                )
                .mappings()
                .all()
            )
        passed = (
            (database, role) == (EXPECTED_DATABASE, EXPECTED_ROLE)
            and replay_equal
            and len(artifacts) == 2
            and len(persisted) == 2
            and {row["skill_id"] for row in persisted}
            == {item.release_skill.skill_id for item in catalog.selections}
            and runtime.package_readiness["status"] == "READY"
        )
        return _result(
            status="PASS" if passed else "FAIL",
            actual_postgres=True,
            detail="installed signed multi-Skill persistence and replay completed",
            database=database,
            role=role,
            migration=asdict(migration),
            tenant_id=tenant_id,
            release_id=catalog.release_id,
            release_hash=catalog.release_hash,
            catalog_hash=catalog.catalog_hash,
            artifact_count=len(persisted),
            artifact_hashes=[row["artifact_hash"] for row in persisted],
            exact_replay=replay_equal,
            redacted_database_url=redact_database_url(database_url),
        )
    except Exception as exc:  # noqa: BLE001 - protected gate records bounded failure
        return _result(
            status="FAIL",
            actual_postgres=True,
            detail=f"{type(exc).__name__}: {exc}",
            tenant_id=tenant_id,
            redacted_database_url=redact_database_url(database_url),
        )
    finally:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM ae_nsl_artifact WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                )
        finally:
            engine.dispose()


def _allowed_target(database_url: str) -> bool:
    try:
        target = make_url(database_url)
    except Exception:  # noqa: BLE001 - malformed URLs are rejected uniformly
        return False
    return target.database == EXPECTED_DATABASE and target.username == EXPECTED_ROLE


def _result(
    *, status: str, actual_postgres: bool, detail: str, **values: Any
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "CP-M1-E2E-FX-01A.5",
        "status": status,
        "actual_postgres": actual_postgres,
        "detail": detail,
        **values,
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    result = run_gate()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.summary:
        print(
            f"status={result['status']} actual_postgres={result['actual_postgres']} "
            f"artifacts={result.get('artifact_count', 0)}"
        )
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
