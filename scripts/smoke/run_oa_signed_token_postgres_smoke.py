#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
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

from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER  # noqa: E402
from nex_oa.service_principal_repository import build_service_principal_repository_for_runtime  # noqa: E402
from nex_oa.service_principal_service import OaServicePrincipalService  # noqa: E402
from nex_oa.signed_token_postgres_smoke import (  # noqa: E402
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    evaluate_signed_token_postgres_smoke,
)
from nex_oa.signed_token_repository import build_signed_token_repository_for_runtime  # noqa: E402
from nex_oa.signing_key_service import OaSigningKeyService  # noqa: E402
from nex_oa.token_exchange_service import OaClientCredentialTokenExchangeService  # noqa: E402
from nex_oa.token_signing import InMemoryOaRsaSigningProvider  # noqa: E402
from nex_oa.token_validation_service import OaSignedTokenValidationService  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SMOKE_ENV = "NEX_OA_SIGNED_TOKEN_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
SCHEMA_VERSION = "oa_signed_token_postgres_smoke.v1"
SERVICE_ID = "nex-oa"
PROFILE = "test"


def run_oa_signed_token_postgres_smoke(
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
        workflow = _execute_signed_token_postgres_smoke(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )
        evidence = evaluate_signed_token_postgres_smoke(
            {
                "planned": migration.planned,
                "applied": migration.applied,
                "skipped": migration.skipped,
            },
            workflow,
        )
        evidence.update(
            smoke_schema_version=SCHEMA_VERSION,
            slice="1270",
            requirement="S127",
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


def _execute_signed_token_postgres_smoke(
    *, database_url: str, runtime_environ: Mapping[str, str]
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    principal_id = f"smoke-{suffix}"
    credential_id = f"cred-{suffix}"
    key_id = f"smoke-key-{suffix}"
    revocation_id = f"rev-{suffix}"
    token_id = f"sat-{suffix}"
    secret = f"smoke-secret-{uuid4().hex}"
    reference = f"file:///tmp/{key_id}"
    now_epoch = 1_790_985_600

    app = build_service_app(
        SERVICE_SPECS[SERVICE_ID], include_oa_mock_auth_routes=False
    )
    persistence = attach_service_persistence_runtime(
        app, SERVICE_SPECS[SERVICE_ID], environ=runtime_environ
    )
    if persistence.api_session_factory is None or persistence.api_engine is None:
        raise RuntimeError("OA signed-token PostgreSQL runtime is unavailable")
    principal_repository = build_service_principal_repository_for_runtime(persistence)
    signed_repository = build_signed_token_repository_for_runtime(persistence)
    principals = OaServicePrincipalService(principal_repository)
    keys = OaSigningKeyService(repository=signed_repository, deployment_profile="test")
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(reference)
    engine = persistence.api_engine
    result: dict[str, Any] = {}
    try:
        principals.upsert_principal(
            {
                "principal_id": principal_id,
                "service_id": "nex-cx",
                "display_name": "CX Signed Token Smoke",
                "allowed_audiences": ["nex-oa"],
                "allowed_scopes": ["token:introspect"],
                "expected_revision": 0,
            }
        )
        principals.issue_credential(
            principal_id,
            lifetime_days=1,
            now_epoch=now_epoch - 10,
            credential_id=credential_id,
            client_secret=secret,
        )
        keys.register_key(
            {
                "key_id": key_id,
                "issuer": PRODUCTION_TOKEN_ISSUER,
                "public_jwk": signer.public_jwk(reference, key_id=key_id),
                "private_key_ref": reference,
                "published_at": now_epoch - 330,
                "activate_at": now_epoch,
                "sign_until": now_epoch + 600,
                "verify_until": now_epoch + 930,
            }
        )
        keys.set_key_state(
            key_id, target_state="ACTIVE", expected_revision=1, now_epoch=now_epoch
        )
        exchange = OaClientCredentialTokenExchangeService(
            principal_service=principals,
            signing_key_service=keys,
            signing_provider=signer,
        )
        token = exchange.exchange(
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
        validator = OaSignedTokenValidationService(
            signing_key_service=keys,
            principal_service=principals,
        )
        active = validator.introspect(
            token, expected_audience="nex-oa", now_epoch=now_epoch + 1
        )

        restarted_principals = OaServicePrincipalService(
            build_service_principal_repository_for_runtime(persistence)
        )
        restarted_keys = OaSigningKeyService(
            repository=build_signed_token_repository_for_runtime(persistence),
            deployment_profile="test",
        )
        restarted_validator = OaSignedTokenValidationService(
            signing_key_service=restarted_keys,
            principal_service=restarted_principals,
        )
        restart_active = restarted_validator.introspect(
            token, expected_audience="nex-oa", now_epoch=now_epoch + 2
        )
        claims = restarted_validator.validate(
            token, expected_audience="nex-oa", now_epoch=now_epoch + 2
        )
        restarted_keys.revoke_token_claims(
            claims,
            reason_code="OPERATOR",
            now_epoch=now_epoch + 2,
            revocation_id=revocation_id,
        )
        revoked = restarted_validator.introspect(
            token, expected_audience="nex-oa", now_epoch=now_epoch + 2
        )
        observations = _database_observations(
            engine,
            principal_id=principal_id,
            credential_id=credential_id,
            key_id=key_id,
            revocation_id=revocation_id,
            token=token,
            token_id=token_id,
        )
        observations.update(
            restart_key_count=len(restarted_keys.list_keys()["items"]),
            restart_revocation_count=int(
                restarted_keys.is_jti_revoked(token_id, at_epoch=now_epoch + 2)
            ),
        )
        result = {
            "database": observations.pop("database"),
            "role": observations.pop("role"),
            "runtime_mode": persistence.mode,
            "checks": {
                "principal_and_credential_persisted": active.get("active") is True,
                "rs256_token_issued": token.count(".") == 2,
                "public_jwks_readback": restarted_keys.jwks(at_epoch=now_epoch + 2)["key_count"] == 1,
                "restart_validation_active": restart_active.get("active") is True,
                "revocation_persisted": revoked.get("active") is False and revoked.get("reason_code") == "oa.token_revoked",
                "private_key_remained_in_memory": "PRIVATE KEY" not in str(observations),
                "raw_token_not_persisted": observations["raw_token_match_count"] == 0,
                "jti_stored_as_digest": observations["jti_digest_match_count"] == 1 and observations["raw_jti_match_count"] == 0,
            },
            "db_observations": observations,
        }
    finally:
        _cleanup(
            engine,
            principal_id=principal_id,
            key_id=key_id,
            revocation_id=revocation_id,
        )
        result["cleanup_residue"] = _cleanup_residue(
            engine,
            principal_id=principal_id,
            key_id=key_id,
            revocation_id=revocation_id,
        )
        _dispose_runtime(persistence)
    return result


def _database_observations(
    engine: Any,
    *,
    principal_id: str,
    credential_id: str,
    key_id: str,
    revocation_id: str,
    token: str,
    token_id: str,
) -> dict[str, Any]:
    digest = sha256(token_id.encode("utf-8")).hexdigest()
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT current_database(), current_user, "
                "(SELECT count(*) FROM schema_migrations), "
                "(SELECT count(*) FROM schema_migrations WHERE version = '1264_oa_signed_token_lifecycle'), "
                "(SELECT count(*) FROM oa_service_principals WHERE principal_id = :principal_id), "
                "(SELECT count(*) FROM oa_service_creds WHERE credential_id = :credential_id), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id), "
                "(SELECT count(*) FROM oa_token_revocations WHERE revocation_id = :revocation_id), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id AND public_jwk ?| ARRAY['d','p','q','dp','dq','qi','oth']), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id AND private_key_ref LIKE 'file://%'), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id AND (private_key_ref = :token OR public_jwk::text = :token)), "
                "(SELECT count(*) FROM oa_token_revocations WHERE revocation_id = :revocation_id AND jti_digest = :digest), "
                "(SELECT count(*) FROM oa_token_revocations WHERE revocation_id = :revocation_id AND jti_digest = :token_id)"
            ),
            {
                "principal_id": principal_id,
                "credential_id": credential_id,
                "key_id": key_id,
                "revocation_id": revocation_id,
                "token": token,
                "digest": digest,
                "token_id": token_id,
            },
        ).one()
    names = (
        "database", "role", "migration_ledger_count", "required_migration_count",
        "principal_count", "credential_count", "signing_key_count", "revocation_count",
        "private_jwk_member_count", "private_reference_count", "raw_token_match_count",
        "jti_digest_match_count", "raw_jti_match_count",
    )
    return dict(zip(names, row, strict=True))


def _cleanup(
    engine: Any, *, principal_id: str, key_id: str, revocation_id: str
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM oa_token_revocations WHERE revocation_id = :id"),
            {"id": revocation_id},
        )
        connection.execute(
            text("DELETE FROM oa_signing_keys WHERE key_id = :id"), {"id": key_id}
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
    engine: Any, *, principal_id: str, key_id: str, revocation_id: str
) -> dict[str, int]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM oa_token_revocations WHERE revocation_id = :revocation_id), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id), "
                "(SELECT count(*) FROM oa_service_creds WHERE principal_id = :principal_id), "
                "(SELECT count(*) FROM oa_service_principals WHERE principal_id = :principal_id)"
            ),
            {"principal_id": principal_id, "key_id": key_id, "revocation_id": revocation_id},
        ).one()
    return dict(
        zip(
            ("revocation_count", "signing_key_count", "credential_count", "principal_count"),
            (int(value) for value in row),
            strict=True,
        )
    )


def _target_url_allowed(database_url: str) -> bool:
    try:
        parsed = urlsplit(database_url.replace("postgresql+psycopg", "postgresql", 1))
    except ValueError:
        return False
    return (
        parsed.scheme == "postgresql"
        and unquote(parsed.username or "") == EXPECTED_ROLE
        and parsed.path.lstrip("/") == EXPECTED_DATABASE
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
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"oa_signed_token_postgres_smoke=skip reason={evidence.get('skip_reason')}"
    if evidence.get("status") != "PASS":
        return f"oa_signed_token_postgres_smoke=fail code={evidence.get('failure_code')}"
    summary = evidence.get("summary") or {}
    return (
        "oa_signed_token_postgres_smoke=pass "
        f"database={evidence.get('workflow', {}).get('database')} "
        f"keys={summary.get('signing_key_count', 0)} "
        f"revocations={summary.get('revocation_count', 0)} "
        f"residue={summary.get('cleanup_residue_count', 0)} next=1271"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_signed_token_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
