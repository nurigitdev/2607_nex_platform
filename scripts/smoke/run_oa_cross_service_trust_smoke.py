#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/_shared",
    ROOT / "services/nex-oa",
    ROOT / "scripts/db",
):
    sys.path.insert(0, str(path))

from nex_oa.mvp_cross_service_trust_smoke import (  # noqa: E402
    EXPECTED_CONSUMERS,
    EXPECTED_DATABASE,
    EXPECTED_ROLE,
    evaluate_oa_cross_service_trust_smoke,
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
    AdmittedServiceClaims,
    BoundedJwksCache,
    SERVICE_SPECS,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    admit_service_token_from_request,
    attach_service_persistence_runtime,
    build_service_app,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SMOKE_ENV = "NEX_OA_CROSS_SERVICE_TRUST_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
SCHEMA_VERSION = "oa_cross_service_trust_smoke.v1"
SERVICE_ID = "nex-oa"
PROFILE = "test"


class _DirectOaTokenIntrospector:
    def __init__(
        self,
        validator: OaSignedTokenValidationService,
        *,
        now_epoch: int,
    ) -> None:
        self.validator = validator
        self.now_epoch = now_epoch

    def introspect(
        self,
        token: str,
        *,
        expected_audience: str,
        required_scopes: Sequence[str],
    ) -> Mapping[str, Any]:
        return self.validator.introspect(
            token,
            expected_audience=expected_audience,
            required_scopes=required_scopes,
            now_epoch=self.now_epoch,
        )


def run_oa_cross_service_trust_smoke(
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
        workflow = _execute_cross_service_workflow(
            runtime_environ={
                **env,
                SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            }
        )
        evidence = evaluate_oa_cross_service_trust_smoke(
            {
                "planned": migration.planned,
                "applied": migration.applied,
                "skipped": migration.skipped,
            },
            workflow,
        )
        evidence.update(
            smoke_schema_version=SCHEMA_VERSION,
            slice="1298",
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
            next_slice="1299",
        )
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", exc.__class__.__name__)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__)


def _execute_cross_service_workflow(
    *, runtime_environ: Mapping[str, str]
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    principal_id = f"platform-{suffix}"
    credential_id = f"cred-{suffix}"
    key_id = f"platform-key-{suffix}"
    secret = f"platform-secret-{uuid4().hex}"
    reference = f"file:///tmp/{key_id}"
    now_epoch = 1_790_985_600
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(reference)

    first = _build_stack(runtime_environ)
    first_persistence = first["persistence"]
    second: dict[str, Any] | None = None
    tokens: dict[str, str] = {}
    revocation_ids = {
        audience: f"rev-{suffix}-{index}"
        for index, audience in enumerate(EXPECTED_CONSUMERS)
    }
    result: dict[str, Any] = {}
    try:
        first["principals"].upsert_principal(
            {
                "principal_id": principal_id,
                "service_id": "nex-oa",
                "display_name": "S130 Platform Trust Principal",
                "allowed_audiences": list(EXPECTED_CONSUMERS),
                "allowed_scopes": ["service:call"],
                "expected_revision": 0,
            }
        )
        first["principals"].issue_credential(
            principal_id,
            lifetime_days=1,
            now_epoch=now_epoch - 10,
            credential_id=credential_id,
            client_secret=secret,
        )
        first["keys"].register_key(
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
        first["keys"].set_key_state(
            key_id,
            target_state="ACTIVE",
            expected_revision=1,
            now_epoch=now_epoch,
        )
        exchange = OaClientCredentialTokenExchangeService(
            principal_service=first["principals"],
            signing_key_service=first["keys"],
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
                token_id=f"sat-{suffix}-{index}",
            )["access_token"]
            for index, audience in enumerate(EXPECTED_CONSUMERS)
        }
        _dispose_runtime(first_persistence)

        second = _build_stack(runtime_environ)
        validator = OaSignedTokenValidationService(
            signing_key_service=second["keys"],
            principal_service=second["principals"],
        )
        jwks = second["keys"].jwks(at_epoch=now_epoch + 1)
        consumers = {
            audience: _exercise_consumer(
                audience=audience,
                token=tokens[audience],
                jwks=jwks,
                validator=validator,
                keys=second["keys"],
                revocation_id=revocation_ids[audience],
                now_epoch=now_epoch + 1,
            )
            for audience in EXPECTED_CONSUMERS
        }
        observations = _database_observations(
            second["persistence"].api_engine,
            principal_id=principal_id,
            credential_id=credential_id,
            key_id=key_id,
            secret=secret,
            tokens=tokens,
            revocation_ids=revocation_ids,
        )
        result = {
            "database": observations.pop("database"),
            "role": observations.pop("role"),
            "runtime_mode": second["persistence"].mode,
            "checks": {
                "four_tokens_issued": len(tokens) == 4
                and all(token.count(".") == 2 for token in tokens.values()),
                "oa_runtime_restarted": second["persistence"] is not first_persistence,
                "persisted_jwks_loaded": jwks.get("key_count") == 1,
                "all_sensitive_routes_introspected": all(
                    item.get("introspection_status") == "ACTIVE"
                    for item in consumers.values()
                ),
                "all_revoked_tokens_denied": all(
                    item.get("revoked_denied") is True
                    for item in consumers.values()
                ),
            },
            "consumers": consumers,
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
                key_id=key_id,
                revocation_ids=revocation_ids,
            )
            result["cleanup_residue"] = _cleanup_residue(
                engine,
                principal_id=principal_id,
                key_id=key_id,
                revocation_ids=revocation_ids,
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
        raise RuntimeError("OA PostgreSQL platform trust runtime is unavailable")
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


def _exercise_consumer(
    *,
    audience: str,
    token: str,
    jwks: Mapping[str, Any],
    validator: OaSignedTokenValidationService,
    keys: OaSigningKeyService,
    revocation_id: str,
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
        introspector=_DirectOaTokenIntrospector(
            validator,
            now_epoch=now_epoch,
        ),
        clock=lambda: now_epoch,
    )
    app = build_service_app(
        SERVICE_SPECS[audience],
        service_token_admission=admission,
    )

    @app.post("/internal/v1/s130/platform-trust")
    async def protected(request: Request) -> Any:
        admitted = admit_service_token_from_request(
            request,
            request.headers.get("Authorization"),
            expected_audience=audience,
            required_scopes=("service:call",),
            route_class="ADMIN",
        )
        if not isinstance(admitted, AdmittedServiceClaims):
            return admitted
        return {
            "claim_status": "VALID",
            "claims": admitted.to_wire(),
        }

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    active = client.post("/internal/v1/s130/platform-trust", headers=headers)
    mock = issue_mock_service_token(service_id="nex-oa", audience=audience)
    mock_response = client.post(
        "/internal/v1/s130/platform-trust",
        headers={"Authorization": f"Bearer {mock.access_token}"},
    )
    claims = validator.validate(
        token,
        expected_audience=audience,
        required_scopes=("service:call",),
        now_epoch=now_epoch,
    )
    keys.revoke_token_claims(
        claims,
        reason_code="OPERATOR",
        now_epoch=now_epoch,
        revocation_id=revocation_id,
    )
    revoked = client.post("/internal/v1/s130/platform-trust", headers=headers)
    active_payload = active.json()
    revoked_payload = revoked.json()
    snapshot = admission.public_snapshot()
    admitted_claims = active_payload.get("claims", {})
    return {
        "status_code": active.status_code,
        "claim_status": active_payload.get("claim_status"),
        "caller_service_id": admitted_claims.get("service_id"),
        "token_kind": admitted_claims.get("token_kind"),
        "introspection_status": admitted_claims.get("introspection_status"),
        "rollout_profile": snapshot.get("rollout_profile"),
        "mock_rejected": mock_response.status_code == 401
        and mock_response.json().get("error_code") == "nex.mock_token_forbidden",
        "revoked_denied": revoked.status_code == 401,
        "revoked_error_code": revoked_payload.get("error_code"),
        "accepted_signed_count": snapshot["admission_counts"]["accepted_signed"],
        "introspected_count": snapshot["admission_counts"]["introspected"],
        "rejected_count": snapshot["admission_counts"]["rejected"],
    }


def _database_observations(
    engine: Any,
    *,
    principal_id: str,
    credential_id: str,
    key_id: str,
    secret: str,
    tokens: Mapping[str, str],
    revocation_ids: Mapping[str, str],
) -> dict[str, Any]:
    ordered_tokens = [tokens[service_id] for service_id in EXPECTED_CONSUMERS]
    ordered_revocations = [
        revocation_ids[service_id] for service_id in EXPECTED_CONSUMERS
    ]
    params = {
        "principal_id": principal_id,
        "credential_id": credential_id,
        "key_id": key_id,
        "secret": secret,
        **{f"token_{index}": value for index, value in enumerate(ordered_tokens)},
        **{
            f"revocation_{index}": value
            for index, value in enumerate(ordered_revocations)
        },
    }
    token_parameters = ", ".join(
        f":token_{index}" for index in range(len(EXPECTED_CONSUMERS))
    )
    revocation_parameters = ", ".join(
        f":revocation_{index}" for index in range(len(EXPECTED_CONSUMERS))
    )
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT current_database(), current_user, "
                "(SELECT count(*) FROM schema_migrations), "
                "(SELECT count(*) FROM oa_service_principals WHERE principal_id = :principal_id), "
                "(SELECT count(*) FROM oa_service_creds WHERE credential_id = :credential_id), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id), "
                f"(SELECT count(*) FROM oa_token_revocations WHERE revocation_id IN ({revocation_parameters})), "
                f"(SELECT count(*) FROM oa_token_revocations WHERE revocation_id IN ({revocation_parameters}) AND jti_digest ~ '^[0-9a-f]{{64}}$'), "
                "(SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id AND public_jwk ?| ARRAY['d','p','q','dp','dq','qi','oth']), "
                f"((SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id AND (private_key_ref IN ({token_parameters}) OR public_jwk::text IN ({token_parameters}))) + (SELECT count(*) FROM oa_token_revocations WHERE revocation_id IN ({revocation_parameters}) AND jti_digest IN ({token_parameters}))), "
                "(SELECT count(*) FROM oa_service_creds WHERE credential_id = :credential_id AND secret_hash = :secret)"
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
        "revocation_count",
        "revocation_digest_count",
        "private_jwk_member_count",
        "raw_token_match_count",
        "raw_secret_match_count",
    )
    result = dict(zip(names, row, strict=True))
    result["issued_token_count"] = len(tokens)
    return result


def _cleanup(
    engine: Any,
    *,
    principal_id: str,
    key_id: str,
    revocation_ids: Mapping[str, str],
) -> None:
    params = {
        "principal_id": principal_id,
        "key_id": key_id,
        **{
            f"revocation_{index}": revocation_ids[service_id]
            for index, service_id in enumerate(EXPECTED_CONSUMERS)
        },
    }
    revocation_parameters = ", ".join(
        f":revocation_{index}" for index in range(len(EXPECTED_CONSUMERS))
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM oa_token_revocations "
                f"WHERE revocation_id IN ({revocation_parameters})"
            ),
            params,
        )
        connection.execute(
            text("DELETE FROM oa_signing_keys WHERE key_id = :key_id"), params
        )
        connection.execute(
            text("DELETE FROM oa_service_creds WHERE principal_id = :principal_id"),
            params,
        )
        connection.execute(
            text(
                "DELETE FROM oa_service_principals "
                "WHERE principal_id = :principal_id"
            ),
            params,
        )


def _cleanup_residue(
    engine: Any,
    *,
    principal_id: str,
    key_id: str,
    revocation_ids: Mapping[str, str],
) -> dict[str, int]:
    params = {
        "principal_id": principal_id,
        "key_id": key_id,
        **{
            f"revocation_{index}": revocation_ids[service_id]
            for index, service_id in enumerate(EXPECTED_CONSUMERS)
        },
    }
    revocation_parameters = ", ".join(
        f":revocation_{index}" for index in range(len(EXPECTED_CONSUMERS))
    )
    queries = {
        "revocation_count": (
            "SELECT count(*) FROM oa_token_revocations "
            f"WHERE revocation_id IN ({revocation_parameters})"
        ),
        "signing_key_count": (
            "SELECT count(*) FROM oa_signing_keys WHERE key_id = :key_id"
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
        "slice": "1298",
        "requirement": "S130",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"oa_cross_service_trust_postgres=skip reason={SMOKE_ENV}"
    if evidence.get("status") != "PASS":
        return (
            "oa_cross_service_trust_postgres=fail "
            f"code={evidence.get('failure_code')}"
        )
    summary = evidence.get("summary") or {}
    workflow = evidence.get("workflow") or {}
    return (
        "oa_cross_service_trust_postgres=pass "
        f"database={workflow.get('database')} "
        f"consumers={summary.get('passed_consumer_count', 0)}/"
        f"{summary.get('consumer_count', 0)} "
        f"tokens={summary.get('issued_token_count', 0)} "
        f"revoked_denials={summary.get('revoked_denial_count', 0)} "
        f"residue={summary.get('cleanup_residue_count', 0)} next=1299"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_oa_cross_service_trust_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
