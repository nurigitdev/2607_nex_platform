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

from nex_oa.platform_signed_token_postgres_smoke import (  # noqa: E402
    EXPECTED_CONSUMERS,
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    evaluate_platform_signed_token_postgres_smoke,
)
from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER  # noqa: E402
from nex_oa.service_principal_repository import build_service_principal_repository_for_runtime  # noqa: E402
from nex_oa.service_principal_service import OaServicePrincipalService  # noqa: E402
from nex_oa.signed_token_repository import build_signed_token_repository_for_runtime  # noqa: E402
from nex_oa.signing_key_service import OaSigningKeyService  # noqa: E402
from nex_oa.token_exchange_service import OaClientCredentialTokenExchangeService  # noqa: E402
from nex_oa.token_signing import InMemoryOaRsaSigningProvider  # noqa: E402
from nex_runtime import (  # noqa: E402
    BoundedJwksCache,
    SERVICE_SPECS,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    attach_service_persistence_runtime,
    build_service_app,
    issue_mock_service_token,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SMOKE_ENV = "NEX_PLATFORM_SIGNED_TOKEN_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
SCHEMA_VERSION = "platform_signed_token_postgres_smoke.v1"
SERVICE_ID = "nex-oa"
PROFILE = "test"


def run_platform_signed_token_postgres_smoke(
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
        workflow = _execute_platform_loopback(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )
        evidence = evaluate_platform_signed_token_postgres_smoke(
            {
                "planned": migration.planned,
                "applied": migration.applied,
                "skipped": migration.skipped,
            },
            workflow,
        )
        evidence.update(
            smoke_schema_version=SCHEMA_VERSION,
            slice="1280",
            requirement="S128",
            service_id=SERVICE_ID,
            profile=PROFILE,
            database_env=DATABASE_ENV,
            redacted_database_url=redact_database_url(database_url),
            migration={
                "planned_count": len(migration.planned),
                "applied": list(migration.applied),
                "skipped_count": len(migration.skipped),
            },
            next_slice="1281",
        )
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", exc.__class__.__name__)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__)


def _execute_platform_loopback(
    *,
    database_url: str,
    runtime_environ: Mapping[str, str],
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    principal_id = f"smoke-{suffix}"
    credential_id = f"cred-{suffix}"
    key_id = f"smoke-key-{suffix}"
    secret = f"smoke-secret-{uuid4().hex}"
    reference = f"file:///tmp/{key_id}"
    now_epoch = 1_790_985_600

    oa_app = build_service_app(
        SERVICE_SPECS[SERVICE_ID],
        include_oa_mock_auth_routes=False,
    )
    persistence = attach_service_persistence_runtime(
        oa_app,
        SERVICE_SPECS[SERVICE_ID],
        environ=runtime_environ,
    )
    if persistence.api_session_factory is None or persistence.api_engine is None:
        raise RuntimeError("OA PostgreSQL runtime is unavailable")
    principals = OaServicePrincipalService(
        build_service_principal_repository_for_runtime(persistence)
    )
    keys = OaSigningKeyService(
        repository=build_signed_token_repository_for_runtime(persistence),
        deployment_profile="test",
    )
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(reference)
    engine = persistence.api_engine
    result: dict[str, Any] = {}
    try:
        principals.upsert_principal(
            {
                "principal_id": principal_id,
                "service_id": "nex-oa",
                "display_name": "Platform Signed Token Smoke",
                "allowed_audiences": list(EXPECTED_CONSUMERS),
                "allowed_scopes": ["service:call"],
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
            key_id,
            target_state="ACTIVE",
            expected_revision=1,
            now_epoch=now_epoch,
        )
        exchange = OaClientCredentialTokenExchangeService(
            principal_service=principals,
            signing_key_service=keys,
            signing_provider=signer,
        )
        tokens = {
            audience: exchange.exchange(
                {
                    "grant_type": "client_credentials",
                    "credential_id": credential_id,
                    "client_secret": secret,
                    "audience": audience,
                    "scope": "service:call",
                },
                now_epoch=now_epoch,
                token_id=f"sat-{suffix}-{audience}",
            )["access_token"]
            for audience in EXPECTED_CONSUMERS
        }
        restarted_keys = OaSigningKeyService(
            repository=build_signed_token_repository_for_runtime(persistence),
            deployment_profile="test",
        )
        jwks = restarted_keys.jwks(at_epoch=now_epoch + 1)
        consumers = {
            audience: _exercise_consumer(
                audience=audience,
                token=tokens[audience],
                jwks=jwks,
                now_epoch=now_epoch + 1,
            )
            for audience in EXPECTED_CONSUMERS
        }
        observations = _database_observations(
            engine,
            principal_id=principal_id,
            credential_id=credential_id,
            key_id=key_id,
            secret=secret,
            tokens=tokens,
        )
        result = {
            "database": observations.pop("database"),
            "role": observations.pop("role"),
            "runtime_mode": persistence.mode,
            "checks": {
                "four_rs256_tokens_issued": len(tokens) == 4
                and all(token.count(".") == 2 for token in tokens.values()),
                "persisted_public_jwks_readback": jwks.get("key_count") == 1,
                "all_signed_consumers_accepted": all(
                    item.get("claim_status") == "VALID"
                    for item in consumers.values()
                ),
                "all_mock_tokens_rejected": all(
                    item.get("mock_rejected") is True
                    for item in consumers.values()
                ),
                "private_material_not_projected": "PRIVATE KEY"
                not in json.dumps(consumers, sort_keys=True),
                "raw_tokens_not_projected": not any(
                    token in json.dumps(consumers, sort_keys=True)
                    for token in tokens.values()
                ),
            },
            "consumers": consumers,
            "db_observations": observations,
        }
    finally:
        _cleanup(engine, principal_id=principal_id, key_id=key_id)
        result["cleanup_residue"] = _cleanup_residue(
            engine,
            principal_id=principal_id,
            key_id=key_id,
        )
        _dispose_runtime(persistence)
    return result


def _exercise_consumer(
    *,
    audience: str,
    token: str,
    jwks: Mapping[str, Any],
    now_epoch: int,
) -> dict[str, Any]:
    verifier = SignedServiceTokenVerifier(
        BoundedJwksCache(
            StaticJwksSource(jwks),
            clock=lambda: now_epoch,
        ),
        clock=lambda: now_epoch,
    )
    admission = ServiceTokenAdmissionRuntime(
        expected_audience=audience,
        rollout_profile="SIGNED_ONLY",
        signed_verifier=verifier,
        clock=lambda: now_epoch,
    )
    client = TestClient(
        build_service_app(
            SERVICE_SPECS[audience],
            service_token_admission=admission,
        )
    )
    signed = client.get(
        "/internal/v1/auth/service-claim",
        headers={"Authorization": f"Bearer {token}"},
    )
    mock = issue_mock_service_token(service_id="nex-oa", audience=audience)
    rejected = client.get(
        "/internal/v1/auth/service-claim",
        headers={"Authorization": f"Bearer {mock.access_token}"},
    )
    runtime = client.get(
        "/internal/v1/auth/service-token-runtime",
        headers={"Authorization": f"Bearer {token}"},
    )
    signed_payload = signed.json()
    runtime_payload = runtime.json()
    return {
        "claim_status": signed_payload.get("claim_status"),
        "caller_service_id": signed_payload.get("claims", {}).get("service_id"),
        "token_kind": signed_payload.get("claims", {}).get("token_kind"),
        "rollout_profile": runtime_payload.get("rollout_profile"),
        "mock_rejected": rejected.status_code == 401
        and rejected.json().get("error_code") == "nex.mock_token_forbidden",
        "accepted_signed_count": runtime_payload.get("admission_counts", {}).get(
            "accepted_signed"
        ),
        "rejected_count": runtime_payload.get("admission_counts", {}).get("rejected"),
        "jwks_cache_status": runtime_payload.get("jwks_cache", {}).get("status"),
    }


def _database_observations(
    engine: Any,
    *,
    principal_id: str,
    credential_id: str,
    key_id: str,
    secret: str,
    tokens: Mapping[str, str],
) -> dict[str, Any]:
    ordered_tokens = [tokens[service_id] for service_id in EXPECTED_CONSUMERS]
    params = {
        "principal_id": principal_id,
        "credential_id": credential_id,
        "key_id": key_id,
        "secret": secret,
        **{f"token_{index}": value for index, value in enumerate(ordered_tokens)},
    }
    token_parameters = ", ".join(f":token_{index}" for index in range(4))
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT current_database(), current_user, "
                "(SELECT count(*) FROM schema_migrations), "
                "(SELECT count(*) FROM schema_migrations WHERE version = '1264_oa_signed_token_lifecycle'), "
                "(SELECT count(*) FROM oa_service_principals WHERE principal_id = :principal_id), "
                "(SELECT count(*) FROM oa_service_creds WHERE credential_id = :credential_id), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id AND public_jwk ?| ARRAY['d','p','q','dp','dq','qi','oth']), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id AND private_key_ref LIKE 'file://%'), "
                f"(SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id AND (private_key_ref IN ({token_parameters}) OR public_jwk::text IN ({token_parameters}))), "
                "(SELECT count(*) FROM oa_service_creds WHERE credential_id = :credential_id AND secret_hash = :secret)"
            ),
            params,
        ).one()
    names = (
        "database",
        "role",
        "migration_ledger_count",
        "required_migration_count",
        "principal_count",
        "credential_count",
        "signing_key_count",
        "private_jwk_member_count",
        "private_reference_count",
        "raw_token_match_count",
        "raw_secret_match_count",
    )
    result = dict(zip(names, row, strict=True))
    result["issued_token_count"] = len(tokens)
    return result


def _cleanup(engine: Any, *, principal_id: str, key_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM oa_signing_keys WHERE key_id = :id"),
            {"id": key_id},
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
    key_id: str,
) -> dict[str, int]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id), "
                "(SELECT count(*) FROM oa_service_creds WHERE principal_id = :principal_id), "
                "(SELECT count(*) FROM oa_service_principals WHERE principal_id = :principal_id)"
            ),
            {"principal_id": principal_id, "key_id": key_id},
        ).one()
    return dict(
        zip(
            ("signing_key_count", "credential_count", "principal_count"),
            (int(value) for value in row),
            strict=True,
        )
    )


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
        return (
            "platform_signed_token_postgres_smoke=skip "
            f"reason={evidence.get('skip_reason')}"
        )
    if evidence.get("status") != "PASS":
        return (
            "platform_signed_token_postgres_smoke=fail "
            f"code={evidence.get('failure_code')}"
        )
    summary = evidence.get("summary") or {}
    workflow = evidence.get("workflow") or {}
    return (
        "platform_signed_token_postgres_smoke=pass "
        f"database={workflow.get('database')} "
        f"consumers={summary.get('passed_consumer_count', 0)}/"
        f"{summary.get('consumer_count', 0)} "
        f"tokens={summary.get('issued_token_count', 0)} "
        f"residue={summary.get('cleanup_residue_count', 0)} next=1281"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_signed_token_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
