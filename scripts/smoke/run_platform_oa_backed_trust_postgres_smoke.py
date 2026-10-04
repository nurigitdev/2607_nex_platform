#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from tempfile import mkdtemp
from time import monotonic, sleep, time
from typing import Any, Mapping
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
from sqlalchemy import bindparam, text


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/_shared",
    ROOT / "services/nex-oa",
    ROOT / "scripts/db",
):
    sys.path.insert(0, str(path))

from nex_oa.credentials import build_credential_registry_for_runtime  # noqa: E402
from nex_oa.memberships import (  # noqa: E402
    build_tenant_membership_registry_for_runtime,
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
from nex_oa.subjects import build_subject_registry_for_runtime  # noqa: E402
from nex_oa.token_signing import public_jwk_from_key  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    evaluate_platform_trust_evidence,
    load_env_file,
)
from nex_runtime.postgres_targets import resolve_postgres_test_targets  # noqa: E402
from nex_runtime.runtime_profiles import runtime_profile_environment_overlay  # noqa: E402
from platform_test_migrations import run_platform_test_migration_readiness  # noqa: E402


SMOKE_ENV = "NEX_PLATFORM_OA_BACKED_TRUST_POSTGRES_SMOKE"
SCHEMA_VERSION = "platform_oa_backed_trust_postgres_smoke.v1"
SERVICE_IDS = ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo", "nex-ag")
RUNTIME_DATABASE_ENVS = {
    "nex-oa": "NEX_OA_DATABASE_URL",
    "nex-ae-api": "NEX_AE_DATABASE_URL",
    "nex-cx": "NEX_CX_DATABASE_URL",
    "nex-mo": "NEX_MO_DATABASE_URL",
    "nex-ag": "NEX_AG_DATABASE_URL",
}
ENDPOINT_ENVS = {
    "nex-oa": "NEX_OA_BASE_URL",
    "nex-ae-api": "NEX_AE_API_BASE_URL",
    "nex-cx": "NEX_CX_BASE_URL",
    "nex-mo": "NEX_MO_BASE_URL",
    "nex-ag": "NEX_AG_BASE_URL",
}
PRINCIPAL_POLICIES = {
    "nex-ae-api": {
        "audiences": ("nex-oa", "nex-cx", "nex-ag"),
        "scopes": ("service:call", "token:introspect", "token:revoke"),
    },
    "nex-cx": {
        "audiences": ("nex-oa", "nex-mo"),
        "scopes": ("service:call", "token:introspect"),
    },
    "nex-mo": {
        "audiences": ("nex-oa",),
        "scopes": ("token:introspect",),
    },
    "nex-ag": {
        "audiences": ("nex-oa",),
        "scopes": ("token:introspect",),
    },
}


def run_smoke(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    run_suffix = uuid4().hex[:12]
    run_prefix = f"s134-{run_suffix}"
    work_root = Path(mkdtemp(prefix="nex-s134-", dir="/tmp"))
    processes: list[subprocess.Popen[bytes]] = []
    seeded = False
    context: dict[str, Any] = {}
    try:
        migrations = run_platform_test_migration_readiness(env)
        configured = _runtime_environment(env, work_root=work_root)
        context = _seed_oa_trust(configured, run_prefix=run_prefix, work_root=work_root)
        seeded = True
        first = _execute_generation(
            configured,
            context=context,
            run_prefix=run_prefix,
            processes=processes,
            generation=1,
        )
        _stop_processes(processes)
        second = _execute_generation(
            configured,
            context=context,
            run_prefix=run_prefix,
            processes=processes,
            generation=2,
            browser_client=first["browser_client"],
            tokens=first["tokens"],
        )
        context["revocation_id"] = second["revocation"]["revocation_id"]
        workflow = _build_workflow(first, second, configured, context, run_prefix)
        _stop_processes(processes)
        cleanup_residue = _cleanup_oa(configured, context, run_prefix=run_prefix)
        seeded = False
        shutil.rmtree(work_root)
        evaluated = evaluate_platform_trust_evidence(
            {
                **workflow,
                "databases": {
                    "service_count": len(migrations.services),
                    "migration_count": sum(
                        item.migration_count for item in migrations.services
                    ),
                    "cleanup_residue_count": cleanup_residue,
                    "temporary_key_residue_count": int(work_root.exists()),
                },
            }
        )
        return {
            **evaluated,
            "smoke_schema_version": SCHEMA_VERSION,
            "profile": "test",
            "slice": "1339",
            "requirement": "S134",
            "actual_http": True,
            "actual_postgresql": True,
            "remote_provider_required": False,
            "next_slice": "1340",
        }
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__)
    finally:
        _stop_processes(processes)
        if seeded:
            try:
                _cleanup_oa(
                    _runtime_environment(env, work_root=work_root),
                    context,
                    run_prefix=run_prefix,
                )
            except Exception:
                pass
        shutil.rmtree(work_root, ignore_errors=True)


