#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/_shared",
    ROOT / "services/nex-oa",
    ROOT / "scripts/db",
):
    sys.path.insert(0, str(path))

from nex_oa.service_principal_api import (  # noqa: E402
    OA_SERVICE_PRINCIPAL_ADMIN_SCOPE,
    OA_SERVICE_PRINCIPAL_READ_SCOPE,
    register_service_principal_routes,
)
from nex_oa.service_principal_postgres_smoke import (  # noqa: E402
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    evaluate_service_principal_postgres_smoke,
)
from nex_oa.service_principal_repository import (  # noqa: E402
    build_service_principal_repository_for_runtime,
)
from nex_oa.service_principal_service import OaServicePrincipalService  # noqa: E402
from nex_oa.service_principals import OaServicePrincipalError  # noqa: E402
from nex_runtime import (  # noqa: E402
    DEFAULT_SERVICE_SCOPE,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SMOKE_ENV = "NEX_OA_SERVICE_PRINCIPAL_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
SCHEMA_VERSION = "oa_service_principal_postgres_smoke.v1"
SERVICE_ID = "nex-oa"
PROFILE = "test"


def run_oa_service_principal_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
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
            SERVICE_ID,
            database_url=database_url,
            profile=PROFILE,
        )
        workflow = _execute_service_principal_postgres_smoke(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )
        evidence = evaluate_service_principal_postgres_smoke(
            {
                "planned": migration.planned,
                "applied": migration.applied,
                "skipped": migration.skipped,
            },
            workflow,
        )
        evidence.update(
            smoke_schema_version=SCHEMA_VERSION,
            slice="1260",
            requirement="S126",
            service_id=SERVICE_ID,
            profile=PROFILE,
            database_env=DATABASE_ENV,
            redacted_database_url=redact_database_url(database_url),
            migration={
                "planned_count": len(migration.planned),
                "applied": list(migration.applied),
                "skipped_count": len(migration.skipped),
            },
        )
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", exc.__class__.__name__)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__)


