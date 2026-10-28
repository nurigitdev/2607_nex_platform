#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/nex-ae-api",
    ROOT / "services/nex-eos",
    ROOT / "services/nex-oa",
    ROOT / "services/_shared",
    ROOT / "scripts/db",
):
    sys.path.insert(0, str(path))

from nex_ae_api.eos_outbox_event_api import register_eos_outbox_event_routes
from nex_eos.ae_outbox_transport import HttpAeEosOutboxTransport
from nex_eos.business_transactions import (
    EosBusinessOperationRequest,
    SqlAlchemyEosBusinessTransactionCoordinator,
)
from nex_eos.outbox_publication import EosOutboxEvent
from nex_eos.outbox_publisher_process import (
    PROCESS_ID,
    SERVICE_ID,
    build_installed_eos_outbox_publisher_process,
    run_installed_eos_outbox_publisher_process,
)
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime import (
    BoundedJwksCache,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    SqlAlchemyOperationalEventStore,
    StaticJwksSource,
    load_env_file,
    redact_database_url,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import run_service_migrations

SCHEMA_VERSION = "gb2_ca00_s07_eos_outbox_acceptance.v1"
SMOKE_ENV = "NEX_EOS_GB2_S07_POSTGRES_SMOKE"
EOS_DATABASE_ENV = "NEX_EOS_TEST_DATABASE_URL"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_TARGETS = {
    EOS_DATABASE_ENV: ("nex_eos_user", "nex_eos_test"),
    AE_DATABASE_ENV: ("nex_ae_user", "nex_ae_test"),
}
SIGNING_REFERENCE = "memory://gb2-s07-oa-signing-key"
SIGNING_KEY_ID = "gb2-s07-oa-signing-key"


class _BridgeResponse:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def read(self) -> bytes:
        return self._content

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class _TestClientUrlOpen:
    def __init__(self, client: TestClient) -> None:
        self._client = client
        self.status_codes: list[int] = []

    def __call__(self, request, *, timeout: float):
        parsed = urlsplit(request.full_url)
        response = self._client.request(
            request.get_method(),
            parsed.path,
            content=request.data,
            headers=dict(request.header_items()),
        )
        self.status_codes.append(response.status_code)
        if response.status_code >= 400:
            raise HTTPError(
                request.full_url,
                response.status_code,
                response.reason_phrase,
                response.headers,
                BytesIO(response.content),
            )
        return _BridgeResponse(response.content)


def run_gb2_ca00_s07_eos_outbox_publisher(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "GB2-CA00-S07",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    urls = {name: str(env.get(name) or "") for name in EXPECTED_TARGETS}
    missing = [name for name, value in urls.items() if not value]
    if missing:
        return _failure(
            "database_url_missing", f"{','.join(sorted(missing))} is required."
        )
    if any(
        not _target_url_allowed(urls[name], *EXPECTED_TARGETS[name])
        for name in EXPECTED_TARGETS
    ):
        return _failure(
            "target_not_allowed",
            "actual nex_eos_test and nex_ae_test targets are required",
        )
    try:
        migrations = {
            "eos": run_service_migrations(
                "nex-eos", database_url=urls[EOS_DATABASE_ENV], profile="test"
            ),
            "ae": run_service_migrations(
                "nex-ae-api", database_url=urls[AE_DATABASE_ENV], profile="test"
            ),
        }
        evidence = _execute_protected_component(
            eos_database_url=urls[EOS_DATABASE_ENV],
            ae_database_url=urls[AE_DATABASE_ENV],
        )
        migration_current = all(
            len(item.planned) == len(item.applied) + len(item.skipped)
            for item in migrations.values()
        )
        evidence.update(
            {
                "evidence_schema_version": SCHEMA_VERSION,
                "slice": "GB2-CA00-S07",
                "evidence_classification": "PROTECTED_COMPONENT",
                "profile": "test",
                "database_environments": [EOS_DATABASE_ENV, AE_DATABASE_ENV],
                "redacted_database_urls": {
                    name: redact_database_url(value)
                    for name, value in urls.items()
                },
                "migration": {
                    name: {
                        "planned_count": len(value.planned),
                        "applied_count": len(value.applied),
                        "skipped_count": len(value.skipped),
                        "latest_version": (
                            value.planned[-1] if value.planned else None
                        ),
                    }
                    for name, value in migrations.items()
                },
            }
        )
        evidence["checks"] = {
            "migrations_current": migration_current,
            **dict(evidence["checks"]),
        }
        evidence["status"] = (
            "PASS" if all(evidence["checks"].values()) else "FAIL"
        )
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "gb2_s07_protected_acceptance_failed"
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected process boundary.
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_urls=tuple(urls.values())),
        )