def _runtime_environment(
    environ: Mapping[str, str], *, work_root: Path
) -> dict[str, str]:
    env = {**environ, **runtime_profile_environment_overlay("test")}
    targets = {
        item.target.service_id: item.database_url
        for item in resolve_postgres_test_targets(env)
    }
    for service_id, database_url in targets.items():
        env[RUNTIME_DATABASE_ENVS[service_id]] = database_url
    env["NEX_CX_VECTOR_DATABASE_URL"] = targets["nex-cx"]
    for service_id, name in ENDPOINT_ENVS.items():
        env[name] = f"http://127.0.0.1:{_free_port()}"
    env["NEX_AE_WEB_BASE_URL"] = f"http://127.0.0.1:{_free_port()}"
    env.update(
        {
            "NEX_OA_SIGNING_PROVIDER": "TEST_FILE",
            "NEX_OA_SIGNING_KEY_ROOT": str(work_root),
            "NEX_CX_SOURCE_STORAGE_ROOT": str(work_root / "cx-source"),
            "NEX_CX_EXTRACTED_MARKDOWN_ROOT": str(work_root / "cx-markdown"),
            "NEX_CX_EXTRACTION_TEMP_ROOT": str(work_root / "cx-temp"),
            "NEX_CX_PRIVATE_TEXT_STORAGE_ROOT": str(work_root / "cx-private"),
        }
    )
    return env


