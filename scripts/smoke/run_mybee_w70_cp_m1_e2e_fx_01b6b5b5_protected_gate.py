#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from io import BytesIO, StringIO
from pathlib import Path
from threading import Lock
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

from nex_ae_api.agent_execution import (  # noqa: E402
    AgentExecutionAdmissionService,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.agent_identity import SqlAlchemyAgentIdentityRegistry  # noqa: E402
from nex_ae_api.agent_registry_api import register_agent_registry_routes  # noqa: E402
from nex_ae_api.claim_handoff_api import register_claim_handoff_routes  # noqa: E402
from nex_oa.authorization_repository import (  # noqa: E402
    build_authorization_repository_for_runtime,
)
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver  # noqa: E402
from nex_oa.authorization_service import (  # noqa: E402
    OA_AUTHORIZATION_READ_SCOPE,
    OaAuthorizationService,
    register_authorization_routes,
)
from nex_oa.identity_access import OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE  # noqa: E402
from nex_oa.memberships import (  # noqa: E402
    build_tenant_membership_registry_for_runtime,
    register_identity_membership_routes,
)
from nex_oa.subjects import build_subject_registry_for_runtime  # noqa: E402
from nex_oa.token_signing import (  # noqa: E402
    InMemoryOaRsaSigningProvider,
    encode_signed_jwt,
)
from nex_runtime import (  # noqa: E402
    BoundedJwksCache,
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    attach_service_persistence_runtime,
    build_service_app,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from nex_wc import coordination_clients, handoff_delivery  # noqa: E402
from nex_wc.assignment_dispatch import (  # noqa: E402
    enqueue_claimable_assignment_jobs,
)
from nex_wc.assignment_dispatch_process import (  # noqa: E402
    PROCESS_ID as DISPATCH_PROCESS_ID,
    build_installed_wc_assignment_dispatch_process,
    run_installed_wc_assignment_dispatch_process,
)
from nex_wc.coordination_clients import HttpAuthorizationSource  # noqa: E402
from nex_wc.event_delivery_process import (  # noqa: E402
    PROCESS_ID as DELIVERY_PROCESS_ID,
    build_installed_wc_event_delivery_process,
    run_installed_wc_event_delivery_process,
)
from nex_wc.work_item_api import register_work_item_routes  # noqa: E402
from nex_wc.work_items import (  # noqa: E402
    SqlAlchemyWorkItemRepository,
    WorkItemService,
)
from protected_tenant_cleanup import (  # noqa: E402
    cleanup_ae_tenant,
    cleanup_oa_tenant,
    cleanup_wc_tenant,
)
from run_migrations import run_service_migrations  # noqa: E402

SCHEMA_VERSION = "mybee_w70_cp_m1_01b6b5b5_protected_gate.v1"
SLICE = "CP-M1-E2E-FX-01B.6B.5B.5"
SMOKE_ENV = "NEX_MYBEE_W70_01B6B5B5_POSTGRES_GATE"
WC_DATABASE_ENV = "NEX_WC_TEST_DATABASE_URL"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
OA_DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
DATABASE_TARGETS = {
    WC_DATABASE_ENV: ("nex_wc_user", "nex_wc_test"),
    AE_DATABASE_ENV: ("nex_ae_user", "nex_ae_test"),
    OA_DATABASE_ENV: ("nex_oa_user", "nex_oa_test"),
}
AE_BASE_URL = "http://ae.01b6b5b5.local"
AE_HANDOFF_BASE_URL = "http://ae-handoff.01b6b5b5.local"
OA_BASE_URL = "http://oa.01b6b5b5.local"
SIGNING_REFERENCE = "memory://mybee-01b6b5b5-oa-signing-key"
SIGNING_KEY_ID = "mybee-01b6b5b5-oa-signing-key"
DEFAULT_REPORT = ROOT / "reports/quality/mybee-w70-01b6b5b5-protected-gate.json"


class _BridgeResponse:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def read(self) -> bytes:
        return self._content

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _MultiAppUrlOpen:
    def __init__(self, clients: Mapping[str, TestClient]) -> None:
        self._clients = dict(clients)
        self._lock = Lock()
        self.attempts: list[dict[str, object]] = []

    def __call__(self, request, *, timeout: float):
        parsed = urlsplit(request.full_url)
        client = self._clients.get(parsed.netloc)
        if client is None:
            raise OSError("protected bridge target is not admitted")
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        response = client.request(
            request.get_method(),
            path,
            content=request.data,
            headers=dict(request.header_items()),
        )
        with self._lock:
            try:
                problem = response.json() if response.status_code >= 400 else {}
            except ValueError:
                problem = {}
            self.attempts.append(
                {
                    "host": parsed.netloc,
                    "method": request.get_method(),
                    "status_code": response.status_code,
                    "error_code": problem.get("error_code"),
                    "timeout": float(timeout),
                }
            )
        if response.status_code >= 400:
            raise HTTPError(
                request.full_url,
                response.status_code,
                response.reason_phrase,
                response.headers,
                BytesIO(response.content),
            )
        return _BridgeResponse(response.content)


def run_protected_gate(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": SLICE,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
            "remote_provider_contacted": False,
        }
    urls = {name: str(env.get(name) or "") for name in DATABASE_TARGETS}
    missing = sorted(name for name, value in urls.items() if not value)
    if missing:
        return _failure("database_url_missing", f"{','.join(missing)} is required.")
    if any(
        not _target_url_allowed(urls[name], *DATABASE_TARGETS[name])
        for name in DATABASE_TARGETS
    ):
        return _failure(
            "target_not_allowed",
            "actual nex_wc_test, nex_ae_test, and nex_oa_test targets are required",
        )
    try:
        migrations = {
            service: run_service_migrations(
                service,
                database_url=urls[database_env],
                profile="test",
            )
            for service, database_env in (
                ("nex-wc", WC_DATABASE_ENV),
                ("nex-ae-api", AE_DATABASE_ENV),
                ("nex-oa", OA_DATABASE_ENV),
            )
        }
        execution = _execute_protected_gate(
            wc_database_url=urls[WC_DATABASE_ENV],
            ae_database_url=urls[AE_DATABASE_ENV],
            oa_database_url=urls[OA_DATABASE_ENV],
        )
        checks = {
            "migrations_current": all(
                len(item.planned) == len(item.applied) + len(item.skipped)
                for item in migrations.values()
            ),
            **dict(execution["checks"]),
        }
        evidence = {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": SLICE,
            "status": "PASS" if all(checks.values()) else "FAIL",
            "evidence_classification": "PROTECTED_COMPONENT",
            "profile": "test",
            "actual_postgres": True,
            "remote_provider_contacted": False,
            "redacted_database_urls": {
                name: redact_database_url(value) for name, value in urls.items()
            },
            "migration_heads": {
                service: result.planned[-1]
                for service, result in migrations.items()
                if result.planned
            },
            "checks": checks,
            **{key: value for key, value in execution.items() if key != "checks"},
        }
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "protected_gate_failed"
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected Gate boundary.
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_urls=tuple(urls.values())),
        )