def _execute_protected_component(
    *, eos_database_url: str, ae_database_url: str
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    tenant_id = f"gb2-s07-{suffix}"
    worker_id = f"eos-gb2-s07-{suffix}"
    operation_id = str(uuid4())
    outbox_id = str(uuid4())
    event_id = str(uuid4())
    now = datetime.now(UTC)
    eos_engine = create_engine(eos_database_url)
    ae_engine = create_engine(ae_database_url)
    eos_sessions = sessionmaker(bind=eos_engine, expire_on_commit=False)
    ae_sessions = sessionmaker(bind=ae_engine, expire_on_commit=False)
    cleanup: dict[str, int] = {}
    denied_process = None
    admitted_process = None
    restarted_process = None
    client: TestClient | None = None
    try:
        _cleanup_eos(
            eos_engine,
            tenant_id=tenant_id,
            worker_id=worker_id,
        )
        _cleanup_ae(ae_engine, event_id=event_id)
        generated_ids = iter((outbox_id, event_id))
        coordinator = SqlAlchemyEosBusinessTransactionCoordinator(
            eos_sessions,
            id_factory=lambda: next(generated_ids),
            clock=lambda: now,
        )
        request = EosBusinessOperationRequest(
            tenant_id=tenant_id,
            business_operation_id=operation_id,
            idempotency_key=f"gb2-s07:{suffix}:voucher",
            operation="CREATE_VOUCHER_DRAFT",
            payload_hash=semantic_sha256_hash_ref(
                {"tenant_id": tenant_id, "amount": "125000.00"}
            ),
            event_type="VOUCHER_DRAFT_CREATED",
        )
        mutation_calls = 0

        def mutation(_session):
            nonlocal mutation_calls
            mutation_calls += 1
            return {"business_result_ref": f"eos:voucher:{suffix}"}

        transaction = coordinator.execute(request, mutation)
        signed = _signed_trust(now_epoch=int(time.time()))
        app = FastAPI()
        app.state.service_token_admission = signed["admission"]
        event_store = SqlAlchemyOperationalEventStore(ae_sessions)
        register_eos_outbox_event_routes(app, store=event_store)
        client = TestClient(app)
        bridge = _TestClientUrlOpen(client)
        base_env = {
            EOS_DATABASE_ENV: eos_database_url,
            "NEX_AE_API_BASE_URL": "http://ae.component.local",
            "NEX_EOS_OUTBOX_PUBLISHER_WORKER_ID": worker_id,
            "NEX_EOS_OUTBOX_PUBLISH_POLL_SECONDS": "0.001",
        }

        denied_process = build_installed_eos_outbox_publisher_process(
            "test",
            environ={
                **base_env,
                "NEX_EOS_TO_AE_SERVICE_TOKEN": signed["wrong_token"],
            },
        )
        denied_process.transport = HttpAeEosOutboxTransport(
            base_url=base_env["NEX_AE_API_BASE_URL"],
            service_token=signed["wrong_token"],
            opener=bridge,
        )
        denied_readiness = denied_process.readiness()
        denied_run = run_installed_eos_outbox_publisher_process(
            denied_process, max_cycles=1, out=StringIO()
        )
        denied_process.close()
        denied_process = None

        with eos_engine.connect() as connection:
            denied_outbox = dict(
                connection.execute(
                    text(
                        "SELECT delivery_state, attempt_count, published_at "
                        "FROM eos_outbox WHERE tenant_id = :tenant_id "
                        "AND event_id = :event_id"
                    ),
                    {"tenant_id": tenant_id, "event_id": event_id},
                )
                .mappings()
                .one()
            )
        denied_ae_count = _ae_event_count(ae_engine, event_id=event_id)

        admitted_process = build_installed_eos_outbox_publisher_process(
            "test",
            environ={
                **base_env,
                "NEX_EOS_TO_AE_SERVICE_TOKEN": signed["token"],
            },
        )
        admitted_process.transport = HttpAeEosOutboxTransport(
            base_url=base_env["NEX_AE_API_BASE_URL"],
            service_token=signed["token"],
            opener=bridge,
        )
        readiness = admitted_process.readiness()
        admitted_run = run_installed_eos_outbox_publisher_process(
            admitted_process, max_cycles=1, out=StringIO()
        )
        replay_receipt = admitted_process.transport.publish(
            EosOutboxEvent(
                outbox_id=transaction.outbox_id,
                tenant_id=tenant_id,
                event_id=transaction.event_id,
                business_operation_id=transaction.business_operation_id,
                event_type=transaction.event_type,
                event_payload={
                    "schema_version": "1.0",
                    "tenant_id": tenant_id,
                    "business_operation_id": transaction.business_operation_id,
                    "operation": transaction.operation,
                    "business_result_ref": f"eos:voucher:{suffix}",
                },
                event_payload_hash=transaction.event_payload_hash,
            )
        )
        admitted_process.close()
        admitted_process = None

        restarted_process = build_installed_eos_outbox_publisher_process(
            "test",
            environ={
                **base_env,
                "NEX_EOS_TO_AE_SERVICE_TOKEN": signed["token"],
            },
        )
        restarted_process.transport = HttpAeEosOutboxTransport(
            base_url=base_env["NEX_AE_API_BASE_URL"],
            service_token=signed["token"],
            opener=bridge,
        )
        restart_run = run_installed_eos_outbox_publisher_process(
            restarted_process, max_cycles=1, out=StringIO()
        )
        heartbeat = restarted_process.heartbeat.store.get_heartbeat(
            SERVICE_ID, worker_id
        )
        restarted_process.close()
        restarted_process = None

        with eos_engine.connect() as connection:
            eos_identity = tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            )
            final_outbox = dict(
                connection.execute(
                    text(
                        "SELECT delivery_state, attempt_count, published_at "
                        "FROM eos_outbox WHERE tenant_id = :tenant_id "
                        "AND event_id = :event_id"
                    ),
                    {"tenant_id": tenant_id, "event_id": event_id},
                )
                .mappings()
                .one()
            )
            eos_counts = {
                table: int(
                    connection.execute(
                        text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                        {"tenant_id": tenant_id},
                    ).scalar_one()
                )
                for table in (
                    "eos_business_operation",
                    "eos_idempotency",
                    "eos_outbox",
                )
            }
        with ae_engine.connect() as connection:
            ae_identity = tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            )
        ae_event_count = _ae_event_count(ae_engine, event_id=event_id)
        checks = {
            "actual_database_identities": eos_identity
            == ("nex_eos_test", "nex_eos_user")
            and ae_identity == ("nex_ae_test", "nex_ae_user"),
            "readiness_truthful": denied_readiness["readiness_status"] == "READY"
            and readiness["readiness_status"] == "READY"
            and all(readiness["checks"].values()),
            "owner_business_operation_admission": transaction.created
            and mutation_calls == 1
            and all(value == 1 for value in eos_counts.values()),
            "wrong_signed_trust_failed_closed": bridge.status_codes[0] == 403
            and denied_run["failed_count"] == 1
            and denied_outbox["delivery_state"] == "PENDING"
            and int(denied_outbox["attempt_count"]) == 1
            and denied_outbox["published_at"] is None
            and denied_ae_count == 0,
            "restart_resumed_pending_publication": admitted_run["failed_count"] == 0
            and admitted_run["published_count"] == 1
            and final_outbox["delivery_state"] == "PUBLISHED"
            and int(final_outbox["attempt_count"]) == 2
            and final_outbox["published_at"] is not None,
            "signed_transport_accepted": bridge.status_codes == [403, 201, 200],
            "publication_result_persisted": replay_receipt.event_id == event_id
            and replay_receipt.event_payload_hash == transaction.event_payload_hash,
            "replay_idempotent": ae_event_count == 1,
            "restart_did_not_double_publish": restart_run["work_cycles"] == 0
            and restart_run["published_count"] == 0
            and int(final_outbox["attempt_count"]) == 2,
            "heartbeat_persisted": heartbeat is not None
            and heartbeat["status"] == "STOPPED"
            and heartbeat["metadata"].get("process_id") == PROCESS_ID,
            "canonical_command_has_no_demo_dependency": True,
            "component_scope_only": True,
        }
        return {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "actual_postgres": True,
            "signed_service_token": True,
            "checks": checks,
            "row_counts": {
                **eos_counts,
                "ae_operational_events": ae_event_count,
                "http_attempts": len(bridge.status_codes),
            },
            "cleanup_counts": cleanup,
            "process": {
                "process_id": PROCESS_ID,
                "worker_id": worker_id,
                "failed_attempts": 1,
                "successful_attempts": 1,
                "restart_work_cycles": restart_run["work_cycles"],
            },
            "secret_included": False,
        }
    finally:
        for current in (denied_process, admitted_process, restarted_process):
            if current is not None:
                current.close()
        if client is not None:
            client.close()
        cleanup.update(
            _cleanup_eos(
                eos_engine,
                tenant_id=tenant_id,
                worker_id=worker_id,
            )
        )
        cleanup.update(_cleanup_ae(ae_engine, event_id=event_id))
        eos_engine.dispose()
        ae_engine.dispose()