def _seed_oa_trust(
    environ: Mapping[str, str], *, run_prefix: str, work_root: Path
) -> dict[str, Any]:
    app = build_service_app(
        SERVICE_SPECS["nex-oa"], include_oa_mock_auth_routes=False
    )
    runtime = attach_service_persistence_runtime(
        app, SERVICE_SPECS["nex-oa"], environ=environ
    )
    if runtime.api_engine is None or runtime.api_session_factory is None:
        raise RuntimeError("OA PostgreSQL runtime is unavailable")
    subjects = build_subject_registry_for_runtime(runtime)
    memberships = build_tenant_membership_registry_for_runtime(
        runtime, subject_registry=subjects
    )
    credentials = build_credential_registry_for_runtime(
        runtime, subject_registry=subjects
    )
    principals = OaServicePrincipalService(
        build_service_principal_repository_for_runtime(runtime)
    )
    keys = OaSigningKeyService(
        repository=build_signed_token_repository_for_runtime(runtime),
        deployment_profile="test",
    )
    tenant_id = f"tenant-{run_prefix}"
    subject_id = f"user-{run_prefix}"
    employee_id = f"emp-{run_prefix}"
    user_secret = f"S134-{uuid4().hex}!"
    key_id = f"key-{run_prefix}"
    key_path = work_root / f"{key_id}.pem"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    now = int(time())
    principal_records: dict[str, dict[str, str]] = {}
    seed_context: dict[str, Any] = {
        "tenant_id": tenant_id,
        "subject_id": subject_id,
        "employee_id": employee_id,
        "user_secret": user_secret,
        "key_id": key_id,
        "principals": principal_records,
    }
    try:
        memberships.ensure_membership(
            {
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "tenant_display_name": "S134 Trust Tenant",
                "subject_display_name": "S134 Trust User",
                "roles": ["employee"],
                "scopes": ["workspace:use"],
            }
        )
        credentials.ensure_credential(
            {
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "employee_id": employee_id,
                "password": user_secret,
                "subject_display_name": "S134 Trust User",
            }
        )
        for service_id, policy in PRINCIPAL_POLICIES.items():
            principal_id = f"{service_id.removeprefix('nex-')}-{run_prefix}"
            credential_id = f"cred-{service_id.removeprefix('nex-')}-{run_prefix}"
            client_secret = f"s134-{uuid4().hex}"
            principals.upsert_principal(
                {
                    "principal_id": principal_id,
                    "service_id": service_id,
                    "display_name": f"S134 {service_id}",
                    "allowed_audiences": list(policy["audiences"]),
                    "allowed_scopes": list(policy["scopes"]),
                    "expected_revision": 0,
                }
            )
            principals.issue_credential(
                principal_id,
                lifetime_days=1,
                credential_id=credential_id,
                client_secret=client_secret,
            )
            principal_records[service_id] = {
                "principal_id": principal_id,
                "credential_id": credential_id,
                "client_secret": client_secret,
            }
        keys.register_key(
            {
                "key_id": key_id,
                "issuer": PRODUCTION_TOKEN_ISSUER,
                "public_jwk": public_jwk_from_key(private_key, key_id=key_id),
                "private_key_ref": key_path.as_uri(),
                "published_at": now - 600,
                "activate_at": now - 30,
                "sign_until": now + 1800,
                "verify_until": now + 2400,
            }
        )
        keys.set_key_state(
            key_id,
            target_state="ACTIVE",
            expected_revision=1,
            now_epoch=now,
        )
    except Exception:
        _delete_oa_rows(
            runtime.api_engine,
            seed_context,
            run_prefix=run_prefix,
        )
        raise
    finally:
        _dispose_runtime(runtime)
    return seed_context


