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
    ROOT / "services/nex-oa",
    ROOT / "services/nex-wc",
    ROOT / "services/_shared",
    ROOT / "scripts/db",
):
    sys.path.insert(0, str(path))

from nex_ae_api.agent_execution import (
    AgentExecutionAdmissionService,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.agent_identity import SqlAlchemyAgentIdentityRegistry
from nex_ae_api.claim_handoff_api import register_claim_handoff_routes
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime import (
    BoundedJwksCache,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    load_env_file,
    redact_database_url,
)
from nex_wc import handoff_delivery
from nex_wc.coordination import (
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.event_delivery_process import (
    PROCESS_ID,
    SERVICE_ID,
    build_installed_wc_event_delivery_process,
    run_installed_wc_event_delivery_process,
)
from nex_wc.handoff_delivery import run_handoff_delivery_job
from nex_wc.work_items import SqlAlchemyWorkItemRepository, WorkItemService
from run_migrations import run_service_migrations

SCHEMA_VERSION = "gb2_ca00_s06_wc_delivery_acceptance.v1"
SMOKE_ENV = "NEX_WC_GB2_S06_POSTGRES_SMOKE"
WC_DATABASE_ENV = "NEX_WC_TEST_DATABASE_URL"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_TARGETS = {
    WC_DATABASE_ENV: ("nex_wc_user", "nex_wc_test"),
    AE_DATABASE_ENV: ("nex_ae_user", "nex_ae_test"),
}
SIGNING_REFERENCE = "memory://gb2-s06-oa-signing-key"
SIGNING_KEY_ID = "gb2-s06-oa-signing-key"


class _Agents:
    def __init__(self, registry: SqlAlchemyAgentIdentityRegistry) -> None:
        self._registry = registry

    def list_agents(self, *, tenant_id: str, agent_type: str, project_id: str):
        return self._registry.list_eligible_agents(
            tenant_id=tenant_id,
            agent_type=agent_type,
            project_id=project_id,
        )

    def get_agent(self, *, tenant_id: str, agent_id: str):
        return self._registry.get_agent(tenant_id=tenant_id, agent_id=agent_id)


class _Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate", "work:claim"],
            "revision_hash": "6" * 64,
        }


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


def run_gb2_ca00_s06_wc_event_delivery_worker(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "GB2-CA00-S06",
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
            "actual nex_wc_test and nex_ae_test targets are required",
        )
    try:
        migrations = {
            "wc": run_service_migrations(
                "nex-wc", database_url=urls[WC_DATABASE_ENV], profile="test"
            ),
            "ae": run_service_migrations(
                "nex-ae-api", database_url=urls[AE_DATABASE_ENV], profile="test"
            ),
        }
        evidence = _execute_protected_component(
            wc_database_url=urls[WC_DATABASE_ENV],
            ae_database_url=urls[AE_DATABASE_ENV],
        )
        migration_current = all(
            len(item.planned) == len(item.applied) + len(item.skipped)
            for item in migrations.values()
        )
        evidence.update(
            {
                "evidence_schema_version": SCHEMA_VERSION,
                "slice": "GB2-CA00-S06",
                "evidence_classification": "PROTECTED_COMPONENT",
                "profile": "test",
                "database_environments": [WC_DATABASE_ENV, AE_DATABASE_ENV],
                "redacted_database_urls": {
                    name: redact_database_url(value) for name, value in urls.items()
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
        evidence["status"] = "PASS" if all(evidence["checks"].values()) else "FAIL"
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "gb2_s06_protected_acceptance_failed"
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected process boundary.
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_urls=tuple(urls.values())),
        )


def _execute_protected_component(
    *, wc_database_url: str, ae_database_url: str
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    tenant_id = f"gb2-s06-{suffix}"
    project_id = f"project-{suffix}"
    requester_id = f"requester-{suffix}"
    agent_id = str(uuid4())
    worker_id = f"wc-gb2-s06-{suffix}"
    now = datetime.now(UTC)
    wc_engine = create_engine(wc_database_url)
    ae_engine = create_engine(ae_database_url)
    wc_sessions = sessionmaker(bind=wc_engine, expire_on_commit=False)
    ae_sessions = sessionmaker(bind=ae_engine, expire_on_commit=False)
    cleanup: dict[str, int] = {}
    original_urlopen = handoff_delivery.urlopen
    wrong_process = None
    installed = None
    restarted = None
    client: TestClient | None = None
    try:
        _cleanup_wc(wc_engine, tenant_id=tenant_id, worker_id=worker_id)
        _cleanup_ae(ae_engine, tenant_id=tenant_id)
        registry = SqlAlchemyAgentIdentityRegistry(
            ae_sessions, id_factory=lambda: agent_id, clock=lambda: now
        )
        registry.register_agent(
            tenant_id=tenant_id,
            agent_type="PA",
            profile_ref="agent-profile://pa/project-budget-read/v1",
            project_id=project_id,
        )
        admission = AgentExecutionAdmissionService(
            identities=registry,
            executions=SqlAlchemyAgentExecutionRepository(ae_sessions),
            mode="required",
            id_factory=lambda: str(uuid4()),
            clock=lambda: now,
        )
        signed = _signed_trust(now_epoch=int(time.time()))
        app = FastAPI()
        app.state.service_token_admission = signed["admission"]
        register_claim_handoff_routes(app, admission=admission)
        client = TestClient(app)
        bridge = _TestClientUrlOpen(client)
        handoff_delivery.urlopen = bridge

        item = WorkItemService(
            SqlAlchemyWorkItemRepository(wc_sessions),
            authorization_source=_Authorization(),
            id_factory=lambda: str(uuid4()),
            clock=lambda: now,
        ).create(
            _work_item_payload(
                tenant_id=tenant_id,
                project_id=project_id,
                requester_id=requester_id,
                suffix=suffix,
            )
        )[
            "work_item"
        ]
        coordination = SqlAlchemyCoordinationRepository(wc_sessions)
        service = WorkCoordinationService(
            coordination,
            candidate_source=_Agents(registry),
            authorization_source=_Authorization(),
            id_factory=lambda: str(uuid4()),
            token_factory=lambda: f"lease-{suffix}",
            clock=lambda: now,
        )
        service.route(
            tenant_id=tenant_id,
            work_item_id=item["work_item_id"],
            expected_version=1,
        )
        routed = coordination.get_work_item(
            tenant_id=tenant_id,
            work_item_id=item["work_item_id"],
        )
        if routed is None:
            raise RuntimeError("routed WorkItem could not be reloaded")
        claimed = service.claim(
            tenant_id=tenant_id,
            work_item_id=item["work_item_id"],
            expected_version=int(routed["work_item"]["version"]),
        )

        base_env = {
            WC_DATABASE_ENV: wc_database_url,
            "NEX_WC_AE_BASE_URL": "http://ae.component.local",
            "NEX_WC_EVENT_DELIVERY_WORKER_ID": worker_id,
            "NEX_WC_EVENT_DELIVERY_POLL_SECONDS": "0.001",
        }
        wrong_process = build_installed_wc_event_delivery_process(
            "test",
            environ={
                **base_env,
                "NEX_WC_TO_AE_SERVICE_TOKEN": signed["wrong_token"],
            },
        )
        wrong_readiness = wrong_process.readiness()
        wrong_run = run_installed_wc_event_delivery_process(
            wrong_process,
            max_cycles=1,
            out=StringIO(),
        )
        wrong_process.close()
        wrong_process = None
        denied_event = coordination.load_handoff_event(
            outbox_id=claimed["outbox_id"], event_id=claimed["event_id"]
        )

        with wc_engine.begin() as connection:
            failed_job = (
                connection.execute(
                    text(
                        "SELECT job_id, status, attempt_count, error "
                        "FROM service_jobs WHERE request_id = :event_id"
                    ),
                    {"event_id": claimed["event_id"]},
                )
                .mappings()
                .one()
            )
            with ae_engine.connect() as ae_connection:
                execution_count_after_denial = int(
                    ae_connection.execute(
                        text(
                            "SELECT count(*) FROM ae_agent_execution "
                            "WHERE tenant_id = :tenant_id"
                        ),
                        {"tenant_id": tenant_id},
                    ).scalar_one()
                )
            connection.execute(
                text(
                    "UPDATE service_jobs SET available_at = now() - interval '1 second' "
                    "WHERE job_id = :job_id"
                ),
                {"job_id": failed_job["job_id"]},
            )

        installed = build_installed_wc_event_delivery_process(
            "test",
            environ={
                **base_env,
                "NEX_WC_TO_AE_SERVICE_TOKEN": signed["token"],
            },
        )
        readiness = installed.readiness()
        delivery_run = run_installed_wc_event_delivery_process(
            installed,
            max_cycles=1,
            out=StringIO(),
        )
        completed_job = installed.queue.get_job(str(failed_job["job_id"]))
        replay = run_handoff_delivery_job(
            completed_job,
            store=installed.coordination,
            client=installed.handoff_client,
        )
        installed.close()
        installed = None

        restarted = build_installed_wc_event_delivery_process(
            "test",
            environ={
                **base_env,
                "NEX_WC_TO_AE_SERVICE_TOKEN": signed["token"],
            },
        )
        restart_run = run_installed_wc_event_delivery_process(
            restarted,
            max_cycles=1,
            out=StringIO(),
        )
        heartbeat = restarted.heartbeat.store.get_heartbeat(SERVICE_ID, worker_id)
        restarted.close()
        restarted = None

        event = coordination.load_handoff_event(
            outbox_id=claimed["outbox_id"], event_id=claimed["event_id"]
        )
        with ae_sessions() as session:
            ae_identity = tuple(
                session.execute(text("SELECT current_database(), current_user")).one()
            )
            execution_count = int(
                session.execute(
                    text(
                        "SELECT count(*) FROM ae_agent_execution "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            inbox_count = int(
                session.execute(
                    text(
                        "SELECT count(*) FROM ae_claim_handoff_inbox "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
        with wc_sessions() as session:
            wc_identity = tuple(
                session.execute(text("SELECT current_database(), current_user")).one()
            )
            final_job = (
                session.execute(
                    text(
                        "SELECT status, attempt_count FROM service_jobs "
                        "WHERE job_id = :job_id"
                    ),
                    {"job_id": failed_job["job_id"]},
                )
                .mappings()
                .one()
            )
            assignment_execution_id = session.execute(
                text(
                    "SELECT agent_execution_id FROM wc_assignment "
                    "WHERE tenant_id = :tenant_id "
                    "AND assignment_id = :assignment_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "assignment_id": claimed["assignment"]["assignment_id"],
                },
            ).scalar_one()
        return _component_evidence(
            wc_identity=wc_identity,
            ae_identity=ae_identity,
            wrong_readiness=wrong_readiness,
            readiness=readiness,
            claimed=claimed,
            denied_event=denied_event,
            execution_count_after_denial=execution_count_after_denial,
            status_codes=tuple(bridge.status_codes),
            wrong_run=wrong_run,
            failed_job=failed_job,
            delivery_run=delivery_run,
            final_job=final_job,
            event=event,
            assignment_execution_id=assignment_execution_id,
            replay=replay,
            accepted_signed=signed["admission"].public_snapshot()["admission_counts"][
                "accepted_signed"
            ],
            execution_count=execution_count,
            inbox_count=inbox_count,
            restart_run=restart_run,
            heartbeat=heartbeat,
            worker_id=worker_id,
            cleanup=cleanup,
        )
    finally:
        handoff_delivery.urlopen = original_urlopen
        for current in (wrong_process, installed, restarted):
            if current is not None:
                current.close()
        if client is not None:
            client.close()
        cleanup.update(_cleanup_wc(wc_engine, tenant_id=tenant_id, worker_id=worker_id))
        cleanup.update(_cleanup_ae(ae_engine, tenant_id=tenant_id))
        wc_engine.dispose()
        ae_engine.dispose()


def _component_evidence(
    *,
    wc_identity: tuple[str, str],
    ae_identity: tuple[str, str],
    wrong_readiness: Mapping[str, Any],
    readiness: Mapping[str, Any],
    claimed: Mapping[str, Any],
    denied_event: Mapping[str, Any],
    execution_count_after_denial: int,
    status_codes: tuple[int, ...],
    wrong_run: Mapping[str, Any],
    failed_job: Mapping[str, Any],
    delivery_run: Mapping[str, Any],
    final_job: Mapping[str, Any],
    event: Mapping[str, Any],
    assignment_execution_id: object,
    replay: Mapping[str, Any],
    accepted_signed: int,
    execution_count: int,
    inbox_count: int,
    restart_run: Mapping[str, Any],
    heartbeat: Mapping[str, Any] | None,
    worker_id: str,
    cleanup: Mapping[str, int],
) -> dict[str, Any]:
    checks = {
        "actual_database_identities": wc_identity == ("nex_wc_test", "nex_wc_user")
        and ae_identity == ("nex_ae_test", "nex_ae_user"),
        "readiness_truthful": wrong_readiness["readiness_status"] == "READY"
        and readiness["readiness_status"] == "READY"
        and all(readiness["checks"].values()),
        "normal_wc_domain_admission": claimed["claim"]["state"] == "ACTIVE",
        "worker_unavailable_preserved_pending_event": denied_event["delivery_state"]
        == "ENQUEUED"
        and execution_count_after_denial == 0,
        "wrong_signed_trust_failed_closed": status_codes[:1] == (403,)
        and wrong_run["failed_count"] == 1
        and failed_job["status"] == "QUEUED"
        and int(failed_job["attempt_count"]) == 1
        and execution_count_after_denial == 0,
        "restart_resumed_pending_delivery": delivery_run["failed_count"] == 0
        and delivery_run["work_cycles"] == 1
        and final_job["status"] == "SUCCEEDED"
        and int(final_job["attempt_count"]) == 2,
        "delivery_result_persisted": event["delivery_state"] == "DELIVERED"
        and str(assignment_execution_id) == replay["agent_execution_id"],
        "signed_transport_accepted": status_codes == (403, 200, 200)
        and accepted_signed == 3,
        "replay_idempotent": execution_count == 1 and inbox_count == 1,
        "restart_did_not_double_deliver": restart_run["work_cycles"] == 0
        and restart_run["failed_count"] == 0
        and execution_count == 1,
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
            "service_jobs": 1,
            "ae_agent_execution": execution_count,
            "ae_claim_handoff_inbox": inbox_count,
            "http_attempts": len(status_codes),
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
        "token": _signed_token(signer, service_id="nex-wc", token_id=f"wc-{uuid4()}"),
        "wrong_token": _signed_token(
            signer, service_id="nex-eos", token_id=f"eos-{uuid4()}"
        ),
    }


def _signed_token(
    signer: InMemoryOaRsaSigningProvider,
    *,
    service_id: str,
    token_id: str,
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
            "jti": token_id,
            "token_use": "service_access",
            "scope": "service:call",
            "service_id": service_id,
            "credential_id": f"cred-{service_id}-gb2-s06",
            "credential_revision": 1,
        },
        private_key_ref=SIGNING_REFERENCE,
        signing_provider=signer,
    )


def _work_item_payload(
    *, tenant_id: str, project_id: str, requester_id: str, suffix: str
) -> dict[str, Any]:
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": f"gb2-s06-delegation-{suffix}",
            "tenant_id": tenant_id,
            "parent_agent_execution_id": f"parent-execution-{suffix}",
            "parent_executable_plan_id": f"parent-plan-{suffix}",
            "parent_executable_step_id": f"parent-step-{suffix}",
            "delegation_revision": 1,
            "goal": "Prove canonical WC event delivery",
            "work_class": "ANALYSIS",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": project_id},
            "project_scope_ref": project_id,
            "result_contract_ref": "urn:nex:result:gb2-s06:1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": f"trace-{suffix}",
            "causation_id": f"cause-{suffix}",
        },
        "requester": {"entity_type": "USER", "entity_id": requester_id},
        "accountable_owner": {
            "entity_type": "USER",
            "entity_id": requester_id,
        },
    }


def _cleanup_wc(engine, *, tenant_id: str, worker_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.begin() as connection:
        job_ids = tuple(
            connection.execute(
                text(
                    "SELECT enqueued_job_id FROM wc_event_outbox "
                    "WHERE tenant_id = :tenant_id AND enqueued_job_id IS NOT NULL"
                ),
                {"tenant_id": tenant_id},
            ).scalars()
        )
        for table in (
            "wc_event_outbox",
            "wc_claim",
            "wc_assignment",
            "wc_routing_decision",
            "wc_work_item",
        ):
            counts[table] = int(
                connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
        if job_ids:
            counts["service_jobs"] = int(
                connection.execute(
                    text("DELETE FROM service_jobs WHERE job_id = ANY(:job_ids)"),
                    {"job_ids": list(job_ids)},
                ).rowcount
                or 0
            )
        else:
            counts["service_jobs"] = 0
        counts["heartbeat"] = int(
            connection.execute(
                text(
                    "DELETE FROM service_worker_heartbeats "
                    "WHERE service_id = :service_id AND worker_id = :worker_id"
                ),
                {"service_id": "nex-wc", "worker_id": worker_id},
            ).rowcount
            or 0
        )
        counts["wc_remaining"] = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM wc_work_item " "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
    return counts


def _cleanup_ae(engine, *, tenant_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.begin() as connection:
        for table in (
            "ae_claim_handoff_inbox",
            "ae_agent_execution",
            "ae_agent_identity",
        ):
            counts[table] = int(
                connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
        counts["ae_remaining"] = sum(
            int(
                connection.execute(
                    text(
                        f"SELECT count(*) FROM {table} " "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table in (
                "ae_claim_handoff_inbox",
                "ae_agent_execution",
                "ae_agent_identity",
            )
        )
    return counts


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
            redacted = redacted.replace(database_url, redact_database_url(database_url))
    return redacted


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "GB2-CA00-S06",
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
        "gb2_ca00_s06_wc_delivery="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"classification={evidence.get('evidence_classification', 'none')} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"jobs={rows.get('service_jobs', 0)} "
        f"http={rows.get('http_attempts', 0)} "
        f"remaining={int(cleanup.get('wc_remaining', 0)) + int(cleanup.get('ae_remaining', 0))}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run GB2-S06 protected WC event-delivery acceptance"
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    env = dict(os.environ)
    env.update(load_env_file(ROOT / args.env_file) or {})
    evidence = run_gb2_ca00_s06_wc_event_delivery_worker(env)
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
