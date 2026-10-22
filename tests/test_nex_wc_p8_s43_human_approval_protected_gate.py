from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
import run_ae_web_credential_login_playwright_postgres_smoke as browser_runtime
from fastapi.testclient import TestClient
from nex_ae_api.approval_facade import (
    HttpWcApprovalClient,
    register_approval_facade_routes,
)
from nex_ae_api.auth_sessions import AUTH_SESSION_MODE_OA, register_auth_session_routes
from nex_ae_api.oa_session_client import HttpOaUserSessionClient
from nex_oa.authorization_repository import (
    build_authorization_repository_for_runtime,
)
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver
from nex_oa.authorization_service import (
    OA_AUTHORIZATION_READ_SCOPE,
    OaAuthorizationService,
    register_authorization_routes,
)
from nex_oa.credentials import (
    build_credential_registry_for_runtime,
    register_local_credential_routes,
)
from nex_oa.memberships import (
    build_tenant_membership_registry_for_runtime,
    register_identity_membership_routes,
)
from nex_oa.sessions import (
    build_oa_session_registry_for_runtime,
    register_user_session_routes,
)
from nex_oa.subjects import (
    OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE,
    build_subject_registry_for_runtime,
    register_subject_registry_routes,
)
from nex_oa.user_login import OaUserLoginService, register_user_login_routes
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    issue_mock_service_token,
)
from nex_wc.approval_api import register_approval_routes
from nex_wc.approvals import (
    ApprovalDecisionAuthorizationError,
    ApprovalDecisionAuthorizer,
    ApprovalDecisionError,
    ApprovalDecisionService,
    ApprovalDetailService,
    ApprovalInboxService,
    ApprovalWorkItemError,
    ApprovalWorkItemService,
    SqlAlchemyApprovalWorkItemRepository,
)
from nex_wc.coordination_clients import HttpAuthorizationSource
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
OA_DATABASE_URL = os.getenv("NEX_OA_TEST_DATABASE_URL", "")
WC_DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_P8_S43_APPROVAL_POSTGRES_SMOKE") == "1"
NODE_RUNNER = (
    ROOT / "apps" / "nex-ae-web" / "scripts" / "runApprovalProtectedPlaywrightSmoke.mjs"
)
PASSWORD = "Nuri1004!"

protected_postgres = pytest.mark.skipif(
    not OA_DATABASE_URL or not WC_DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S43 OA/WC PostgreSQL acceptance is disabled",
)


def _stable_uuid(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"nex-p8-s43:{label}"))


def _service_token(service_id: str, audience: str, *scopes: str) -> str:
    return issue_mock_service_token(
        service_id=service_id,
        audience=audience,
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
    ).access_token


def _identity_headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + _service_token(
            "nex-ae-api",
            "nex-oa",
            OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE,
        ),
        "X-Service-ID": "nex-ae-api",
        "X-Request-ID": str(uuid4()),
    }


def _build_oa_app(database_url: str):
    spec = SERVICE_SPECS["nex-oa"]
    app = build_service_app(spec)
    runtime = attach_service_persistence_runtime(
        app,
        spec,
        environ={
            spec.database_env: database_url,
            "NEX_OA_PERSISTENCE_MODE": "postgres",
        },
    )
    assert runtime.api_session_factory is not None
    subjects = build_subject_registry_for_runtime(runtime)
    memberships = build_tenant_membership_registry_for_runtime(
        runtime,
        subject_registry=subjects,
    )
    authorization_repository = build_authorization_repository_for_runtime(runtime)
    authorization_resolver = OaEffectiveAuthorizationResolver(
        repository=authorization_repository
    )
    sessions = build_oa_session_registry_for_runtime(
        runtime,
        membership_registry=memberships,
        authorization_resolver=authorization_resolver,
    )
    credentials = build_credential_registry_for_runtime(
        runtime,
        subject_registry=subjects,
    )
    authorization = OaAuthorizationService(
        repository=authorization_repository,
        resolver=authorization_resolver,
        membership_registry=memberships,
    )
    register_subject_registry_routes(app, registry=subjects)
    register_identity_membership_routes(app, registry=memberships)
    register_local_credential_routes(app, registry=credentials)
    register_user_session_routes(app, registry=sessions)
    register_user_login_routes(
        app,
        service=OaUserLoginService(
            credential_registry=credentials,
            session_registry=sessions,
        ),
    )
    register_authorization_routes(app, service=authorization)
    return app