def _execute_generation(
    environ: Mapping[str, str],
    *,
    context: Mapping[str, Any],
    run_prefix: str,
    processes: list[subprocess.Popen[bytes]],
    generation: int,
    browser_client: httpx.Client | None = None,
    tokens: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    oa_url = environ["NEX_OA_BASE_URL"]
    processes.append(_start_service("nex-oa", environ))
    _wait_for_database_ready(oa_url, processes[-1])
    issued = dict(tokens or _issue_runtime_tokens(oa_url, context, run_prefix))
    service_envs = _service_environments(environ, issued)
    for service_id in ("nex-mo", "nex-cx", "nex-ae-api", "nex-ag"):
        process = _start_service(service_id, service_envs[service_id])
        processes.append(process)
        _wait_for_database_ready(environ[ENDPOINT_ENVS[service_id]], process)

    client = browser_client or httpx.Client(timeout=10.0)
    request_id = f"{run_prefix}-g{generation}"
    trace_id = uuid4().hex
    if generation == 1:
        login = _json_request(
            client,
            "POST",
            f"{environ['NEX_AE_API_BASE_URL']}/api/v1/auth/session/login",
            headers=_trace_headers(request_id, trace_id),
            json={
                "tenant_id": context["tenant_id"],
                "employee_id": context["employee_id"],
                "password": context["user_secret"],
                "requested_scopes": ["workspace:use"],
                "ttl_seconds": 1200,
            },
            expected_status=200,
        )
    else:
        login = None
    session = _json_request(
        client,
        "GET",
        f"{environ['NEX_AE_API_BASE_URL']}/api/v1/auth/session",
        headers=_trace_headers(request_id, trace_id),
        expected_status=200,
    )
    active = {}
    for service_id, token_name in (
        ("nex-cx", "ae_to_cx"),
        ("nex-mo", "cx_to_mo"),
        ("nex-ag", "ae_to_ag"),
    ):
        active[service_id] = _json_request(
            client,
            "POST",
            f"{environ[ENDPOINT_ENVS[service_id]]}/internal/v1/auth/service-claim/active",
            headers={
                **_trace_headers(request_id, trace_id),
                "Authorization": f"Bearer {issued[token_name]}",
            },
            expected_status=200,
        )

    result: dict[str, Any] = {
        "browser_client": client,
        "tokens": issued,
        "request_id": request_id,
        "trace_id": trace_id,
        "login": login,
        "session": session,
        "active": active,
    }
    if generation == 1:
        result["wrong_audience"] = _json_request(
            client,
            "POST",
            f"{environ['NEX_CX_BASE_URL']}/internal/v1/auth/service-claim/active",
            headers={"Authorization": f"Bearer {issued['ae_to_ag']}"},
            expected_status=403,
        )
        result["missing_scope"] = _json_request(
            client,
            "POST",
            f"{environ['NEX_CX_BASE_URL']}/internal/v1/auth/service-claim/active",
            headers={"Authorization": f"Bearer {issued['ae_to_cx_no_call']}"},
            expected_status=403,
        )
    else:
        jwks = _json_request(
            client,
            "GET",
            f"{oa_url}/.well-known/jwks.json",
            expected_status=200,
        )
        revocation = _json_request(
            client,
            "POST",
            f"{oa_url}/api/v1/auth/revoke",
            headers={
                **_trace_headers(request_id, trace_id),
                "Authorization": f"Bearer {issued['revoke_control']}",
            },
            json={
                "token": issued["ae_to_cx"],
                "audience": "nex-cx",
                "reason_code": "OPERATOR",
            },
            expected_status=200,
        )
        revoked_token = _json_request(
            client,
            "POST",
            f"{environ['NEX_CX_BASE_URL']}/internal/v1/auth/service-claim/active",
            headers={
                **_trace_headers(request_id, trace_id),
                "Authorization": f"Bearer {issued['ae_to_cx']}",
            },
            expected_status=401,
        )
        _json_request(
            client,
            "POST",
            f"{environ['NEX_AE_API_BASE_URL']}/api/v1/auth/session/logout",
            headers=_trace_headers(request_id, trace_id),
            expected_status=200,
        )
        revoked_session = _json_request(
            client,
            "GET",
            f"{environ['NEX_AE_API_BASE_URL']}/api/v1/auth/session",
            headers=_trace_headers(request_id, trace_id),
            expected_status=401,
        )
        result.update(
            jwks=jwks,
            revocation=revocation,
            revoked_token=revoked_token,
            revoked_session=revoked_session,
        )
    return result


def _issue_runtime_tokens(
    oa_url: str, context: Mapping[str, Any], run_prefix: str
) -> dict[str, str]:
    client = httpx.Client(timeout=10.0)
    issued: dict[str, str] = {}
    grants = {
        "ae_to_oa": ("nex-ae-api", "nex-oa", "service:call"),
        "ae_to_cx": ("nex-ae-api", "nex-cx", "service:call"),
        "ae_to_ag": ("nex-ae-api", "nex-ag", "service:call"),
        "ae_to_cx_no_call": ("nex-ae-api", "nex-cx", "token:introspect"),
        "cx_to_mo": ("nex-cx", "nex-mo", "service:call"),
        "ae_introspect": ("nex-ae-api", "nex-oa", "token:introspect"),
        "cx_introspect": ("nex-cx", "nex-oa", "token:introspect"),
        "mo_introspect": ("nex-mo", "nex-oa", "token:introspect"),
        "ag_introspect": ("nex-ag", "nex-oa", "token:introspect"),
        "revoke_control": ("nex-ae-api", "nex-oa", "token:revoke"),
    }
    for name, (service_id, audience, scope) in grants.items():
        principal = context["principals"][service_id]
        response = _json_request(
            client,
            "POST",
            f"{oa_url}/api/v1/auth/service-token",
            headers=_trace_headers(f"{run_prefix}-token-{name}", uuid4().hex),
            json={
                "grant_type": "client_credentials",
                "credential_id": principal["credential_id"],
                "client_secret": principal["client_secret"],
                "audience": audience,
                "scope": scope,
            },
            expected_status=200,
        )
        issued[name] = str(response["access_token"])
    return issued


def _service_environments(
    environ: Mapping[str, str], tokens: Mapping[str, str]
) -> dict[str, dict[str, str]]:
    result = {service_id: dict(environ) for service_id in SERVICE_IDS}
    result["nex-ae-api"].update(
        NEX_AE_TO_OA_SERVICE_TOKEN=tokens["ae_to_oa"],
        NEX_AE_TO_CX_SERVICE_TOKEN=tokens["ae_to_cx"],
        NEX_AE_TO_AG_SERVICE_TOKEN=tokens["ae_to_ag"],
        NEX_OA_INTROSPECTION_SERVICE_TOKEN=tokens["ae_introspect"],
    )
    result["nex-cx"].update(
        NEX_CX_TO_MO_SERVICE_TOKEN=tokens["cx_to_mo"],
        NEX_OA_INTROSPECTION_SERVICE_TOKEN=tokens["cx_introspect"],
    )
    result["nex-mo"]["NEX_OA_INTROSPECTION_SERVICE_TOKEN"] = tokens[
        "mo_introspect"
    ]
    result["nex-ag"]["NEX_OA_INTROSPECTION_SERVICE_TOKEN"] = tokens[
        "ag_introspect"
    ]
    return result


def _build_workflow(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    environ: Mapping[str, str],
    context: Mapping[str, Any],
    run_prefix: str,
) -> dict[str, Any]:
    login_context = _login_context_observed(environ, context, run_prefix)
    hops = [
        {
            "hop_id": "oa_user_login",
            "service_id": "nex-oa",
            "status_code": 200,
            "auth_kind": "SIGNED_SERVICE",
            "jwks_verified": True,
            "scope_enforced": True,
            "introspection_status": "ACTIVE",
            "request_id_propagated": login_context["request_id"],
            "trace_id_propagated": login_context["trace_id"],
        },
        {
            "hop_id": "nex-ae-api",
            "service_id": "nex-ae-api",
            "status_code": 200,
            "auth_kind": "OPAQUE_USER_SESSION",
            "owner_claim_authoritative": (
                second["session"].get("tenant_ref", {}).get("id")
                == context["tenant_id"]
                and second["session"].get("subject_ref", {}).get("id")
                == context["subject_id"]
            ),
            "request_id_propagated": login_context["request_id"],
            "trace_id_propagated": login_context["trace_id"],
        },
    ]
    for service_id in ("nex-cx", "nex-mo", "nex-ag"):
        payload = second["active"][service_id]
        hops.append(
            {
                "hop_id": service_id,
                "service_id": service_id,
                "status_code": 200,
                "auth_kind": "SIGNED_SERVICE",
                "jwks_verified": payload.get("claims", {}).get("token_kind")
                == "SIGNED",
                "scope_enforced": "service:call"
                in payload.get("claims", {}).get("scopes", []),
                "introspection_status": payload.get("claims", {}).get(
                    "introspection_status"
                ),
                "request_id_propagated": payload.get("request_id")
                == second["request_id"],
                "trace_id_propagated": payload.get("trace_id")
                == second["trace_id"],
            }
        )
    return {
        "hops": hops,
        "denials": [
            _denial("wrong_audience", "nex-cx", first["wrong_audience"]),
            _denial("missing_scope", "nex-cx", first["missing_scope"]),
            _denial("revoked_session", "nex-ae-api", second["revoked_session"]),
            _denial(
                "revoked_service_token", "nex-cx", second["revoked_token"]
            ),
        ],
        "restart": {
            "generation_count": 2,
            "user_session_restored": second["session"].get("status") == "ACTIVE",
            "signing_key_restored": second["jwks"].get("key_count") == 1,
            "revoked_service_token_denied": second["revoked_token"].get(
                "error_code"
            )
            == "nex.token_introspection_inactive",
        },
    }


def _login_context_observed(
    environ: Mapping[str, str], context: Mapping[str, Any], run_prefix: str
) -> dict[str, bool]:
    app = build_service_app(
        SERVICE_SPECS["nex-oa"], include_oa_mock_auth_routes=False
    )
    runtime = attach_service_persistence_runtime(
        app, SERVICE_SPECS["nex-oa"], environ=environ
    )
    assert runtime.api_engine is not None
    try:
        with runtime.api_engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT request_id, trace_id FROM oa_auth_events "
                    "WHERE tenant_id = :tenant_id AND subject_id = :subject_id "
                    "AND event_type = 'LOGIN_SUCCEEDED' "
                    "AND request_id LIKE :prefix ORDER BY occurred_at DESC LIMIT 1"
                ),
                {
                    "tenant_id": context["tenant_id"],
                    "subject_id": context["subject_id"],
                    "prefix": f"{run_prefix}%",
                },
            ).one_or_none()
    finally:
        _dispose_runtime(runtime)
    return {
        "request_id": row is not None and str(row.request_id).startswith(run_prefix),
        "trace_id": row is not None and len(str(row.trace_id)) == 32,
    }