def _execute_protected_gate(
    *, wc_database_url: str, ae_database_url: str, oa_database_url: str
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    tenant_id = f"wc-gate-{suffix}"
    project_id = f"project-{suffix}"
    requester_id = f"requester-{suffix}"
    denied_requester_id = f"denied-{suffix}"
    worker_ids = tuple(f"wc-dispatch-{suffix}-{index}" for index in range(1, 6))
    delivery_worker_id = f"wc-delivery-{suffix}"
    now = datetime.now(UTC)
    wc_engine = create_engine(wc_database_url)
    ae_engine = create_engine(ae_database_url)
    wc_sessions = sessionmaker(bind=wc_engine, expire_on_commit=False)
    ae_sessions = sessionmaker(bind=ae_engine, expire_on_commit=False)
    oa_runtime = None
    oa_client: TestClient | None = None
    ae_registry_client: TestClient | None = None
    ae_handoff_client: TestClient | None = None
    wc_client: TestClient | None = None
    processes: list[Any] = []
    original_coordination_urlopen = coordination_clients.urlopen
    original_handoff_urlopen = handoff_delivery.urlopen
    cleanup: dict[str, int] = {}
    evidence: dict[str, Any] = {}
    try:
        cleanup_wc_tenant(
            wc_engine,
            tenant_id=tenant_id,
            worker_ids=worker_ids + (delivery_worker_id,),
        )
        cleanup_ae_tenant(ae_engine, tenant_id=tenant_id)
        foreign_claimable = _foreign_claimable_count(wc_engine, tenant_id=tenant_id)
        if foreign_claimable:
            raise RuntimeError(
                "WC test database contains foreign CREATED/ROUTED WorkItems; "
                "protected dispatcher execution was refused"
            )

        oa_app, oa_runtime, _oa_memberships = _build_oa_app(oa_database_url)
        oa_client = TestClient(oa_app)
        signed = _signed_trust(now_epoch=int(time.time()))
        registry = SqlAlchemyAgentIdentityRegistry(ae_sessions, clock=lambda: now)
        agent = registry.register_agent(
            tenant_id=tenant_id,
            agent_type="PA",
            profile_ref="agent-profile://nex-platform/project-agent/v1",
            project_id=project_id,
        )
        ae_registry_app = FastAPI()
        register_agent_registry_routes(ae_registry_app, registry=registry)
        ae_registry_client = TestClient(ae_registry_app)
        ae_handoff_app = FastAPI()
        ae_handoff_app.state.service_token_admission = signed["admission"]
        register_claim_handoff_routes(
            ae_handoff_app,
            admission=AgentExecutionAdmissionService(
                identities=registry,
                executions=SqlAlchemyAgentExecutionRepository(ae_sessions),
                mode="required",
                clock=lambda: now,
            ),
        )
        ae_handoff_client = TestClient(ae_handoff_app)
        bridge = _MultiAppUrlOpen(
            {
                urlsplit(AE_BASE_URL).netloc: ae_registry_client,
                urlsplit(AE_HANDOFF_BASE_URL).netloc: ae_handoff_client,
                urlsplit(OA_BASE_URL).netloc: oa_client,
            }
        )
        coordination_clients.urlopen = bridge
        handoff_delivery.urlopen = bridge

        oa_read_token = _mock_service_token(
            service_id="nex-wc",
            audience="nex-oa",
            scopes=(OA_AUTHORIZATION_READ_SCOPE,),
        )
        ae_registry_token = _mock_service_token(
            service_id="nex-wc",
            audience="nex-ae-api",
            scopes=(),
        )
        _seed_oa_membership(
            oa_client,
            tenant_id=tenant_id,
            subject_id=requester_id,
            scopes=("work:delegate", "work:claim"),
        )
        _seed_oa_membership(
            oa_client,
            tenant_id=tenant_id,
            subject_id=denied_requester_id,
            scopes=("work:delegate",),
        )

        wc_app = FastAPI()
        register_work_item_routes(
            wc_app,
            service=WorkItemService(
                SqlAlchemyWorkItemRepository(wc_sessions),
                authorization_source=HttpAuthorizationSource(
                    base_url=OA_BASE_URL,
                    service_token=oa_read_token,
                ),
            ),
        )
        wc_client = TestClient(wc_app)
        item = _create_public_work_item(
            wc_client,
            tenant_id=tenant_id,
            project_id=project_id,
            requester_id=requester_id,
            suffix=suffix,
        )

        dispatch_env = {
            WC_DATABASE_ENV: wc_database_url,
            "NEX_WC_AE_BASE_URL": AE_BASE_URL,
            "NEX_WC_OA_BASE_URL": OA_BASE_URL,
            "NEX_WC_TO_AE_SERVICE_TOKEN": ae_registry_token,
            "NEX_WC_TO_OA_SERVICE_TOKEN": oa_read_token,
            "NEX_WC_ASSIGNMENT_DISPATCH_POLL_SECONDS": "0.001",
        }
        route_processes = [
            _build_dispatch_process(dispatch_env, worker_id=worker_ids[index])
            for index in range(2)
        ]
        processes.extend(route_processes)
        with ThreadPoolExecutor(max_workers=2) as executor:
            route_runs = list(executor.map(_run_route_stage, route_processes))
        for process in route_processes:
            process.close()
            processes.remove(process)

        routed = _work_item_state(
            wc_engine, tenant_id=tenant_id, work_item_id=item["work_item_id"]
        )
        claim_processes = [
            _build_dispatch_process(dispatch_env, worker_id=worker_ids[index])
            for index in range(2, 4)
        ]
        processes.extend(claim_processes)
        with ThreadPoolExecutor(max_workers=2) as executor:
            claim_runs = list(
                executor.map(lambda value: value.run_once(), claim_processes)
            )
        for process in claim_processes:
            process.close()
            processes.remove(process)

        replay_process = _build_dispatch_process(dispatch_env, worker_id=worker_ids[4])
        processes.append(replay_process)
        replay_run = run_installed_wc_assignment_dispatch_process(
            replay_process,
            max_cycles=1,
            out=StringIO(),
        )
        replay_process.close()
        processes.remove(replay_process)

        authority = _assignment_authority_counts(
            wc_engine, tenant_id=tenant_id, work_item_id=item["work_item_id"]
        )
        delivery_env = {
            WC_DATABASE_ENV: wc_database_url,
            "NEX_WC_AE_BASE_URL": AE_HANDOFF_BASE_URL,
            "NEX_WC_TO_AE_SERVICE_TOKEN": signed["token"],
            "NEX_WC_EVENT_DELIVERY_WORKER_ID": delivery_worker_id,
            "NEX_WC_EVENT_DELIVERY_POLL_SECONDS": "0.001",
        }
        delivery = build_installed_wc_event_delivery_process(
            "test", environ=delivery_env
        )
        processes.append(delivery)
        delivery_readiness = delivery.readiness()
        delivery_run = run_installed_wc_event_delivery_process(
            delivery, max_cycles=1, out=StringIO()
        )
        delivery.close()
        processes.remove(delivery)

        restarted_delivery = build_installed_wc_event_delivery_process(
            "test", environ=delivery_env
        )
        processes.append(restarted_delivery)
        delivery_restart = run_installed_wc_event_delivery_process(
            restarted_delivery, max_cycles=1, out=StringIO()
        )
        restarted_delivery.close()
        processes.remove(restarted_delivery)
        delivery_counts = _delivery_counts(ae_engine, wc_engine, tenant_id=tenant_id)

        denied = _create_public_work_item(
            wc_client,
            tenant_id=tenant_id,
            project_id=project_id,
            requester_id=denied_requester_id,
            suffix=f"{suffix}-denied",
        )
        denied_process = _build_dispatch_process(
            dispatch_env, worker_id=f"{worker_ids[4]}-denied"
        )
        processes.append(denied_process)
        denied_run = denied_process.run_once()
        denied_process.close()
        processes.remove(denied_process)
        denied_counts = _denied_authority_counts(
            wc_engine, tenant_id=tenant_id, work_item_id=denied["work_item_id"]
        )
        database_identities = {
            "wc": _database_identity(wc_engine),
            "ae": _database_identity(ae_engine),
            "oa": _database_identity(oa_runtime.api_engine),
        }
        dispatch_heartbeat = _heartbeat_count(
            wc_engine, worker_id=worker_ids[4], process_id=DISPATCH_PROCESS_ID
        )
        delivery_heartbeat = _heartbeat_count(
            wc_engine, worker_id=delivery_worker_id, process_id=DELIVERY_PROCESS_ID
        )
        checks = {
            "actual_database_identities": database_identities
            == {
                "wc": ("nex_wc_test", "nex_wc_user"),
                "ae": ("nex_ae_test", "nex_ae_user"),
                "oa": ("nex_oa_test", "nex_oa_user"),
            },
            "public_work_item_created": item["state"] == "CREATED",
            "concurrent_route_converged": routed == "ROUTED"
            and sum(run["execution_status"] == "SUCCEEDED" for run in route_runs) == 1,
            "restart_claim_converged": authority
            == {"assignment": 1, "claim": 1, "outbox": 1, "state": "ASSIGNED"},
            "concurrent_claim_exactly_once": sum(
                int(run["succeeded_count"]) for run in claim_runs
            )
            == 1,
            "dispatcher_replay_idle": replay_run["work_cycles"] == 0,
            "event_delivery_ready": delivery_readiness["readiness_status"] == "READY",
            "authoritative_handoff_delivered_once": delivery_counts
            == {
                "outbox_delivered": 1,
                "handoff_inbox": 1,
                "agent_execution": 1,
            },
            "delivery_restart_idempotent": delivery_restart["work_cycles"] == 0,
            "oa_claim_denial_fail_closed": denied_run["failed_count"] == 1
            and denied_counts
            == {"assignment": 0, "claim": 0, "outbox": 0, "state": "ROUTED"},
            "heartbeats_persisted": dispatch_heartbeat == 1 and delivery_heartbeat == 1,
            "signed_ae_transport_used": signed["admission"].public_snapshot()[
                "admission_counts"
            ]["accepted_signed"]
            >= 1,
            "no_remote_provider_contact": True,
        }
        evidence = {
            "checks": checks,
            "database_identities": {
                name: {"database": value[0], "role": value[1]}
                for name, value in database_identities.items()
            },
            "row_counts": {
                **authority,
                **delivery_counts,
                "bridge_attempts": len(bridge.attempts),
                "dispatch_jobs": _job_count(wc_engine, "WC_ASSIGNMENT_DISPATCH"),
                "delivery_jobs": _job_count(wc_engine, "WC_EVENT_DELIVERY"),
            },
            "processes": {
                "dispatcher": DISPATCH_PROCESS_ID,
                "event_delivery": DELIVERY_PROCESS_ID,
            },
            "dispatch_runs": {
                "route": route_runs,
                "claim": claim_runs,
                "replay": replay_run,
            },
            "bridge_attempts": list(bridge.attempts),
            "job_projection": _job_projection(wc_engine, tenant_id=tenant_id),
            "denial": {"run": denied_run, "authority": denied_counts},
            "agent_id_hash": (
                "sha256:"
                f"{hashlib.sha256(str(agent['agent_id']).encode()).hexdigest()}"
            ),
            "secret_included": False,
        }
    finally:
        coordination_clients.urlopen = original_coordination_urlopen
        handoff_delivery.urlopen = original_handoff_urlopen
        for process in processes:
            process.close()
        for client in (wc_client, ae_registry_client, ae_handoff_client, oa_client):
            if client is not None:
                client.close()
        cleanup.update(
            cleanup_wc_tenant(
                wc_engine,
                tenant_id=tenant_id,
                worker_ids=worker_ids + (f"{worker_ids[4]}-denied", delivery_worker_id),
            )
        )
        cleanup.update(cleanup_ae_tenant(ae_engine, tenant_id=tenant_id))
        if oa_runtime is not None:
            cleanup.update(
                cleanup_oa_tenant(oa_runtime.api_engine, tenant_id=tenant_id)
            )
            _dispose_runtime(oa_runtime)
        wc_engine.dispose()
        ae_engine.dispose()
    evidence["cleanup_counts"] = cleanup
    evidence.setdefault("checks", {})["zero_residue"] = all(
        cleanup.get(name, -1) == 0
        for name in ("wc_remaining", "ae_remaining", "oa_remaining")
    )
    return evidence


def _build_oa_app(database_url: str):
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    runtime = attach_service_persistence_runtime(
        app,
        SERVICE_SPECS["nex-oa"],
        environ={
            SERVICE_SPECS["nex-oa"].database_env: database_url,
            "NEX_OA_PERSISTENCE_MODE": "postgres",
        },
    )
    if runtime.api_engine is None or runtime.api_session_factory is None:
        raise RuntimeError("OA PostgreSQL runtime is unavailable")
    subjects = build_subject_registry_for_runtime(runtime)
    memberships = build_tenant_membership_registry_for_runtime(
        runtime, subject_registry=subjects
    )
    repository = build_authorization_repository_for_runtime(runtime)
    register_identity_membership_routes(app, registry=memberships)
    register_authorization_routes(
        app,
        service=OaAuthorizationService(
            repository,
            OaEffectiveAuthorizationResolver(repository),
            memberships,
        ),
    )
    return app, runtime, memberships


def _seed_oa_membership(
    client: TestClient,
    *,
    tenant_id: str,
    subject_id: str,
    scopes: tuple[str, ...],
) -> None:
    response = client.post(
        "/internal/v1/identity/memberships/ensure",
        headers=_service_headers(
            service_id="nex-wc",
            audience="nex-oa",
            scopes=(OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE,),
        ),
        json={
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "tenant_display_name": "Protected WC Gate Tenant",
            "subject_display_name": "Protected WC Gate Subject",
            "roles": ["employee"],
            "scopes": list(scopes),
        },
    )
    response.raise_for_status()


def _create_public_work_item(
    client: TestClient,
    *,
    tenant_id: str,
    project_id: str,
    requester_id: str,
    suffix: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/work-items",
        headers=_service_headers(
            service_id="nex-ae-api",
            audience="nex-wc",
            scopes=(),
        ),
        json=_work_item_payload(
            tenant_id=tenant_id,
            project_id=project_id,
            requester_id=requester_id,
            suffix=suffix,
        ),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload.get("work_item"), dict):
        raise RuntimeError("public WC WorkItem response is invalid")
    return dict(payload["work_item"])


def _work_item_payload(
    *, tenant_id: str, project_id: str, requester_id: str, suffix: str
) -> dict[str, Any]:
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": f"delegation-{suffix}",
            "tenant_id": tenant_id,
            "parent_agent_execution_id": f"execution-{suffix}",
            "parent_executable_plan_id": f"plan-{suffix}",
            "parent_executable_step_id": f"step-{suffix}",
            "delegation_revision": 1,
            "goal": "Execute an admitted generic finance operation",
            "work_class": "BUSINESS_TRANSACTION",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.VOUCHER.APPROVE_AND_POST",
            "project_ref": {"entity_type": "PROJECT", "entity_id": project_id},
            "project_scope_ref": project_id,
            "result_contract_ref": "urn:nex:result:finance:v1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": f"trace-{suffix}",
            "causation_id": f"cause-{suffix}",
        },
        "requester": {"entity_type": "USER", "entity_id": requester_id},
        "accountable_owner": {"entity_type": "USER", "entity_id": requester_id},
    }


