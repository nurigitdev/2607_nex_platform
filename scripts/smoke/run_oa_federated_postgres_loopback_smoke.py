#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import ipaddress
import json
import os
from pathlib import Path
import ssl
import sys
from tempfile import TemporaryDirectory
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import time
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
import httpx
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/_shared",
    ROOT / "services/nex-oa",
    ROOT / "scripts/db",
):
    sys.path.insert(0, str(path))

from nex_oa.federated_identities import (  # noqa: E402
    build_external_identity_link,
    build_federation_provider,
)
from nex_oa.federated_identity_repository import (  # noqa: E402
    build_federated_identity_repository_for_runtime,
)
from nex_oa.federated_login import (  # noqa: E402
    CachingOidcVerifierProvider,
    HttpOidcDocumentSource,
    OaFederatedLoginService,
    register_federated_login_routes,
)
from nex_oa.memberships import (  # noqa: E402
    build_tenant_membership_registry_for_runtime,
)
from nex_oa.sessions import build_oa_session_registry_for_runtime  # noqa: E402
from nex_oa.subjects import build_subject_registry_for_runtime  # noqa: E402
from nex_oa.token_signing import (  # noqa: E402
    InMemoryOaRsaSigningProvider,
    encode_signed_jwt,
)
from nex_runtime import (  # noqa: E402
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SMOKE_ENV = "NEX_OA_FEDERATED_POSTGRES_LOOPBACK_SMOKE"
DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
SCHEMA_VERSION = "oa_federated_postgres_loopback_smoke.v1"
SERVICE_ID = "nex-oa"
PROFILE = "test"
SLICE_ID = "1290"
REQUIRED_MIGRATION = "1284_oa_federated_identity"
EXPECTED_DATABASE = "nex_oa_test"
EXPECTED_ROLE = "nex_oa_user"
OIDC_KEY_REF = "memory://s129-loopback-key"
OIDC_KEY_ID = "s129-loopback-key"
DISCOVERY_PATH = "/.well-known/openid-configuration"
JWKS_PATH = "/jwks"


def run_oa_federated_postgres_loopback_smoke(
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
        workflow = _execute_federated_postgres_loopback_smoke(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )
        evidence = _evaluate(
            {
                "planned": migration.planned,
                "applied": migration.applied,
                "skipped": migration.skipped,
            },
            workflow,
        )
        evidence.update(
            smoke_schema_version=SCHEMA_VERSION,
            slice=SLICE_ID,
            requirement="S129",
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


def _execute_federated_postgres_loopback_smoke(
    *, database_url: str, runtime_environ: Mapping[str, str]
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    tenant_id = f"tenant-s129-{suffix}"
    subject_id = f"user-s129-{suffix}"
    provider_id = f"oidc-s129-{suffix}"
    external_subject = f"external-s129-{uuid4().hex}"
    nonce = f"nonce-{uuid4().hex}"
    signer = InMemoryOaRsaSigningProvider()
    jwk = signer.generate_key(OIDC_KEY_REF)
    engine = None
    session_id: str | None = None
    cleanup_residue: dict[str, int] = {}

    loopback = _TlsOidcLoopbackServer(jwk)
    loopback.start()
    try:
        provider = build_federation_provider(
            {
                "provider_id": provider_id,
                "issuer": loopback.issuer,
                "client_id": "nex-platform-s129-smoke",
                "discovery_url": loopback.discovery_url,
                "display_name": "S129 protected loopback OIDC",
            }
        )
        identity = build_external_identity_link(
            {
                "provider_id": provider_id,
                "external_subject": external_subject,
                "tenant_id": tenant_id,
                "subject_id": subject_id,
            },
            provider=provider,
        )
        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        persistence = attach_service_persistence_runtime(
            app,
            SERVICE_SPECS[SERVICE_ID],
            environ=dict(runtime_environ),
        )
        if persistence.api_session_factory is None or persistence.api_engine is None:
            raise RuntimeError("OA federated PostgreSQL runtime is unavailable")
        engine = persistence.api_engine
        subject_registry = build_subject_registry_for_runtime(persistence)
        membership_registry = build_tenant_membership_registry_for_runtime(
            persistence,
            subject_registry=subject_registry,
        )
        session_registry = build_oa_session_registry_for_runtime(
            persistence,
            membership_registry=membership_registry,
        )
        repository = build_federated_identity_repository_for_runtime(persistence)
        membership_registry.ensure_membership(
            {
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "tenant_display_name": "S129 Smoke Tenant",
                "subject_display_name": "S129 Smoke Operator",
                "roles": ["admin", "employee"],
                "scopes": ["workspace:use", "documents:read"],
                "membership_metadata": {"source": "s129-postgres-loopback"},
            }
        )
        repository.save_provider(provider)
        repository.save_identity(identity)
        register_federated_login_routes(
            app,
            service=OaFederatedLoginService(
                repository=repository,
                session_issuer=session_registry,
                verifier_provider=CachingOidcVerifierProvider(
                    HttpOidcDocumentSource(requester=loopback.request),
                    cache_ttl_seconds=300,
                ),
            ),
        )

        now_epoch = int(time())
        id_token = encode_signed_jwt(
            headers={"alg": "RS256", "typ": "JWT", "kid": OIDC_KEY_ID},
            claims={
                "iss": loopback.issuer,
                "sub": external_subject,
                "aud": provider["client_id"],
                "iat": now_epoch,
                "exp": now_epoch + 300,
                "nonce": nonce,
            },
            private_key_ref=OIDC_KEY_REF,
            signing_provider=signer,
        )
        payload = {
            "provider_id": provider_id,
            "id_token": id_token,
            "nonce": nonce,
            "requested_scopes": ["workspace:use"],
            "ttl_seconds": 900,
        }
        token = issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-oa",
            scopes=[DEFAULT_SERVICE_SCOPE],
        ).access_token
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": f"s129-{suffix}",
        }
        with TestClient(app) as client:
            unauthorized = client.post(
                "/internal/v1/auth/federated-login", json=payload
            )
            response = client.post(
                "/internal/v1/auth/federated-login",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        session_id = str(body["session"]["session_id"])

        restarted_repository = build_federated_identity_repository_for_runtime(
            persistence
        )
        restarted_sessions = build_oa_session_registry_for_runtime(
            persistence,
            membership_registry=membership_registry,
        )
        restart_provider = restarted_repository.get_provider(provider_id)
        restart_identity = restarted_repository.find_identity(
            provider_id=provider_id,
            external_subject_digest=identity["external_subject_digest"],
        )
        restart_session = restarted_sessions.get_session(session_id)
        observations = _database_observations(
            engine,
            provider_id=provider_id,
            tenant_id=tenant_id,
            subject_id=subject_id,
            session_id=session_id,
            external_subject=external_subject,
            external_subject_digest=identity["external_subject_digest"],
        )
        serialized_response = json.dumps(body, sort_keys=True)
        workflow_checks = {
            "runtime_postgres": persistence.mode == "postgres",
            "route_requires_service_auth": unauthorized.status_code == 401,
            "federated_login_succeeded": response.status_code == 200,
            "oidc_discovery_and_jwks_fetched": loopback.request_kinds
            == ["discovery", "jwks"],
            "oidc_transport_tls": loopback.scheme == "https",
            "oa_session_issued": body["session"]["status"] == "ACTIVE",
            "admin_context_projected": body["operator_context"]["roles"]
            == ["admin", "employee"],
            "requested_scope_narrowed": body["operator_context"]["scopes"]
            == ["workspace:use"],
            "restart_provider_readable": restart_provider is not None,
            "restart_identity_readable": restart_identity is not None,
            "restart_session_readable": restart_session is not None,
            "raw_id_token_absent": id_token not in serialized_response,
            "raw_external_subject_absent": external_subject
            not in serialized_response,
            "database_url_absent": database_url not in serialized_response,
        }
        return {
            "runtime_mode": persistence.mode,
            "database": observations.pop("database"),
            "role": observations.pop("role"),
            "checks": workflow_checks,
            "db_observations": observations,
            "loopback": {
                "transport": "trusted_local_tls",
                "request_count": len(loopback.request_kinds),
                "discovery_count": loopback.request_kinds.count("discovery"),
                "jwks_count": loopback.request_kinds.count("jwks"),
                "private_key_exported_to_evidence": False,
            },
        }
    finally:
        loopback.stop()
        if engine is not None:
            cleanup_residue = _cleanup_smoke_rows(
                engine,
                provider_id=provider_id,
                tenant_id=tenant_id,
                subject_id=subject_id,
                session_id=session_id,
            )
            engine.dispose()
        if "workflow_checks" in locals():
            workflow_checks["cleanup_residue_zero"] = bool(cleanup_residue) and all(
                value == 0 for value in cleanup_residue.values()
            )
        if "observations" in locals():
            observations["cleanup_residue"] = cleanup_residue


class _TlsOidcLoopbackServer:
    def __init__(self, public_jwk: Mapping[str, Any]) -> None:
        self._public_jwk = dict(public_jwk)
        self.request_kinds: list[str] = []
        self._temporary_directory = TemporaryDirectory(prefix="nex-s129-oidc-")
        self._cert_path = Path(self._temporary_directory.name) / "loopback-cert.pem"
        self._key_path = Path(self._temporary_directory.name) / "loopback-key.pem"
        _write_loopback_certificate(self._cert_path, self._key_path)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self._cert_path), str(self._key_path))
        self._server.socket = context.wrap_socket(
            self._server.socket,
            server_side=True,
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="oa-s129-oidc-loopback",
            daemon=True,
        )
        self._started = False

    @property
    def scheme(self) -> str:
        return "https"

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def issuer(self) -> str:
        return f"https://127.0.0.1:{self.port}"

    @property
    def discovery_url(self) -> str:
        return f"{self.issuer}{DISCOVERY_PATH}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}{JWKS_PATH}"

    def start(self) -> None:
        self._thread.start()
        self._started = True

    def stop(self) -> None:
        if self._started:
            self._server.shutdown()
            self._thread.join(timeout=5)
        self._server.server_close()
        self._temporary_directory.cleanup()

    def request(self, url: str, **kwargs: Any) -> httpx.Response:
        trust_context = ssl.create_default_context(cafile=str(self._cert_path))
        with httpx.Client(
            verify=trust_context,
            trust_env=False,
        ) as client:
            return client.get(url, **kwargs)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == DISCOVERY_PATH:
                    owner.request_kinds.append("discovery")
                    payload = {
                        "issuer": owner.issuer,
                        "jwks_uri": owner.jwks_url,
                        "id_token_signing_alg_values_supported": ["RS256"],
                    }
                elif self.path == JWKS_PATH:
                    owner.request_kinds.append("jwks")
                    payload = {"keys": [owner._public_jwk]}
                else:
                    self.send_error(404)
                    return
                body = json.dumps(payload, separators=(",", ":")).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_: Any) -> None:
                return None

        return Handler