def _seed_identity(
    app: Any,
    *,
    tenant_id: str,
    subject_id: str,
    scopes: list[str],
    status: str = "ACTIVE",
    employee_id: str | None = None,
) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/internal/v1/identity/memberships/ensure",
            headers=_identity_headers(),
            json={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "tenant_display_name": "P8-S43 Protected Tenant",
                "subject_display_name": f"P8-S43 {subject_id}",
                "status": status,
                "roles": ["employee"],
                "scopes": scopes,
                "membership_metadata": {"smoke_marker": "p8-s43"},
            },
        )
        response.raise_for_status()
        if employee_id is not None:
            credential = client.post(
                "/internal/v1/auth/local-credentials/ensure",
                headers=_identity_headers(),
                json={
                    "tenant_id": tenant_id,
                    "employee_id": employee_id,
                    "subject_id": subject_id,
                    "password": PASSWORD,
                    "credential_metadata": {"smoke_marker": "p8-s43"},
                },
            )
            credential.raise_for_status()


def _build_wc_app(database_url: str, *, oa_url: str):
    spec = SERVICE_SPECS["nex-wc"]
    app = build_service_app(spec)
    runtime = attach_service_persistence_runtime(
        app,
        spec,
        environ={
            spec.database_env: database_url,
            "NEX_WC_PERSISTENCE_MODE": "postgres",
        },
    )
    assert runtime.api_session_factory is not None
    repository = SqlAlchemyApprovalWorkItemRepository(runtime.api_session_factory)
    authorization = HttpAuthorizationSource(
        base_url=oa_url,
        service_token=_service_token(
            "nex-wc",
            "nex-oa",
            OA_AUTHORIZATION_READ_SCOPE,
        ),
    )
    register_approval_routes(
        app,
        inbox_service=ApprovalInboxService(
            repository,
            authorization_source=authorization,
        ),
        detail_service=ApprovalDetailService(
            repository,
            authorization_source=authorization,
        ),
        decision_service=ApprovalDecisionService(
            repository,
            authorizer=ApprovalDecisionAuthorizer(authorization),
        ),
    )
    return app, repository


def _build_ae_app(*, oa_url: str, wc_url: str):
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    oa_client = HttpOaUserSessionClient(
        base_url=oa_url,
        service_token=_service_token("nex-ae-api", "nex-oa"),
    )
    register_auth_session_routes(
        app,
        oa_session_client=oa_client,
        session_mode=AUTH_SESSION_MODE_OA,
        cookie_secure=False,
    )
    register_approval_facade_routes(
        app,
        wc_client=HttpWcApprovalClient(
            base_url=wc_url,
            service_token=_service_token("nex-ae-api", "nex-wc"),
        ),
        oa_session_client=oa_client,
        session_mode=AUTH_SESSION_MODE_OA,
    )
    return app


def _work_item(
    tenant_id: str,
    label: str,
    *,
    target: str,
    domain: str = "NSL_WRITE",
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    created = created_at or datetime.now(UTC)
    expires = expires_at or created + timedelta(hours=2)
    item: dict[str, Any] = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": tenant_id,
        "approval_work_item_id": _stable_uuid(f"{tenant_id}:{label}"),
        "approval_domain": domain,
        "source_ref": f"approval-request-{label}",
        "semantic_hash": "sha256:" + "a" * 64,
        "title": f"P8-S43 {label}",
        "display_safe_summary": f"Protected approval scenario {label}.",
        "approval_provider_type": {
            "NSL_WRITE": "NSL",
            "AGENT_FORMAL": "AGENT",
            "BUSINESS_FORMAL": "EOS",
        }[domain],
        "approval_target_ref": f"approval-target-{label}",
        "target_approver_ref": target,
        "target_role_ref": None,
        "target_org_scope_ref": None,
        "target_project_scope_ref": None,
        "agent_execution_id": None,
        "executable_step_id": None,
        "nsl_execution_id": None,
        "business_operation_id": f"business-operation-{label}",
        "approval_request_id": None,
        "protected_request_ref": f"ae-private:approval-{label}",
        "resume_target_ref": f"ae-wait:approval-{label}",
        "state": "PENDING",
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "version": 1,
    }
    if domain in {"NSL_WRITE", "AGENT_FORMAL"}:
        item.update(
            {
                "agent_execution_id": f"agent-execution-{label}",
                "executable_step_id": f"step-{label}",
            }
        )
    if domain == "NSL_WRITE":
        item.update(
            {
                "nsl_execution_id": f"nsl-execution-{label}",
                "approval_request_id": f"approval-request-{label}",
            }
        )
    return item


