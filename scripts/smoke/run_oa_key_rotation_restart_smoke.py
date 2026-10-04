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

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/_shared",
    ROOT / "services/nex-oa",
    ROOT / "scripts/db",
):
    sys.path.insert(0, str(path))

from nex_oa.mvp_key_rotation_smoke import (  # noqa: E402
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    evaluate_oa_key_rotation_smoke,
)
from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER  # noqa: E402
from nex_oa.service_principal_repository import (  # noqa: E402
    build_service_principal_repository_for_runtime,
)
from nex_oa.service_principal_service import OaServicePrincipalService  # noqa: E402
from nex_oa.signed_token_repository import (  # noqa: E402
    build_signed_token_repository_for_runtime,
)
from nex_oa.signing_key_service import OaSigningKeyService  # noqa: E402
from nex_oa.token_exchange_service import (  # noqa: E402
    OaClientCredentialTokenExchangeService,
)
from nex_oa.token_signing import InMemoryOaRsaSigningProvider  # noqa: E402
from nex_oa.token_validation_service import (  # noqa: E402
    OaSignedTokenValidationService,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SMOKE_ENV = "NEX_OA_KEY_ROTATION_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
SCHEMA_VERSION = "oa_key_rotation_restart_smoke.v1"
SERVICE_ID = "nex-oa"
PROFILE = "test"


def run_oa_key_rotation_restart_smoke(
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
        workflow = _execute_rotation_workflow(
            runtime_environ={
                **env,
                SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            }
        )
        evidence = evaluate_oa_key_rotation_smoke(
            {
                "planned": migration.planned,
                "applied": migration.applied,
                "skipped": migration.skipped,
            },
            workflow,
        )
        evidence.update(
            smoke_schema_version=SCHEMA_VERSION,
            slice="1296",
            requirement="S130",
            service_id=SERVICE_ID,
            profile=PROFILE,
            database_env=DATABASE_ENV,
            redacted_database_url=redact_database_url(database_url),
            migration={
                "planned_count": len(migration.planned),
                "applied": list(migration.applied),
                "skipped_count": len(migration.skipped),
            },
            next_slice="1297",
        )
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", exc.__class__.__name__)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__)


def _execute_rotation_workflow(
    *, runtime_environ: Mapping[str, str]
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    principal_id = f"rotate-{suffix}"
    credential_id = f"cred-{suffix}"
    old_key_id = f"old-key-{suffix}"
    new_key_id = f"new-key-{suffix}"
    old_token_id = f"sat-old-{suffix}"
    new_token_id = f"sat-new-{suffix}"
    secret = f"rotate-secret-{uuid4().hex}"
    old_reference = f"file:///tmp/{old_key_id}"
    new_reference = f"file:///tmp/{new_key_id}"
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(old_reference)
    signer.generate_key(new_reference)

    first = _build_stack(runtime_environ)
    first_persistence = first["persistence"]
    second: dict[str, Any] | None = None
    old_token = ""
    new_token = ""
    result: dict[str, Any] = {}
    try:
        first["principals"].upsert_principal(
            {
                "principal_id": principal_id,
                "service_id": "nex-cx",
                "display_name": "S130 Rotation Principal",
                "allowed_audiences": ["nex-oa"],
                "allowed_scopes": ["token:introspect"],
                "expected_revision": 0,
            }
        )
        first["principals"].issue_credential(
            principal_id,
            lifetime_days=1,
            now_epoch=800,
            credential_id=credential_id,
            client_secret=secret,
        )
        _register_key(
            first["keys"],
            signer,
            key_id=old_key_id,
            reference=old_reference,
            published_at=500,
            activate_at=830,
            sign_until=1_400,
            verify_until=1_730,
        )
        _register_key(
            first["keys"],
            signer,
            key_id=new_key_id,
            reference=new_reference,
            published_at=700,
            activate_at=1_030,
            sign_until=1_600,
            verify_until=1_930,
        )
        first["keys"].set_key_state(
            old_key_id,
            target_state="ACTIVE",
            expected_revision=1,
            now_epoch=830,
        )
        old_token = _exchange(
            first,
            signer,
            credential_id=credential_id,
            secret=secret,
            now_epoch=1_000,
            token_id=old_token_id,
        )
        first["keys"].set_key_state(
            old_key_id,
            target_state="VERIFY_ONLY",
            expected_revision=2,
            now_epoch=1_030,
        )
        first["keys"].set_key_state(
            new_key_id,
            target_state="ACTIVE",
            expected_revision=1,
            now_epoch=1_030,
        )
        _dispose_runtime(first_persistence)

        second = _build_stack(runtime_environ)
        new_token = _exchange(
            second,
            signer,
            credential_id=credential_id,
            secret=secret,
            now_epoch=1_031,
            token_id=new_token_id,
        )
        validator = OaSignedTokenValidationService(
            signing_key_service=second["keys"],
            principal_service=second["principals"],
        )
        old_claims = validator.validate(
            old_token,
            expected_audience="nex-oa",
            required_scopes=("token:introspect",),
            now_epoch=1_032,
        )
        new_claims = validator.validate(
            new_token,
            expected_audience="nex-oa",
            required_scopes=("token:introspect",),
            now_epoch=1_032,
        )
        jwks = second["keys"].jwks(at_epoch=1_032)
        key_list = second["keys"].list_keys()["items"]
        states = {item["key_id"]: item["state"] for item in key_list}
        observations = _database_observations(
            second["persistence"].api_engine,
            principal_id=principal_id,
            old_key_id=old_key_id,
            new_key_id=new_key_id,
            old_token=old_token,
            new_token=new_token,
        )
        result = {
            "database": observations.pop("database"),
            "role": observations.pop("role"),
            "runtime_mode": second["persistence"].mode,
            "jwks_key_count": jwks["key_count"],
            "checks": {
                "old_token_valid_after_restart": (
                    old_claims["jti"] == old_token_id
                ),
                "new_token_issued_after_restart": (
                    new_claims["jti"] == new_token_id
                ),
                "jwks_overlap_after_rotation": (
                    jwks["key_count"] == 2
                    and {item["kid"] for item in jwks["keys"]}
                    == {old_key_id, new_key_id}
                ),
                "exactly_one_active_key": (
                    states.get(old_key_id) == "VERIFY_ONLY"
                    and states.get(new_key_id) == "ACTIVE"
                    and sum(state == "ACTIVE" for state in states.values()) == 1
                ),
                "external_custody_available_after_restart": (
                    old_token.count(".") == 2 and new_token.count(".") == 2
                ),
            },
            "db_observations": observations,
        }
    finally:
        cleanup_runtime = (
            second["persistence"] if second is not None else first_persistence
        )
        engine = cleanup_runtime.api_engine
        if engine is not None:
            _cleanup(
                engine,
                principal_id=principal_id,
                old_key_id=old_key_id,
                new_key_id=new_key_id,
            )
            result["cleanup_residue"] = _cleanup_residue(
                engine,
                principal_id=principal_id,
                old_key_id=old_key_id,
                new_key_id=new_key_id,
            )
        _dispose_runtime(cleanup_runtime)
    return result


def _build_stack(runtime_environ: Mapping[str, str]) -> dict[str, Any]:
    app = build_service_app(
        SERVICE_SPECS[SERVICE_ID], include_oa_mock_auth_routes=False
    )
    persistence = attach_service_persistence_runtime(
        app, SERVICE_SPECS[SERVICE_ID], environ=runtime_environ
    )
    if persistence.api_session_factory is None or persistence.api_engine is None:
        raise RuntimeError("OA PostgreSQL rotation runtime is unavailable")
    return {
        "persistence": persistence,
        "principals": OaServicePrincipalService(
            build_service_principal_repository_for_runtime(persistence)
        ),
        "keys": OaSigningKeyService(
            repository=build_signed_token_repository_for_runtime(persistence),
            deployment_profile="test",
        ),
    }


def _register_key(
    keys: OaSigningKeyService,
    signer: InMemoryOaRsaSigningProvider,
    *,
    key_id: str,
    reference: str,
    published_at: int,
    activate_at: int,
    sign_until: int,
    verify_until: int,
) -> None:
    keys.register_key(
        {
            "key_id": key_id,
            "issuer": PRODUCTION_TOKEN_ISSUER,
            "public_jwk": signer.public_jwk(reference, key_id=key_id),
            "private_key_ref": reference,
            "published_at": published_at,
            "activate_at": activate_at,
            "sign_until": sign_until,
            "verify_until": verify_until,
        }
    )


def _exchange(
    stack: Mapping[str, Any],
    signer: InMemoryOaRsaSigningProvider,
    *,
    credential_id: str,
    secret: str,
    now_epoch: int,
    token_id: str,
) -> str:
    service = OaClientCredentialTokenExchangeService(
        principal_service=stack["principals"],
        signing_key_service=stack["keys"],
        signing_provider=signer,
    )
    return service.exchange(
        {
            "grant_type": "client_credentials",
            "credential_id": credential_id,
            "client_secret": secret,
            "audience": "nex-oa",
            "scope": "token:introspect",
        },
        now_epoch=now_epoch,
        token_id=token_id,
    )["access_token"]


def _database_observations(
    engine: Any,
    *,
    principal_id: str,
    old_key_id: str,
    new_key_id: str,
    old_token: str,
    new_token: str,
) -> dict[str, Any]:
    params = {
        "principal_id": principal_id,
        "old_key_id": old_key_id,
        "new_key_id": new_key_id,
        "old_token": old_token,
        "new_token": new_token,
    }
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT current_database(), current_user, "
                "(SELECT count(*) FROM schema_migrations), "
                "(SELECT count(*) FROM oa_service_principals WHERE principal_id = :principal_id), "
                "(SELECT count(*) FROM oa_service_creds WHERE principal_id = :principal_id), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id IN (:old_key_id, :new_key_id)), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id IN (:old_key_id, :new_key_id) AND state = 'ACTIVE'), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id IN (:old_key_id, :new_key_id) AND state = 'VERIFY_ONLY'), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id IN (:old_key_id, :new_key_id) AND public_jwk ?| ARRAY['d','p','q','dp','dq','qi','oth']), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id IN (:old_key_id, :new_key_id) AND private_key_ref LIKE 'file://%'), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id IN (:old_key_id, :new_key_id) AND (private_key_ref IN (:old_token, :new_token) OR public_jwk::text IN (:old_token, :new_token)))"
            ),
            params,
        ).one()
    names = (
        "database",
        "role",
        "migration_ledger_count",
        "principal_count",
        "credential_count",
        "signing_key_count",
        "active_key_count",
        "verify_only_key_count",
        "private_jwk_member_count",
        "private_reference_count",
        "raw_token_match_count",
    )
    return dict(zip(names, row, strict=True))


def _cleanup(
    engine: Any,
    *,
    principal_id: str,
    old_key_id: str,
    new_key_id: str,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM oa_signing_keys "
                "WHERE key_id IN (:old_key_id, :new_key_id)"
            ),
            {"old_key_id": old_key_id, "new_key_id": new_key_id},
        )
        connection.execute(
            text("DELETE FROM oa_service_creds WHERE principal_id = :id"),
            {"id": principal_id},
        )
        connection.execute(
            text("DELETE FROM oa_service_principals WHERE principal_id = :id"),
            {"id": principal_id},
        )