def _write_loopback_certificate(cert_path: Path, key_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "nex-s129-oidc-loopback")]
    )
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=10))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def _database_observations(
    engine: Any,
    *,
    provider_id: str,
    tenant_id: str,
    subject_id: str,
    session_id: str,
    external_subject: str,
    external_subject_digest: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        database, role = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
        migration_ledger_count = connection.execute(
            text("SELECT count(*) FROM schema_migrations")
        ).scalar_one()
        required_migration_count = connection.execute(
            text("SELECT count(*) FROM schema_migrations WHERE version = :version"),
            {"version": REQUIRED_MIGRATION},
        ).scalar_one()
        provider_count = connection.execute(
            text("SELECT count(*) FROM oa_fed_providers WHERE provider_id = :id"),
            {"id": provider_id},
        ).scalar_one()
        identity_row = connection.execute(
            text(
                "SELECT external_subject_digest, tenant_id, subject_id "
                "FROM oa_fed_identities WHERE provider_id = :id"
            ),
            {"id": provider_id},
        ).mappings().first()
        membership_count = connection.execute(
            text(
                "SELECT count(*) FROM oa_tenant_memberships "
                "WHERE tenant_id = :tenant_id AND subject_id = :subject_id"
            ),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        ).scalar_one()
        session_count = connection.execute(
            text("SELECT count(*) FROM oa_user_sessions WHERE session_id = :id"),
            {"id": session_id},
        ).scalar_one()
        raw_subject_count = connection.execute(
            text(
                "SELECT count(*) FROM oa_fed_identities WHERE provider_id = :id "
                "AND (provider_id LIKE :raw OR external_subject_digest LIKE :raw "
                "OR tenant_id LIKE :raw OR subject_id LIKE :raw)"
            ),
            {"id": provider_id, "raw": f"%{external_subject}%"},
        ).scalar_one()
    return {
        "database": str(database),
        "role": str(role),
        "migration_ledger_count": int(migration_ledger_count),
        "required_migration_count": int(required_migration_count),
        "provider_count": int(provider_count),
        "identity_count": 1 if identity_row is not None else 0,
        "identity_digest_matches": bool(
            identity_row
            and identity_row["external_subject_digest"] == external_subject_digest
        ),
        "identity_subject_matches": bool(
            identity_row
            and identity_row["tenant_id"] == tenant_id
            and identity_row["subject_id"] == subject_id
        ),
        "membership_count": int(membership_count),
        "session_count": int(session_count),
        "raw_external_subject_match_count": int(raw_subject_count),
    }


def _cleanup_smoke_rows(
    engine: Any,
    *,
    provider_id: str,
    tenant_id: str,
    subject_id: str,
    session_id: str | None,
) -> dict[str, int]:
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM oa_user_sessions WHERE session_id = :session_id "
                "OR (tenant_id = :tenant_id AND subject_id = :subject_id)"
            ),
            {
                "session_id": session_id or "",
                "tenant_id": tenant_id,
                "subject_id": subject_id,
            },
        )
        connection.execute(
            text("DELETE FROM oa_fed_identities WHERE provider_id = :provider_id"),
            {"provider_id": provider_id},
        )
        connection.execute(
            text("DELETE FROM oa_fed_providers WHERE provider_id = :provider_id"),
            {"provider_id": provider_id},
        )
        connection.execute(
            text(
                "DELETE FROM oa_tenant_memberships "
                "WHERE tenant_id = :tenant_id AND subject_id = :subject_id"
            ),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        )
        connection.execute(
            text(
                "DELETE FROM oa_subjects "
                "WHERE tenant_id = :tenant_id AND subject_id = :subject_id"
            ),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        )
        connection.execute(
            text("DELETE FROM oa_tenants WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        residue = {
            "provider_count": connection.execute(
                text("SELECT count(*) FROM oa_fed_providers WHERE provider_id = :id"),
                {"id": provider_id},
            ).scalar_one(),
            "identity_count": connection.execute(
                text("SELECT count(*) FROM oa_fed_identities WHERE provider_id = :id"),
                {"id": provider_id},
            ).scalar_one(),
            "membership_count": connection.execute(
                text(
                    "SELECT count(*) FROM oa_tenant_memberships "
                    "WHERE tenant_id = :tenant_id AND subject_id = :subject_id"
                ),
                {"tenant_id": tenant_id, "subject_id": subject_id},
            ).scalar_one(),
            "session_count": connection.execute(
                text(
                    "SELECT count(*) FROM oa_user_sessions "
                    "WHERE tenant_id = :tenant_id AND subject_id = :subject_id"
                ),
                {"tenant_id": tenant_id, "subject_id": subject_id},
            ).scalar_one(),
            "subject_count": connection.execute(
                text(
                    "SELECT count(*) FROM oa_subjects "
                    "WHERE tenant_id = :tenant_id AND subject_id = :subject_id"
                ),
                {"tenant_id": tenant_id, "subject_id": subject_id},
            ).scalar_one(),
            "tenant_count": connection.execute(
                text("SELECT count(*) FROM oa_tenants WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            ).scalar_one(),
        }
    return {name: int(value) for name, value in residue.items()}


def _evaluate(
    migration: Mapping[str, Any], workflow: Mapping[str, Any]
) -> dict[str, Any]:
    planned = tuple(str(item) for item in migration.get("planned") or ())
    current = {
        str(item)
        for key in ("applied", "skipped")
        for item in migration.get(key) or ()
    }
    workflow_checks = {
        str(name): value is True
        for name, value in dict(workflow.get("checks") or {}).items()
    }
    observations = dict(workflow.get("db_observations") or {})
    cleanup = dict(observations.get("cleanup_residue") or {})
    checks = {
        "migration_planned": REQUIRED_MIGRATION in planned,
        "migration_applied_or_current": REQUIRED_MIGRATION in current,
        "migration_inventory_current": observations.get("migration_ledger_count")
        == len(planned),
        "actual_test_database": workflow.get("database") == EXPECTED_DATABASE,
        "expected_test_role": workflow.get("role") == EXPECTED_ROLE,
        "workflow_checks_complete": bool(workflow_checks)
        and all(workflow_checks.values()),
        "federation_rows_persisted": (
            observations.get("provider_count") == 1
            and observations.get("identity_count") == 1
            and observations.get("membership_count") == 1
            and observations.get("session_count") == 1
        ),
        "digest_only_identity": observations.get("identity_digest_matches") is True
        and observations.get("raw_external_subject_match_count") == 0,
        "protected_tls_loopback_complete": (
            (workflow.get("loopback") or {}).get("transport")
            == "trusted_local_tls"
            and (workflow.get("loopback") or {}).get("discovery_count") == 1
            and (workflow.get("loopback") or {}).get("jwks_count") == 1
        ),
        "cleanup_residue_zero": bool(cleanup)
        and all(int(value) == 0 for value in cleanup.values()),
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    return {
        "status": "PASS" if not failed else "FAIL",
        "failure_code": None if not failed else "oa_federated_postgres_loopback_failed",
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "migration_count": len(planned),
            "loopback_request_count": int(
                (workflow.get("loopback") or {}).get("request_count") or 0
            ),
            "persisted_row_count": sum(
                int(observations.get(name) or 0)
                for name in (
                    "provider_count",
                    "identity_count",
                    "membership_count",
                    "session_count",
                )
            ),
            "cleanup_residue_count": sum(int(value) for value in cleanup.values()),
        },
        "workflow": dict(workflow),
    }


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": SLICE_ID,
        "requirement": "S129",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"oa_federated_postgres_loopback=skipped reason={SMOKE_ENV}"
    summary = evidence.get("summary") or {}
    return (
        "oa_federated_postgres_loopback="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"migrations={summary.get('migration_count', 0)} "
        f"tls_requests={summary.get('loopback_request_count', 0)} "
        f"rows={summary.get('persisted_row_count', 0)} "
        f"residue={summary.get('cleanup_residue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_oa_federated_postgres_loopback_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 1 if evidence.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