def _assert_database_identity_and_migrations(
    database_url: str,
    *,
    service_id: str,
    expected_user: str,
    expected_database: str,
) -> None:
    target = make_url(database_url)
    assert target.username == expected_user
    assert target.database == expected_database
    expected = [migration.version for migration in load_migrations(service_id)]
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            ) == (expected_database, expected_user)
            applied = set(
                connection.execute(
                    text("SELECT version FROM schema_migrations")
                ).scalars()
            )
        assert set(expected) <= applied
    finally:
        engine.dispose()


def _cleanup_wc(engine: Any, tenant_id: str) -> dict[str, int]:
    tables = (
        "wc_approval_outbox",
        "wc_approval_decision",
        "wc_approval_work_item",
    )
    with engine.begin() as connection:
        for table in tables:
            connection.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
    with engine.connect() as connection:
        return {
            table: int(
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table in tables
        }


def _cleanup_oa(engine: Any, tenant_id: str) -> dict[str, int]:
    tables = (
        "oa_user_sessions",
        "oa_local_credentials",
        "oa_tenant_memberships",
        "oa_subjects",
        "oa_tenants",
    )
    with engine.begin() as connection:
        for table in tables:
            connection.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
    with engine.connect() as connection:
        return {
            table: int(
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table in tables
        }


def _approval_counts(engine: Any, tenant_id: str) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: int(
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table in (
                "wc_approval_work_item",
                "wc_approval_decision",
                "wc_approval_outbox",
            )
        }


def _prepare_databases() -> None:
    run_service_migrations(
        "nex-oa",
        database_url=OA_DATABASE_URL,
        profile="test",
    )
    run_service_migrations(
        "nex-wc",
        database_url=WC_DATABASE_URL,
        profile="test",
    )
    _assert_database_identity_and_migrations(
        OA_DATABASE_URL,
        service_id="nex-oa",
        expected_user="nex_oa_user",
        expected_database="nex_oa_test",
    )
    _assert_database_identity_and_migrations(
        WC_DATABASE_URL,
        service_id="nex-wc",
        expected_user="nex_wc_user",
        expected_database="nex_wc_test",
    )


def _decision_service(repository, authorization, now: datetime):
    return ApprovalDecisionService(
        repository,
        authorizer=ApprovalDecisionAuthorizer(
            authorization,
            clock=lambda: now,
        ),
        clock=lambda: now,
    )


def test_s43_protected_gate_inventory_matches_the_p8_3_exit_boundary() -> None:
    plan = (ROOT / "docs/transition/P8/P8_Implementation_Slice_Plan_v1.0.md").read_text(
        encoding="utf-8"
    )
    srs = (
        ROOT
        / "docs/transition/P8/P8_Controlled_WRITE_Approval_Delegation_and_Enterprise_OS_SRS_v1.0.md"
    ).read_text(encoding="utf-8")
    package = json.loads(
        (ROOT / "apps/nex-ae-web/package.json").read_text(encoding="utf-8")
    )
    assert "P8-S43 — Human Approval Foundation Protected Gate" in plan
    assert all(
        phrase in srs
        for phrase in (
            "ApprovalWorkItem persistence",
            "IA pending inbox",
            "fresh OA approval:read/decide",
            "duplicate/conflict behavior",
            "BUSINESS_FORMAL schema/domain support",
        )
    )
    assert package["scripts"]["smoke:approval-protected-playwright"] == (
        "node scripts/runApprovalProtectedPlaywrightSmoke.mjs --summary"
    )


@protected_postgres
def test_s43_actual_oa_wc_postgres_authorization_create_and_decision_gate() -> None:
    _prepare_databases()
    suffix = uuid4().hex[:8]
    tenant_id = f"tenant-p8-s43-core-{suffix}"
    approver = f"approver-{suffix}"
    read_only = f"reader-{suffix}"
    inactive = f"inactive-{suffix}"
    other = f"other-{suffix}"
    oa_engine = create_engine(OA_DATABASE_URL)
    wc_engine = create_engine(WC_DATABASE_URL)
    oa_server = None
    try:
        assert all(value == 0 for value in _cleanup_wc(wc_engine, tenant_id).values())
        assert all(value == 0 for value in _cleanup_oa(oa_engine, tenant_id).values())
        oa_app = _build_oa_app(OA_DATABASE_URL)
        common = [DEFAULT_USER_SCOPE, "approval:read"]
        _seed_identity(
            oa_app,
            tenant_id=tenant_id,
            subject_id=approver,
            scopes=[*common, "approval:decide"],
        )
        _seed_identity(
            oa_app,
            tenant_id=tenant_id,
            subject_id=read_only,
            scopes=common,
        )
        _seed_identity(
            oa_app,
            tenant_id=tenant_id,
            subject_id=inactive,
            scopes=[*common, "approval:decide"],
            status="DISABLED",
        )
        _seed_identity(
            oa_app,
            tenant_id=tenant_id,
            subject_id=other,
            scopes=[*common, "approval:decide"],
        )
        oa_server = browser_runtime.start_api_server(
            oa_app,
            browser_runtime.find_free_port(),
        )
        _, repository = _build_wc_app(WC_DATABASE_URL, oa_url=oa_server.url)
        work_items = ApprovalWorkItemService(repository)
        authorization = HttpAuthorizationSource(
            base_url=oa_server.url,
            service_token=_service_token(
                "nex-wc",
                "nex-oa",
                OA_AUTHORIZATION_READ_SCOPE,
            ),
        )
        now = datetime.now(UTC)

        primary = _work_item(tenant_id, "primary", target=approver)
        first = work_items.create_or_get(primary)
        replay = work_items.create_or_get(primary)
        assert first["created"] is True
        assert replay["created"] is False
        assert (
            replay["work_item"]["approval_work_item_id"]
            == primary["approval_work_item_id"]
        )
        with pytest.raises(ApprovalWorkItemError) as semantic_conflict:
            work_items.create_or_get({**primary, "semantic_hash": "sha256:" + "b" * 64})
        assert semantic_conflict.value.error_code == (
            "wc.approval_work_item_idempotency_conflict"
        )

        denied_cases = (
            ("read-only", read_only, read_only, authorization, 403),
            ("inactive", inactive, inactive, authorization, 403),
            ("target-mismatch", approver, other, authorization, 403),
        )
        for label, target, principal, source, status_code in denied_cases:
            item = _work_item(tenant_id, label, target=target)
            work_items.create_or_get(item)
            with pytest.raises(ApprovalDecisionAuthorizationError) as denied:
                _decision_service(repository, source, now).decide(
                    tenant_id=tenant_id,
                    approval_work_item_id=item["approval_work_item_id"],
                    decision="APPROVE",
                    decided_by=principal,
                )
            assert denied.value.status_code == status_code

        class UnavailableAuthorization:
            def effective_authorization(self, **_kwargs):
                raise RuntimeError("OA unavailable")

        unavailable_item = _work_item(
            tenant_id,
            "oa-unavailable",
            target=approver,
        )
        work_items.create_or_get(unavailable_item)
        with pytest.raises(ApprovalDecisionAuthorizationError) as unavailable:
            _decision_service(
                repository,
                UnavailableAuthorization(),
                now,
            ).decide(
                tenant_id=tenant_id,
                approval_work_item_id=unavailable_item["approval_work_item_id"],
                decision="APPROVE",
                decided_by=approver,
            )
        assert unavailable.value.status_code == 503
        assert unavailable.value.retryable is True

        service = _decision_service(repository, authorization, now)
        decision_args = {
            "tenant_id": tenant_id,
            "approval_work_item_id": primary["approval_work_item_id"],
            "decision": "APPROVE",
            "decided_by": approver,
            "decision_comment": "P8-S43 protected approval",
            "correlation_id": f"correlation-{suffix}",
            "causation_id": f"causation-{suffix}",
        }
        approved = service.decide(**decision_args)
        exact_replay = service.decide(**decision_args)
        assert approved["created"] is True
        assert exact_replay["created"] is False
        assert (
            exact_replay["decision"]["decision_id"]
            == approved["decision"]["decision_id"]
        )
        with pytest.raises(ApprovalDecisionError) as terminal_conflict:
            service.decide(**{**decision_args, "decision": "REJECT"})
        assert terminal_conflict.value.status_code == 409

        expired = _work_item(
            tenant_id,
            "expired",
            target=approver,
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
        work_items.create_or_get(expired)
        with pytest.raises(ApprovalDecisionError) as expired_error:
            service.decide(
                tenant_id=tenant_id,
                approval_work_item_id=expired["approval_work_item_id"],
                decision="APPROVE",
                decided_by=approver,
            )
        assert expired_error.value.error_code == "wc.approval_decision_expired"

        counts = _approval_counts(wc_engine, tenant_id)
        assert counts["wc_approval_work_item"] == 6
        assert counts["wc_approval_decision"] == 1
        assert counts["wc_approval_outbox"] == 1
    finally:
        if oa_server is not None:
            oa_server.stop()
        wc_residue = _cleanup_wc(wc_engine, tenant_id)
        oa_residue = _cleanup_oa(oa_engine, tenant_id)
        wc_engine.dispose()
        oa_engine.dispose()
    assert all(value == 0 for value in wc_residue.values()), wc_residue
    assert all(value == 0 for value in oa_residue.values()), oa_residue


@protected_postgres
def test_s43_authenticated_ia_ui_uses_actual_oa_wc_postgres() -> None:
    _prepare_databases()
    suffix = uuid4().hex[:8]
    tenant_id = f"tenant-p8-s43-ui-{suffix}"
    subject_id = f"approver-{suffix}"
    employee_id = f"EMP-P8-S43-{suffix}"
    hidden_subject = f"hidden-{suffix}"
    oa_engine = create_engine(OA_DATABASE_URL)
    wc_engine = create_engine(WC_DATABASE_URL)
    servers: list[Any] = []
    try:
        assert all(value == 0 for value in _cleanup_wc(wc_engine, tenant_id).values())
        assert all(value == 0 for value in _cleanup_oa(oa_engine, tenant_id).values())
        oa_app = _build_oa_app(OA_DATABASE_URL)
        _seed_identity(
            oa_app,
            tenant_id=tenant_id,
            subject_id=subject_id,
            employee_id=employee_id,
            scopes=[
                DEFAULT_USER_SCOPE,
                "documents:upload",
                "approval:read",
                "approval:decide",
            ],
        )
        oa_server = browser_runtime.start_api_server(
            oa_app,
            browser_runtime.find_free_port(),
        )
        servers.append(oa_server)
        wc_app, repository = _build_wc_app(
            WC_DATABASE_URL,
            oa_url=oa_server.url,
        )
        now = datetime.now(UTC)
        items = {
            "approve": _work_item(
                tenant_id,
                "ui-approve",
                target=subject_id,
                domain="NSL_WRITE",
            ),
            "reject": _work_item(
                tenant_id,
                "ui-reject",
                target=subject_id,
                domain="BUSINESS_FORMAL",
            ),
            "hidden": _work_item(
                tenant_id,
                "ui-hidden",
                target=hidden_subject,
                domain="AGENT_FORMAL",
            ),
            "expired": _work_item(
                tenant_id,
                "ui-expired",
                target=subject_id,
                domain="NSL_WRITE",
                created_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            ),
        }
        service = ApprovalWorkItemService(repository)
        for item in items.values():
            assert service.create_or_get(item)["created"] is True

        wc_server = browser_runtime.start_api_server(
            wc_app,
            browser_runtime.find_free_port(),
        )
        servers.append(wc_server)
        ae_server = browser_runtime.start_api_server(
            _build_ae_app(oa_url=oa_server.url, wc_url=wc_server.url),
            browser_runtime.find_free_port(),
        )
        servers.append(ae_server)
        web_server = browser_runtime.start_web_server(
            browser_runtime.find_free_port(),
            ae_server.url,
        )
        servers.append(web_server)

        node_env = {
            **os.environ,
            "NEX_P8_S43_WEB_URL": web_server.url,
            "NEX_P8_S43_TENANT_ID": tenant_id,
            "NEX_P8_S43_EMPLOYEE_ID": employee_id,
            "NEX_P8_S43_PASSWORD": PASSWORD,
            "NEX_P8_S43_APPROVE_GATE_ID": items["approve"]["approval_work_item_id"],
            "NEX_P8_S43_REJECT_GATE_ID": items["reject"]["approval_work_item_id"],
            "NEX_P8_S43_HIDDEN_GATE_ID": items["hidden"]["approval_work_item_id"],
            "NEX_P8_S43_EXPIRED_GATE_ID": items["expired"]["approval_work_item_id"],
        }
        completed = subprocess.run(
            ["node", str(NODE_RUNNER)],
            cwd=ROOT,
            env=node_env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout or completed.stderr
        evidence = json.loads(completed.stdout)
        assert evidence["status"] == "PASS", evidence
        assert evidence["runner"] == {
            "tool": "Playwright",
            "browser": "chromium",
            "headless": True,
            "client_mode": "fetch",
            "postgresql_used": True,
        }
        assert all(evidence["checks"].values()), evidence

        with wc_engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT w.approval_work_item_id, w.state, d.decision,
                           count(o.outbox_id) AS outbox_count
                    FROM wc_approval_work_item w
                    LEFT JOIN wc_approval_decision d
                      ON d.tenant_id = w.tenant_id
                     AND d.approval_work_item_id = w.approval_work_item_id
                    LEFT JOIN wc_approval_outbox o
                      ON o.tenant_id = d.tenant_id
                     AND o.decision_id = d.decision_id
                    WHERE w.tenant_id = :tenant_id
                    GROUP BY w.approval_work_item_id, w.state, d.decision
                    """
                    ),
                    {"tenant_id": tenant_id},
                )
                .mappings()
                .all()
            )
        by_id = {str(row["approval_work_item_id"]): row for row in rows}
        assert by_id[items["approve"]["approval_work_item_id"]]["state"] == ("APPROVED")
        assert by_id[items["approve"]["approval_work_item_id"]]["decision"] == (
            "APPROVE"
        )
        assert by_id[items["approve"]["approval_work_item_id"]]["outbox_count"] == 1
        assert by_id[items["reject"]["approval_work_item_id"]]["state"] == ("REJECTED")
        assert by_id[items["reject"]["approval_work_item_id"]]["decision"] == ("REJECT")
        assert by_id[items["reject"]["approval_work_item_id"]]["outbox_count"] == 1
        assert by_id[items["hidden"]["approval_work_item_id"]]["state"] == "PENDING"
        assert by_id[items["expired"]["approval_work_item_id"]]["state"] == "PENDING"
        counts = _approval_counts(wc_engine, tenant_id)
        assert counts == {
            "wc_approval_work_item": 4,
            "wc_approval_decision": 2,
            "wc_approval_outbox": 2,
        }
    finally:
        for server in reversed(servers):
            server.stop()
        wc_residue = _cleanup_wc(wc_engine, tenant_id)
        oa_residue = _cleanup_oa(oa_engine, tenant_id)
        wc_engine.dispose()
        oa_engine.dispose()
    assert all(value == 0 for value in wc_residue.values()), wc_residue
    assert all(value == 0 for value in oa_residue.values()), oa_residue