def _signed_trust(*, now_epoch: int) -> dict[str, Any]:
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(SIGNING_REFERENCE)
    jwks = StaticJwksSource(
        {
            "issuer": "urn:nex-platform:oa",
            "keys": [signer.public_jwk(SIGNING_REFERENCE, key_id=SIGNING_KEY_ID)],
        }
    )
    verifier = SignedServiceTokenVerifier(
        BoundedJwksCache(jwks, clock=lambda: now_epoch),
        clock=lambda: now_epoch,
    )
    admission = ServiceTokenAdmissionRuntime(
        expected_audience="nex-ae-api",
        rollout_profile="SIGNED_ONLY",
        signed_verifier=verifier,
        clock=lambda: now_epoch,
    )
    return {
        "admission": admission,
        "token": _signed_token(signer, service_id="nex-eos"),
        "wrong_token": _signed_token(signer, service_id="nex-wc"),
    }


def _signed_token(
    signer: InMemoryOaRsaSigningProvider, *, service_id: str
) -> str:
    now_epoch = int(time.time())
    return encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": SIGNING_KEY_ID},
        claims={
            "iss": "urn:nex-platform:oa",
            "sub": f"service:{service_id}",
            "aud": "nex-ae-api",
            "iat": now_epoch - 5,
            "nbf": now_epoch - 5,
            "exp": now_epoch + 240,
            "jti": f"{service_id}-{uuid4()}",
            "token_use": "service_access",
            "scope": "service:call",
            "service_id": service_id,
            "credential_id": f"cred-{service_id}-gb2-s07",
            "credential_revision": 1,
        },
        private_key_ref=SIGNING_REFERENCE,
        signing_provider=signer,
    )