def _build_dispatch_process(env: Mapping[str, str], *, worker_id: str):
    return build_installed_wc_assignment_dispatch_process(
        "test",
        environ={
            **dict(env),
            "NEX_WC_ASSIGNMENT_DISPATCH_WORKER_ID": worker_id,
        },
    )


def _run_route_stage(process) -> dict[str, Any]:
    scan = enqueue_claimable_assignment_jobs(
        repository=process.repository,
        queue=process.queue,
        state="CREATED",
        limit=process.scan_limit,
    )
    execution = process._run_worker_once()
    return {
        "scanned_count": scan["scanned_count"],
        "enqueued_count": scan["enqueued_count"],
        "execution_status": execution.status,
    }


def _signed_trust(*, now_epoch: int) -> dict[str, Any]:
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(SIGNING_REFERENCE)
    verifier = SignedServiceTokenVerifier(
        BoundedJwksCache(
            StaticJwksSource(
                {
                    "issuer": "urn:nex-platform:oa",
                    "keys": [
                        signer.public_jwk(SIGNING_REFERENCE, key_id=SIGNING_KEY_ID)
                    ],
                }
            ),
            clock=lambda: now_epoch,
        ),
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
        "token": encode_signed_jwt(
            headers={"alg": "RS256", "typ": "at+jwt", "kid": SIGNING_KEY_ID},
            claims={
                "iss": "urn:nex-platform:oa",
                "sub": "service:nex-wc",
                "aud": "nex-ae-api",
                "iat": now_epoch - 5,
                "nbf": now_epoch - 5,
                "exp": now_epoch + 240,
                "jti": f"wc-{uuid4()}",
                "token_use": "service_access",
                "scope": DEFAULT_SERVICE_SCOPE,
                "service_id": "nex-wc",
                "credential_id": "cred-nex-wc-01b6b5b5",
                "credential_revision": 1,
            },
            private_key_ref=SIGNING_REFERENCE,
            signing_provider=signer,
        ),
    }


