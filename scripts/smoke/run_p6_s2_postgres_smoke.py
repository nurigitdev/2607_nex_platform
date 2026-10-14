#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_ae_api.skill_artifacts import (
    SkillArtifactGateway,
    SkillArtifactGatewayError,
    SqlAlchemySkillArtifactRepository,
)
from nex_runtime import (
    load_env_file,
    redact_database_url,
    sqlalchemy_database_url,
)
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p6_s2_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_S2_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2201_ae_nsl_artifact"
GOLDEN = (
    ROOT
    / "docs/transition/P6/contracts/examples/p6-golden-verified-artifact-v1.json"
)


class _Resolver:
    def __init__(self, golden: Mapping[str, Any], *, signed: bool = True) -> None:
        self.calls = 0
        self._resolved = SimpleNamespace(
            skill=SimpleNamespace(
                skill_id=golden["skill_id"],
                skill_version=golden["skill_version"],
                semantic_hash=golden["skill_semantic_hash"],
            ),
            package_hash=golden["package_hash"],
            signer_key_id=golden["signing_key_id"] if signed else None,
        )

    def resolve(self, *, skill_id: str, skill_version: str) -> object:
        self.calls += 1
        return self._resolved


class _AdmissionSource:
    def __init__(self, golden: Mapping[str, Any]) -> None:
        self.calls = 0
        trust = golden["trust_evidence"]
        self._record = {
            "trust_evidence": {
                "evidence_ref": trust["evidence_ref"],
                "package_id": golden["package_id"],
                "package_hash": golden["package_hash"],
                "publisher_id": golden["publisher_id"],
                "signing_key_id": golden["signing_key_id"],
                "verified_at": trust["verified_at"],
                "trust_policy_id": trust["trust_policy_id"],
                "trust_status": trust["trust_status"],
                "governance_status": trust["governance_status"],
                "governance_decision_ref": trust["governance_decision_ref"],
                "evidence_hash": trust["evidence_hash"],
            },
            "admission_decision": {
                "decision_id": golden["artifact_admission_decision_ref"],
                "decision": "ADMITTED",
                "package_id": golden["package_id"],
                "package_hash": golden["package_hash"],
                "publisher_id": golden["publisher_id"],
                "signing_key_id": golden["signing_key_id"],
                "governance_status": "ACTIVE",
                "trust_policy_id": trust["trust_policy_id"],
                "package_trust_evidence_ref": trust["evidence_ref"],
                "reason_codes": [],
                "decided_at": trust["verified_at"],
            },
            "admission_decision_hash": golden[
                "artifact_admission_decision_hash"
            ],
        }

    def current_admission(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls += 1
        return self._record


def run_p6_s2_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-S2",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    database_url = env.get(DATABASE_ENV, "")
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not _target_url_allowed(database_url):
        return _failure(
            "target_not_allowed",
            f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
        )
    try:
        migration = run_service_migrations(
            "nex-ae-api", database_url=database_url, profile="test"
        )
        evidence = _execute_postgres_smoke(database_url)
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "P6-S2",
                "profile": "test",
                "database_env": DATABASE_ENV,
                "redacted_database_url": redact_database_url(database_url),
                "migration": {
                    "planned_count": len(migration.planned),
                    "applied_count": len(migration.applied),
                    "skipped_count": len(migration.skipped),
                    "latest_version": migration.planned[-1]
                    if migration.planned
                    else None,
                },
            }
        )
        evidence["checks"] = {
            "migration_current": (
                REQUIRED_MIGRATION in migration.planned
                and migration.planned[-1] == REQUIRED_MIGRATION
                and len(migration.planned)
                == len(migration.applied) + len(migration.skipped)
            ),
            **evidence["checks"],
        }
        evidence["status"] = (
            "PASS" if all(evidence["checks"].values()) else "FAIL"
        )
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "p6_s2_postgres_smoke_failed"
        return evidence
    except (
        MigrationError,
        OSError,
        RuntimeError,
        SkillArtifactGatewayError,
        SQLAlchemyError,
        ValueError,
    ) as exc:
        return _failure(
            "execution_failed", _redact_detail(str(exc), database_url=database_url)
        )