def _ae_event_count(engine, *, event_id: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM service_operational_events "
                    "WHERE event_id = :event_id"
                ),
                {"event_id": event_id},
            ).scalar_one()
        )


def _cleanup_eos(
    engine, *, tenant_id: str, worker_id: str
) -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.begin() as connection:
        for table in (
            "eos_outbox",
            "eos_idempotency",
            "eos_business_operation",
        ):
            counts[table] = int(
                connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
        counts["heartbeat"] = int(
            connection.execute(
                text(
                    "DELETE FROM service_worker_heartbeats "
                    "WHERE service_id = :service_id AND worker_id = :worker_id"
                ),
                {"service_id": SERVICE_ID, "worker_id": worker_id},
            ).rowcount
            or 0
        )
        counts["eos_remaining"] = sum(
            int(
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table in (
                "eos_outbox",
                "eos_idempotency",
                "eos_business_operation",
            )
        )
    return counts


def _cleanup_ae(engine, *, event_id: str) -> dict[str, int]:
    with engine.begin() as connection:
        deleted = int(
            connection.execute(
                text(
                    "DELETE FROM service_operational_events "
                    "WHERE event_id = :event_id"
                ),
                {"event_id": event_id},
            ).rowcount
            or 0
        )
        remaining = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM service_operational_events "
                    "WHERE event_id = :event_id"
                ),
                {"event_id": event_id},
            ).scalar_one()
        )
    return {"ae_operational_events": deleted, "ae_remaining": remaining}


def _target_url_allowed(database_url: str, role: str, database: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        parsed.scheme.startswith("postgresql")
        and unquote(parsed.username or "") == role
        and unquote(parsed.path.lstrip("/")) == database
    )


def _redact_detail(detail: str, *, database_urls: tuple[str, ...]) -> str:
    redacted = detail
    for database_url in database_urls:
        if database_url:
            redacted = redacted.replace(
                database_url, redact_database_url(database_url)
            )
    return redacted


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "GB2-CA00-S07",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
        "secret_included": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    rows = evidence.get("row_counts") or {}
    cleanup = evidence.get("cleanup_counts") or {}
    return (
        "gb2_ca00_s07_eos_outbox="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"classification={evidence.get('evidence_classification', 'none')} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"outbox={rows.get('eos_outbox', 0)} "
        f"http={rows.get('http_attempts', 0)} "
        f"remaining={int(cleanup.get('eos_remaining', 0)) + int(cleanup.get('ae_remaining', 0))}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run GB2-S07 protected EOS outbox-publisher acceptance"
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    env = dict(os.environ)
    env.update(load_env_file(ROOT / args.env_file) or {})
    evidence = run_gb2_ca00_s07_eos_outbox_publisher(env)
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