def _mock_service_token(
    *, service_id: str, audience: str, scopes: tuple[str, ...]
) -> str:
    return issue_mock_service_token(
        service_id=service_id,
        audience=audience,
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
    ).access_token


def _service_headers(
    *, service_id: str, audience: str, scopes: tuple[str, ...]
) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_mock_service_token(service_id=service_id, audience=audience, scopes=scopes)}",
        "X-Request-ID": str(uuid4()),
        "traceparent": f"00-{uuid4().hex}-{uuid4().hex[:16]}-01",
    }


def _database_identity(engine) -> tuple[str, str]:
    with engine.connect() as connection:
        database, role = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
    return str(database), str(role)


def _foreign_claimable_count(engine, *, tenant_id: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM wc_work_item "
                    "WHERE tenant_id <> :tenant_id AND state IN ('CREATED','ROUTED')"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )


def _work_item_state(engine, *, tenant_id: str, work_item_id: str) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT state FROM wc_work_item "
                "WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id"
            ),
            {"tenant_id": tenant_id, "work_item_id": work_item_id},
        ).scalar_one_or_none()


def _assignment_authority_counts(
    engine, *, tenant_id: str, work_item_id: str
) -> dict[str, Any]:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT w.state, "
                    "(SELECT count(*) FROM wc_assignment a WHERE a.tenant_id = w.tenant_id "
                    "AND a.work_item_id = w.work_item_id) AS assignment_count, "
                    "(SELECT count(*) FROM wc_claim c WHERE c.tenant_id = w.tenant_id "
                    "AND c.work_item_id = w.work_item_id) AS claim_count, "
                    "(SELECT count(*) FROM wc_event_outbox o WHERE o.tenant_id = w.tenant_id "
                    "AND o.work_item_id = w.work_item_id) AS outbox_count "
                    "FROM wc_work_item w WHERE w.tenant_id = :tenant_id "
                    "AND w.work_item_id = :work_item_id"
                ),
                {"tenant_id": tenant_id, "work_item_id": work_item_id},
            )
            .mappings()
            .one()
        )
    return {
        "assignment": int(row["assignment_count"]),
        "claim": int(row["claim_count"]),
        "outbox": int(row["outbox_count"]),
        "state": str(row["state"]),
    }