def _execute_postgres_smoke(database_url: str) -> dict[str, Any]:
    engine = create_engine(
        sqlalchemy_database_url(database_url), future=True, pool_pre_ping=True
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    tenant_id = f"tenant-p6-s2-{uuid4().hex[:12]}"
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    repository = SqlAlchemySkillArtifactRepository(factory)
    resolver = _Resolver(golden)
    admissions = _AdmissionSource(golden)
    gateway = SkillArtifactGateway(
        resolver=resolver,
        admission_source=admissions,
        repository=repository,
    )
    artifact: dict[str, Any] | None = None
    cleanup_counts: dict[str, int] = {}
    checks: dict[str, bool] = {}
    database = ""
    role = ""

    try:
        with factory() as session:
            database, role = session.execute(
                text("SELECT current_database(), current_user")
            ).one()
        arguments = {
            "tenant_id": tenant_id,
            "skill_id": golden["skill_id"],
            "exact_version": golden["skill_version"],
            "expected_semantic_hash": golden["skill_semantic_hash"],
            "runtime_contract_ref": golden["runtime_contract_ref"],
            "trust_policy_id": golden["trust_evidence"]["trust_policy_id"],
            "environment": "production",
            "observed_at": observed_at,
        }
        artifact = gateway.resolve_verified(**arguments)
        replay = gateway.resolve_verified(**arguments)
        restarted = SqlAlchemySkillArtifactRepository(factory).get(
            tenant_id=tenant_id, artifact_ref=artifact["artifact_ref"]
        )
        other_tenant = repository.get(
            tenant_id=f"{tenant_id}-other", artifact_ref=artifact["artifact_ref"]
        )
        with factory() as session:
            row = session.execute(
                text(
                    """
                    SELECT count(*) AS total,
                           count(*) FILTER (
                               WHERE artifact_json::text ILIKE '%signature_bytes%'
                                  OR artifact_json::text ILIKE '%package_bytes%'
                                  OR artifact_json::text ILIKE '%verification_journal%'
                           ) AS raw_content
                    FROM ae_nsl_artifact WHERE tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": tenant_id},
            ).mappings().one()

        mismatch_before = int(row["total"])
        mismatch_rejected = False
        try:
            gateway.resolve_verified(
                **{**arguments, "expected_semantic_hash": "sha256:" + "0" * 64}
            )
        except SkillArtifactGatewayError as exc:
            mismatch_rejected = exc.error_code == "ae.skill_artifact_semantic_mismatch"

        unsigned_source = _AdmissionSource(golden)
        unsigned_gateway = SkillArtifactGateway(
            resolver=_Resolver(golden, signed=False),
            admission_source=unsigned_source,
            repository=repository,
        )
        unsigned_rejected = False
        try:
            unsigned_gateway.resolve_verified(**arguments)
        except SkillArtifactGatewayError as exc:
            unsigned_rejected = exc.error_code == "ae.skill_artifact_trust_rejected"
        with factory() as session:
            after_negative = int(
                session.execute(
                    text(
                        "SELECT count(*) FROM ae_nsl_artifact "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )

        checks = {
            "actual_test_database": database == EXPECTED_DATABASE,
            "actual_test_role": role == EXPECTED_ROLE,
            "exact_selector_resolved": resolver.calls == 3,
            "current_admission_checked": admissions.calls == 2,
            "canonical_artifact_persisted": artifact == replay == restarted,
            "idempotent_single_row": int(row["total"]) == 1,
            "tenant_isolation": other_tenant is None,
            "semantic_mismatch_rejected": mismatch_rejected,
            "unsigned_production_rejected": unsigned_rejected,
            "unsigned_zero_governance_calls": unsigned_source.calls == 0,
            "negative_paths_zero_residue": after_negative == mismatch_before,
            "bounded_projection_only": int(row["raw_content"] or 0) == 0,
        }
    finally:
        try:
            with factory.begin() as session:
                deleted = int(
                    session.execute(
                        text(
                            "DELETE FROM ae_nsl_artifact WHERE tenant_id = :tenant_id"
                        ),
                        {"tenant_id": tenant_id},
                    ).rowcount
                    or 0
                )
            with factory() as session:
                remaining = int(
                    session.execute(
                        text(
                            "SELECT count(*) FROM ae_nsl_artifact "
                            "WHERE tenant_id = :tenant_id"
                        ),
                        {"tenant_id": tenant_id},
                    ).scalar_one()
                )
            cleanup_counts = {"deleted": deleted, "remaining": remaining}
        finally:
            engine.dispose()

    checks["cleanup_complete"] = cleanup_counts.get("remaining") == 0
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "execution_state": "EXECUTED",
        "actual_postgres": True,
        "database": database,
        "role": role,
        "nsl_verification_mode": "source-backed-public-contract-projection",
        "remote_provider_mode": "not-required",
        "checks": checks,
        "row_counts": {"artifacts": 1 if artifact is not None else 0},
        "cleanup_counts": cleanup_counts,
    }


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _redact_detail(detail: str, *, database_url: str) -> str:
    redacted = detail.replace(database_url, redact_database_url(database_url))
    password = urlsplit(database_url).password
    return redacted.replace(unquote(password), "***") if password else redacted


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-S2",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    rows = evidence.get("row_counts") or {}
    cleanup = evidence.get("cleanup_counts") or {}
    return (
        "p6_s2_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"actual_postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"artifacts={rows.get('artifacts', 0)} "
        f"remaining={cleanup.get('remaining', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p6_s2_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
