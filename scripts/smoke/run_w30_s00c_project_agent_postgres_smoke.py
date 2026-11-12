#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-eos",
    ROOT / "scripts" / "db",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import psycopg
from fastapi.testclient import TestClient
from nex_ae_api.project_agent_lifecycle import (
    AE_PROJECT_AGENT_SYNC_TABLE,
    AE_PROJECT_LIFECYCLE_INBOX_TABLE,
    AdmittedProjectAgentProfilePolicy,
    SqlAlchemyProjectAgentLifecycleService,
)
from nex_ae_api.project_agent_lifecycle_api import (
    register_project_agent_lifecycle_routes,
)
from nex_eos import (
    EOS_OUTBOX_TABLE,
    EOS_PROJECT_TABLE,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosOutboxPublisher,
    SqlAlchemyEosProjectRepository,
    append_project_lifecycle_event,
)
from nex_eos.ae_outbox_transport import HttpAeEosOutboxTransport
from nex_runtime import (
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

POLICY_PATH = ROOT / "deployment/product/config/project-agent-profile-policy.v1.json"
POLICY_REF = "policy://nex-platform/project-agent-lifecycle/v1"
TENANT = "VO0C"
NVT_ID = "c6000000-0000-4000-8000-000000000001"
PROJECT_ID = "c6000000-0000-4000-8000-000000000002"
PROJECT_CODE = "VO0CD260001"
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


class _UrlResponse(AbstractContextManager):
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __exit__(self, *args):
        return None


def run_smoke(*, eos_database_url: str, ae_database_url: str) -> dict[str, object]:
    eos_schema = f"mybee_w30s00c_eos_{uuid4().hex}"
    ae_schema = f"mybee_w30s00c_ae_{uuid4().hex}"
    _create_schema(eos_database_url, eos_schema, "nex_eos_test", "nex_eos_user")
    _create_schema(ae_database_url, ae_schema, "nex_ae_test", "nex_ae_user")
    eos_scoped = _scoped_url(eos_database_url, eos_schema)
    ae_scoped = _scoped_url(ae_database_url, ae_schema)
    eos_engine = None
    ae_engine = None
    try:
        eos_migration = run_service_migrations(
            "nex-eos", database_url=eos_scoped, profile="test"
        )
        ae_migration = run_service_migrations(
            "nex-ae-api", database_url=ae_scoped, profile="test"
        )
        eos_engine = create_engine(eos_scoped, pool_pre_ping=True)
        ae_engine = create_engine(ae_scoped, pool_pre_ping=True)
        eos_sessions = sessionmaker(bind=eos_engine, expire_on_commit=False)
        ae_sessions = sessionmaker(bind=ae_engine, expire_on_commit=False)
        projects = SqlAlchemyEosProjectRepository(eos_sessions)
        projects.create_nvt_project(
            NvtProjectInput(TENANT, NVT_ID, "NVT-W30-C-PG", "W30 PA PostgreSQL")
        )
        projects.create_project(
            ProjectInput(
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                project_code=PROJECT_CODE,
                name="Project Agent PostgreSQL",
                nvt_project_id=NVT_ID,
                project_request_code="VO0CR260001",
                purpose_type="D",
                origin="APPROVED_APPLICATION",
                approval_evidence_ref="eos.project-approval:VO0CR260001",
                approval_evidence_hash="sha256:" + "a" * 64,
                agent_sync_state="PENDING",
            )
        )
        lineage = str(uuid4())
        with eos_sessions.begin() as session:
            append_project_lifecycle_event(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                project_code=PROJECT_CODE,
                previous_state="SUBMITTED",
                current_state="ACTIVE",
                project_version=1,
                profile_policy_ref=POLICY_REF,
                correlation_id=lineage,
                causation_id=lineage,
                occurred_at=NOW,
            )

        lifecycle = SqlAlchemyProjectAgentLifecycleService(
            ae_sessions,
            profile_policy=AdmittedProjectAgentProfilePolicy.from_path(POLICY_PATH),
            clock=lambda: NOW,
        )
        app = build_service_app(SERVICE_SPECS["nex-ae-api"])
        register_project_agent_lifecycle_routes(app, service=lifecycle)
        client = TestClient(app)
        token = issue_mock_service_token(
            service_id="nex-eos",
            audience="nex-ae-api",
            scopes=["service:call"],
        ).access_token

        def opener(request, *, timeout):
            assert timeout == 10.0
            parsed = urlsplit(request.full_url)
            response = client.post(
                parsed.path,
                content=request.data,
                headers={key: value for key, value in request.header_items()},
            )
            if response.status_code not in {200, 201}:
                raise RuntimeError(f"AE lifecycle HTTP {response.status_code}")
            return _UrlResponse(response.json())

        transport = HttpAeEosOutboxTransport(
            base_url="http://testserver",
            service_token=token,
            opener=opener,
        )
        publisher = SqlAlchemyEosOutboxPublisher(eos_sessions, clock=lambda: NOW)
        receipts = []
        first = publisher.publish_next(transport, tenant_id=TENANT)
        assert first is not None
        receipts.append(first.receipt_ref)
        for version, state in (
            (1, "INACTIVE"),
            (2, "ACTIVE"),
            (3, "CLOSING"),
            (4, "CLOSED"),
        ):
            projects.transition_project_status(
                tenant_id=TENANT,
                project_code=PROJECT_CODE,
                target_status=state,
                expected_version=version,
                profile_policy_ref=POLICY_REF,
            )
            published = publisher.publish_next(transport, tenant_id=TENANT)
            assert published is not None
            receipts.append(published.receipt_ref)

        with eos_sessions() as session:
            project = dict(
                session.execute(
                    select(EOS_PROJECT_TABLE).where(
                        EOS_PROJECT_TABLE.c.tenant_id == TENANT,
                        EOS_PROJECT_TABLE.c.project_id == PROJECT_ID,
                    )
                )
                .mappings()
                .one()
            )
            outbox_count = session.scalar(
                select(func.count()).select_from(EOS_OUTBOX_TABLE)
            )
            pending_count = session.scalar(
                select(func.count())
                .select_from(EOS_OUTBOX_TABLE)
                .where(EOS_OUTBOX_TABLE.c.delivery_state == "PENDING")
            )
        with ae_sessions() as session:
            sync = dict(
                session.execute(select(AE_PROJECT_AGENT_SYNC_TABLE)).mappings().one()
            )
            identity = dict(
                session.execute(
                    text(
                        "SELECT agent_id, status FROM ae_agent_identity "
                        "WHERE tenant_id=:tenant_id AND project_id=:project_id"
                    ),
                    {"tenant_id": TENANT, "project_id": PROJECT_ID},
                )
                .mappings()
                .one()
            )
            identity_count = session.scalar(
                text(
                    "SELECT count(*) FROM ae_agent_identity "
                    "WHERE tenant_id=:tenant_id AND project_id=:project_id"
                ),
                {"tenant_id": TENANT, "project_id": PROJECT_ID},
            )
            inbox_count = session.scalar(
                select(func.count()).select_from(AE_PROJECT_LIFECYCLE_INBOX_TABLE)
            )
        assert project["status"] == "CLOSED"
        assert project["agent_sync_state"] == "IN_SYNC"
        assert sync["agent_status"] == "RETIRED"
        assert sync["capability_mode"] == "RETIRED"
        assert identity["status"] == "RETIRED"
        assert outbox_count == inbox_count == len(receipts) == 5
        assert pending_count == 0
        assert identity_count == 1
        return {
            "schema_version": "mybee.w30_s00c.postgres_smoke.v1",
            "status": "PASS",
            "migration": {
                "eos_latest": eos_migration.applied[-1],
                "ae_latest": ae_migration.applied[-1],
            },
            "project": {
                "project_code": project["project_code"],
                "status": project["status"],
                "agent_sync_state": project["agent_sync_state"],
                "outbox_count": outbox_count,
            },
            "project_agent": {
                "agent_id": str(sync["agent_id"]),
                "status": identity["status"],
                "capability_mode": sync["capability_mode"],
                "identity_count": identity_count,
                "inbox_count": inbox_count,
            },
            "signed_http_delivery_count": len(receipts),
            "zero_residue": True,
        }
    finally:
        if eos_engine is not None:
            eos_engine.dispose()
        if ae_engine is not None:
            ae_engine.dispose()
        _drop_schema(eos_database_url, eos_schema)
        _drop_schema(ae_database_url, ae_schema)


def _create_schema(url: str, schema: str, database: str, user: str) -> None:
    with (
        psycopg.connect(_psycopg_url(url), autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        if cursor.fetchone() != (database, user):
            raise RuntimeError(f"database identity mismatch for {database}")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))


def _drop_schema(url: str, schema: str) -> None:
    with (
        psycopg.connect(_psycopg_url(url), autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
        )
        cursor.execute("SELECT to_regnamespace(%s)", (schema,))
        if cursor.fetchone() != (None,):
            raise RuntimeError(f"schema residue remains: {schema}")


def _scoped_url(url: str, schema: str) -> str:
    return (
        make_url(url)
        .update_query_dict({"options": f"-csearch_path={schema},public"})
        .render_as_string(hide_password=False)
    )


def _psycopg_url(url: str) -> str:
    parsed = make_url(url)
    return parsed.set(drivername="postgresql").render_as_string(hide_password=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eos-database-url", required=True)
    parser.add_argument("--ae-database-url", required=True)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    result = run_smoke(
        eos_database_url=args.eos_database_url,
        ae_database_url=args.ae_database_url,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