def _execute_service_principal_postgres_smoke(
    *, database_url: str, runtime_environ: Mapping[str, str]
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    principal_id = f"smoke-{suffix}"
    first_id = f"cred-a-{suffix}"
    second_id = f"cred-b-{suffix}"
    first_secret = f"smoke-first-{uuid4().hex}"
    second_secret = f"smoke-second-{uuid4().hex}"
    now_epoch = 1_790_985_600

    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    persistence = attach_service_persistence_runtime(
        app, SERVICE_SPECS[SERVICE_ID], environ=runtime_environ
    )
    if persistence.api_session_factory is None or persistence.api_engine is None:
        raise RuntimeError("OA service-principal PostgreSQL runtime is unavailable")
    repository = build_service_principal_repository_for_runtime(persistence)
    service = OaServicePrincipalService(repository)
    register_service_principal_routes(
        app,
        service=service,
        audit_emitter=OperationalEventEmitter(
            service_id=SERVICE_ID, store=InMemoryOperationalEventStore()
        ),
    )
    client = TestClient(app)
    engine = persistence.api_engine
    result: dict[str, Any] = {}
    try:
        admin = _service_headers(OA_SERVICE_PRINCIPAL_ADMIN_SCOPE)
        reader = _service_headers(OA_SERVICE_PRINCIPAL_READ_SCOPE)
        created = client.post(
            "/internal/v1/service-principals",
            headers=admin,
            json={
                "principal_id": principal_id,
                "service_id": "nex-cx",
                "display_name": "CX Smoke Runtime",
                "allowed_audiences": ["nex-mo"],
                "allowed_scopes": ["generation:request"],
                "expected_revision": 0,
            },
        )
        created.raise_for_status()
        issued = service.issue_credential(
            principal_id,
            lifetime_days=30,
            now_epoch=now_epoch,
            credential_id=first_id,
            client_secret=first_secret,
        )
        first_verified = service.verify_client_secret(
            first_id, first_secret, now_epoch=now_epoch + 1
        )
        rotated = service.rotate_credential(
            first_id,
            expected_revision=1,
            lifetime_days=30,
            grace_seconds=60,
            now_epoch=now_epoch + 2,
            new_credential_id=second_id,
            client_secret=second_secret,
        )
        old_grace_verified = service.verify_client_secret(
            first_id, first_secret, now_epoch=now_epoch + 3
        )
        replacement_verified = service.verify_client_secret(
            second_id, second_secret, now_epoch=now_epoch + 3
        )
        principal_list = client.get(
            "/internal/v1/service-principals?service_id=nex-cx", headers=reader
        )
        credential_list = client.get(
            f"/internal/v1/service-principals/{principal_id}/credentials",
            headers=reader,
        )
        credential_detail = client.get(
            f"/internal/v1/service-credentials/{second_id}", headers=reader
        )
        for response in (principal_list, credential_list, credential_detail):
            response.raise_for_status()
        revoked = client.patch(
            f"/internal/v1/service-credentials/{second_id}/status",
            headers=admin,
            json={"target_status": "REVOKED", "expected_revision": 1},
        )
        revoked.raise_for_status()
        revoked_rejected = False
        try:
            service.verify_client_secret(
                second_id, second_secret, now_epoch=now_epoch + 4
            )
        except OaServicePrincipalError as exc:
            revoked_rejected = exc.status_code == 401

        observations = _database_observations(
            engine,
            principal_id=principal_id,
            first_secret=first_secret,
            second_secret=second_secret,
        )
        restarted_service = OaServicePrincipalService(
            build_service_principal_repository_for_runtime(persistence)
        )
        restart_principal = restarted_service.get_principal(principal_id)
        restart_credentials = restarted_service.list_credentials(principal_id)
        observations.update(
            restart_principal_count=int(
                restart_principal["principal"]["principal_id"] == principal_id
            ),
            restart_credential_count=restart_credentials["count"],
        )
        result = {
            "database": observations.pop("database"),
            "role": observations.pop("role"),
            "runtime_mode": persistence.mode,
            "checks": {
                "protected_create": created.json()["principal"]["principal_id"]
                == principal_id,
                "one_time_issue": (
                    issued["credential"]["credential_id"] == first_id
                    and issued["secret_display"] == "once"
                    and "secret_hash" not in issued["credential"]
                ),
                "initial_secret_verified": first_verified["principal_id"]
                == principal_id,
                "rotation_persisted": (
                    rotated["rotated_credential"]["status"] == "ROTATING"
                    and rotated["credential"]["credential_id"] == second_id
                ),
                "old_secret_grace_verified": old_grace_verified["credential_id"]
                == first_id,
                "replacement_secret_verified": replacement_verified["credential_id"]
                == second_id,
                "protected_readback": (
                    principal_list.json()["count"] == 1
                    and credential_list.json()["count"] == 2
                    and credential_detail.json()["credential"]["credential_id"]
                    == second_id
                ),
                "revocation_persisted": revoked.json()["credential"]["status"]
                == "REVOKED",
                "revoked_secret_rejected": revoked_rejected,
                "restart_readback": (
                    observations["restart_principal_count"] == 1
                    and observations["restart_credential_count"] == 2
                ),
            },
            "db_observations": observations,
        }
    finally:
        _cleanup(engine, principal_id=principal_id)
        result["cleanup_residue"] = _cleanup_residue(
            engine, principal_id=principal_id
        )
        _dispose_runtime(persistence)
    return result


def _database_observations(
    engine: Any,
    *,
    principal_id: str,
    first_secret: str,
    second_secret: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT current_database(), current_user, "
                "(SELECT count(*) FROM oa_service_principals WHERE principal_id = :principal_id), "
                "(SELECT count(*) FROM oa_service_creds WHERE principal_id = :principal_id), "
                "(SELECT count(*) FROM oa_service_creds WHERE principal_id = :principal_id AND status = 'ROTATING'), "
                "(SELECT count(*) FROM oa_service_creds WHERE principal_id = :principal_id AND status = 'REVOKED'), "
                "(SELECT count(*) FROM oa_service_creds WHERE principal_id = :principal_id AND secret_hash LIKE '$argon2id$%'), "
                "(SELECT count(*) FROM oa_service_creds WHERE principal_id = :principal_id AND secret_hash IN (:first_secret, :second_secret)), "
                "(SELECT count(DISTINCT secret_hint) FROM oa_service_creds WHERE principal_id = :principal_id), "
                "(SELECT count(*) FROM schema_migrations), "
                "(SELECT count(*) FROM schema_migrations WHERE version = '1254_oa_service_principal_lifecycle')"
            ),
            {
                "principal_id": principal_id,
                "first_secret": first_secret,
                "second_secret": second_secret,
            },
        ).one()
    return {
        "database": row[0],
        "role": row[1],
        "principal_count": int(row[2]),
        "credential_count": int(row[3]),
        "rotating_credential_count": int(row[4]),
        "revoked_credential_count": int(row[5]),
        "argon2id_hash_count": int(row[6]),
        "plaintext_match_count": int(row[7]),
        "distinct_secret_hint_count": int(row[8]),
        "migration_ledger_count": int(row[9]),
        "required_migration_count": int(row[10]),
    }


def _cleanup(engine: Any, *, principal_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM oa_service_creds WHERE principal_id = :principal_id"),
            {"principal_id": principal_id},
        )
        connection.execute(
            text("DELETE FROM oa_service_principals WHERE principal_id = :principal_id"),
            {"principal_id": principal_id},
        )


def _cleanup_residue(engine: Any, *, principal_id: str) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            "credential_count": int(
                connection.execute(
                    text("SELECT count(*) FROM oa_service_creds WHERE principal_id = :principal_id"),
                    {"principal_id": principal_id},
                ).scalar_one()
            ),
            "principal_count": int(
                connection.execute(
                    text("SELECT count(*) FROM oa_service_principals WHERE principal_id = :principal_id"),
                    {"principal_id": principal_id},
                ).scalar_one()
            ),
        }


def _service_headers(*scopes: str) -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": str(uuid4()),
        "traceparent": f"00-{uuid4().hex}-{uuid4().hex[:16]}-01",
    }


def _dispose_runtime(runtime: Any) -> None:
    for engine in (runtime.api_engine, runtime.worker_engine):
        if engine is not None:
            engine.dispose()


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1260",
        "requirement": "S126",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"oa_service_principal_postgres_smoke=skipped reason={SMOKE_ENV}"
    summary = evidence.get("summary") or {}
    workflow = evidence.get("workflow") or {}
    return (
        "oa_service_principal_postgres_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"database={workflow.get('database', 'not-run')} "
        f"credentials={summary.get('persisted_credential_count', 0)} "
        f"argon2id={summary.get('argon2id_hash_count', 0)} "
        f"residue={summary.get('cleanup_residue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_oa_service_principal_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