def _denied_authority_counts(
    engine, *, tenant_id: str, work_item_id: str
) -> dict[str, Any]:
    return _assignment_authority_counts(
        engine, tenant_id=tenant_id, work_item_id=work_item_id
    )


def _delivery_counts(ae_engine, wc_engine, *, tenant_id: str) -> dict[str, int]:
    with wc_engine.connect() as connection:
        delivered = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM wc_event_outbox "
                    "WHERE tenant_id = :tenant_id AND delivery_state = 'DELIVERED'"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
    with ae_engine.connect() as connection:
        inbox = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM ae_claim_handoff_inbox "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
        executions = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM ae_agent_execution "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
    return {
        "outbox_delivered": delivered,
        "handoff_inbox": inbox,
        "agent_execution": executions,
    }


def _heartbeat_count(engine, *, worker_id: str, process_id: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM service_worker_heartbeats "
                    "WHERE service_id = 'nex-wc' AND worker_id = :worker_id "
                    "AND metadata ->> 'process_id' = :process_id"
                ),
                {"worker_id": worker_id, "process_id": process_id},
            ).scalar_one()
        )


def _job_count(engine, job_type: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM service_jobs WHERE job_type = :job_type"),
                {"job_type": job_type},
            ).scalar_one()
        )


def _job_projection(engine, *, tenant_id: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT job_type, status, attempt_count, max_attempts, "
                "error ->> 'error_code' AS error_code, "
                "payload ->> 'action' AS action "
                "FROM service_jobs WHERE links ->> 'tenant_id' = :tenant_id "
                "ORDER BY created_at, job_id"
            ),
            {"tenant_id": tenant_id},
        ).mappings()
        return [dict(row) for row in rows]


def _dispose_runtime(runtime) -> None:
    for engine in (runtime.api_engine, runtime.worker_engine):
        if engine is not None:
            engine.dispose()


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
        "slice": SLICE,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
        "remote_provider_contacted": False,
        "secret_included": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = dict(evidence.get("checks") or {})
    rows = dict(evidence.get("row_counts") or {})
    cleanup = dict(evidence.get("cleanup_counts") or {})
    return (
        "mybee_w70_01b6b5b5_gate="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"assignments={rows.get('assignment', 0)} "
        f"handoffs={rows.get('handoff_inbox', 0)} "
        f"remaining={sum(int(cleanup.get(name, 0)) for name in ('wc_remaining', 'ae_remaining', 'oa_remaining'))}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run MyBee W70 WC assignment-dispatch protected PostgreSQL Gate"
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    env = dict(os.environ)
    env.update(load_env_file(ROOT / args.env_file) or {})
    evidence = run_protected_gate(env)
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