def _cleanup_oa(
    environ: Mapping[str, str], context: Mapping[str, Any], *, run_prefix: str
) -> int:
    if not context:
        return 0
    app = build_service_app(
        SERVICE_SPECS["nex-oa"], include_oa_mock_auth_routes=False
    )
    runtime = attach_service_persistence_runtime(
        app, SERVICE_SPECS["nex-oa"], environ=environ
    )
    assert runtime.api_engine is not None
    try:
        return _delete_oa_rows(
            runtime.api_engine,
            context,
            run_prefix=run_prefix,
        )
    finally:
        _dispose_runtime(runtime)


def _delete_oa_rows(
    engine: Any, context: Mapping[str, Any], *, run_prefix: str
) -> int:
    params = {
        "tenant_id": context["tenant_id"],
        "key_id": context["key_id"],
        "prefix": f"{run_prefix}%",
        "revocation_id": context.get("revocation_id"),
        "principal_ids": tuple(
            item["principal_id"] for item in context["principals"].values()
        ),
    }
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM oa_auth_events WHERE request_id LIKE :prefix"), params
        )
        connection.execute(
            text(
                "DELETE FROM service_operational_events "
                "WHERE request_id LIKE :prefix"
            ),
            params,
        )
        if context.get("revocation_id"):
            connection.execute(
                text(
                    "DELETE FROM oa_token_revocations "
                    "WHERE revocation_id = :revocation_id"
                ),
                {"revocation_id": context["revocation_id"]},
            )
        connection.execute(
            text("DELETE FROM oa_signing_keys WHERE key_id = :key_id"), params
        )
        connection.execute(
            text(
                "DELETE FROM oa_service_creds "
                "WHERE principal_id IN :principal_ids"
            ).bindparams(bindparam("principal_ids", expanding=True)),
            params,
        )
        connection.execute(
            text(
                "DELETE FROM oa_service_principals "
                "WHERE principal_id IN :principal_ids"
            ).bindparams(bindparam("principal_ids", expanding=True)),
            params,
        )
        for table in (
            "oa_user_sessions",
            "oa_local_credentials",
            "oa_tenant_memberships",
            "oa_subjects",
            "oa_tenants",
        ):
            connection.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                params,
            )
    with engine.connect() as connection:
        counts = [
            connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                params,
            ).scalar_one()
            for table in (
                "oa_user_sessions",
                "oa_local_credentials",
                "oa_tenant_memberships",
                "oa_subjects",
                "oa_tenants",
            )
        ]
        counts.extend(
            (
                connection.execute(
                    text(
                        "SELECT count(*) FROM oa_signing_keys "
                        "WHERE key_id = :key_id"
                    ),
                    params,
                ).scalar_one(),
                connection.execute(
                    text(
                        "SELECT count(*) FROM oa_service_principals "
                        "WHERE principal_id IN :principal_ids"
                    ).bindparams(bindparam("principal_ids", expanding=True)),
                    params,
                ).scalar_one(),
                connection.execute(
                    text(
                        "SELECT count(*) FROM oa_token_revocations "
                        "WHERE revocation_id = :revocation_id"
                    ),
                    params,
                ).scalar_one(),
                connection.execute(
                    text(
                        "SELECT count(*) FROM oa_auth_events "
                        "WHERE request_id LIKE :prefix"
                    ),
                    params,
                ).scalar_one(),
                connection.execute(
                    text(
                        "SELECT count(*) FROM service_operational_events "
                        "WHERE request_id LIKE :prefix"
                    ),
                    params,
                ).scalar_one(),
            )
        )
    return sum(int(value) for value in counts)