def _cleanup_residue(
    engine: Any,
    *,
    principal_id: str,
    old_key_id: str,
    new_key_id: str,
) -> dict[str, int]:
    params = {
        "principal_id": principal_id,
        "old_key_id": old_key_id,
        "new_key_id": new_key_id,
    }
    queries = {
        "signing_key_count": (
            "SELECT count(*) FROM oa_signing_keys "
            "WHERE key_id IN (:old_key_id, :new_key_id)"
        ),
        "credential_count": (
            "SELECT count(*) FROM oa_service_creds "
            "WHERE principal_id = :principal_id"
        ),
        "principal_count": (
            "SELECT count(*) FROM oa_service_principals "
            "WHERE principal_id = :principal_id"
        ),
    }
    with engine.connect() as connection:
        return {
            name: int(connection.execute(text(sql), params).scalar_one())
            for name, sql in queries.items()
        }


def _target_url_allowed(database_url: str) -> bool:
    try:
        parsed = urlsplit(
            database_url.replace("postgresql+psycopg", "postgresql", 1)
        )
    except ValueError:
        return False
    return (
        parsed.scheme == "postgresql"
        and unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _dispose_runtime(runtime: Any) -> None:
    seen: set[int] = set()
    for engine in (runtime.api_engine, runtime.worker_engine):
        if engine is not None and id(engine) not in seen:
            seen.add(id(engine))
            engine.dispose()


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1296",
        "requirement": "S130",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"oa_key_rotation_postgres=skip reason={SMOKE_ENV}"
    if evidence.get("status") != "PASS":
        return (
            "oa_key_rotation_postgres=fail "
            f"code={evidence.get('failure_code')}"
        )
    summary = evidence.get("summary") or {}
    workflow = evidence.get("workflow") or {}
    return (
        "oa_key_rotation_postgres=pass "
        f"database={workflow.get('database')} "
        f"migrations={summary.get('migration_count', 0)} "
        f"checks={summary.get('rotation_check_count', 0)} "
        f"jwks={summary.get('jwks_key_count', 0)} "
        f"residue={summary.get('cleanup_residue_count', 0)} next=1297"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_oa_key_rotation_restart_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