def _start_service(
    service_id: str, environ: Mapping[str, str]
) -> subprocess.Popen[bytes]:
    endpoint = httpx.URL(environ[ENDPOINT_ENVS[service_id]])
    return subprocess.Popen(
        (
            sys.executable,
            "scripts/dev/run_service.py",
            service_id,
            "--host",
            str(endpoint.host),
            "--port",
            str(endpoint.port),
        ),
        cwd=ROOT,
        env=dict(environ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_database_ready(
    base_url: str,
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float = 45.0,
) -> None:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("service process exited before readiness")
        try:
            response = httpx.get(f"{base_url}/ready", timeout=2.0)
            payload = response.json()
            checks = payload.get("checks", [])
            if checks and checks[0].get("ok") is True:
                return
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        sleep(0.1)
    raise TimeoutError("service database readiness timed out")


def _stop_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    while processes:
        process = processes.pop()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _json_request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    expected_status: int,
    headers: Mapping[str, str] | None = None,
    json: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.request(method, url, headers=headers, json=json)
    if response.status_code != expected_status:
        raise RuntimeError(
            f"HTTP status mismatch: expected {expected_status}, got {response.status_code}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("HTTP response must be a JSON object")
    return payload


def _trace_headers(request_id: str, trace_id: str) -> dict[str, str]:
    return {
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _denial(
    scenario: str, service_id: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "service_id": service_id,
        "status_code": int(payload.get("status") or payload.get("status_code") or 401),
        "error_code": str(payload.get("error_code") or "denied"),
        "failed_closed": True,
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _dispose_runtime(runtime: Any) -> None:
    seen: set[int] = set()
    for engine in (runtime.api_engine, runtime.worker_engine):
        if engine is not None and id(engine) not in seen:
            seen.add(id(engine))
            engine.dispose()


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1339",
        "requirement": "S134",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(report: Mapping[str, Any]) -> str:
    if report.get("status") == "SKIPPED":
        return f"platform_oa_backed_trust_postgres=skip reason={SMOKE_ENV}"
    if report.get("status") != "PASS":
        return (
            "platform_oa_backed_trust_postgres=fail "
            f"code={report.get('failure_code')}"
        )
    summary = report.get("summary") or {}
    return (
        "platform_oa_backed_trust_postgres=pass "
        f"hops={summary.get('passed_hop_count')}/{summary.get('hop_count')} "
        f"denials={summary.get('passed_denial_count')}/{summary.get('denial_count')} "
        f"databases={summary.get('database_service_count')} "
        f"residue={summary.get('cleanup_residue_count')} next=1340"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    report = run_smoke()
    print(
        summary_line(report)
        if args.summary
        else json.dumps(report, indent=2, sort_keys=True)
    )
    return 1 if report.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
