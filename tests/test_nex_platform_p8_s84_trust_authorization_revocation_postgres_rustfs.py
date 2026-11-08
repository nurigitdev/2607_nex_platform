from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import check_nsl_v02_readiness as nsl_readiness
import pytest
import run_ae_web_credential_login_playwright_postgres_smoke as browser_runtime
import run_p8_s65_golden_a_approval_journey as p8_s65
import test_nex_eos_p8_s75f_postgres_rustfs as s75f
import test_nex_platform_p8_s75h_protected_attachment_journey as s75h
import test_nex_wc_p8_s43_human_approval_protected_gate as s43
from fastapi.testclient import TestClient
from nex_ae_api.agent_runtime_worker import (
    LOCAL_SKILL_EXECUTOR,
    AgentRuntimeWorkerConfig,
    AgentRuntimeWorkerError,
    build_agent_runtime_worker_profile,
    validate_agent_runtime_worker_startup,
)
from nex_ae_api.auth_sessions import AUTH_SESSION_MODE_OA, SESSION_COOKIE_NAME
from nex_ae_api.nsl_backend_profiles import NSL_V02_IN_PROCESS_BACKEND
from nex_ae_api.oa_session_client import HttpOaUserSessionClient
from nex_ae_api.voucher_attachment_api import register_voucher_attachment_routes
from nex_ae_api.voucher_attachment_storage import VoucherAttachmentObjectGateway
from nex_eos import create_eos_app
from nex_oa.authorization_service import OA_AUTHORIZATION_READ_SCOPE
from nex_runtime import DEFAULT_USER_SCOPE, SERVICE_SPECS, build_service_app
from nex_runtime.object_storage import (
    ObjectStorageSettings,
    S3ObjectStore,
    build_owner_object_key,
    build_s3_client,
)
from nex_runtime.object_storage_lifecycle import bootstrap_private_bucket
from nex_wc.approvals import (
    ApprovalDecisionAuthorizationError,
    ApprovalDecisionAuthorizer,
    ApprovalDecisionService,
    ApprovalWorkItemService,
    SqlAlchemyApprovalWorkItemRepository,
)
from nex_wc.coordination_clients import HttpAuthorizationSource
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
AE_DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL", "")
WC_DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL", "")
OA_DATABASE_URL = os.getenv("NEX_OA_TEST_DATABASE_URL", "")
EOS_DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
RUSTFS_ENDPOINT = os.getenv("NEX_P8_S84_RUSTFS_ENDPOINT", "")
RUSTFS_ACCESS_KEY = os.getenv("NEX_P8_S84_RUSTFS_ACCESS_KEY", "")
RUSTFS_SECRET_KEY = os.getenv("NEX_P8_S84_RUSTFS_SECRET_KEY", "")
SMOKE_ENABLED = os.getenv("NEX_P8_S84_PROTECTED_SMOKE") == "1"
BUCKET = "nex-ae-p8-s84"
LOCK_PATH = ROOT / "deployment/locks/nsl-v0.2-wheel.json"
WHEEL_DIRECTORY = ROOT / "reports/deployment/p8-nsl-v0.2-wheel"

pytestmark = pytest.mark.skipif(
    not all(
        (
            AE_DATABASE_URL,
            WC_DATABASE_URL,
            OA_DATABASE_URL,
            EOS_DATABASE_URL,
            RUSTFS_ENDPOINT,
            RUSTFS_ACCESS_KEY,
            RUSTFS_SECRET_KEY,
            SMOKE_ENABLED,
        )
    ),
    reason="Protected P8-S84 revocation smoke is disabled",
)


class _ObservedObjectStore:
    def __init__(self, delegate: S3ObjectStore) -> None:
        self._delegate = delegate
        self.head_calls = 0
        self.copy_calls = 0

    def head(self, *args, **kwargs):
        self.head_calls += 1
        return self._delegate.head(*args, **kwargs)

    def copy_to_stream(self, *args, **kwargs):
        self.copy_calls += 1
        return self._delegate.copy_to_stream(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    @property
    def read_observation(self) -> tuple[int, int]:
        return self.head_calls, self.copy_calls


def test_current_trust_and_authority_revocation_fail_closed(
    tmp_path: Path,
) -> None:
    s75h._prepare_databases()
    valid_evidence = nsl_readiness.run_nsl_v02_readiness(
        {nsl_readiness.EXECUTION_ENV: "1"},
        execute=True,
        lock_path=LOCK_PATH,
        wheel_directory=WHEEL_DIRECTORY,
        report_path=tmp_path / "valid-readiness.json",
    )
    assert valid_evidence["status"] == "PASS", valid_evidence
    assert valid_evidence["isolated_install"] is True
    assert valid_evidence["host_environment_mutated"] is False
    tampered_lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    tampered_lock["wheel_sha256"] = "sha256:" + "0" * 64
    tampered_lock_path = tmp_path / "revoked-nsl-v0.2-wheel.json"
    tampered_lock_path.write_text(
        json.dumps(tampered_lock, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    revoked_evidence = nsl_readiness.run_nsl_v02_readiness(
        {nsl_readiness.EXECUTION_ENV: "1"},
        execute=True,
        lock_path=tampered_lock_path,
        wheel_directory=WHEEL_DIRECTORY,
        report_path=tmp_path / "revoked-readiness.json",
    )
    assert revoked_evidence["status"] == "FAIL"
    assert "wheel digest" in revoked_evidence["issues"][0]
    failed_readiness = {
        "schema_version": "nsl_installed_package_readiness.v2",
        "status": "FAIL",
        "failure_code": "ae.agent_runtime_worker.nsl_package_unready",
        "detail": revoked_evidence["issues"][0],
    }
    config = AgentRuntimeWorkerConfig(
        mode="enabled",
        profile=build_agent_runtime_worker_profile(
            worker_id="ae-runtime-worker-p8-s84-protected",
            declared_at="2026-10-24T12:00:00Z",
            supported_backend_profiles=(NSL_V02_IN_PROCESS_BACKEND,),
        ),
    )
    with pytest.raises(AgentRuntimeWorkerError) as package_denied:
        validate_agent_runtime_worker_startup(
            config,
            available_executor_kinds=(LOCAL_SKILL_EXECUTOR,),
            available_backend_profiles=(NSL_V02_IN_PROCESS_BACKEND,),
            in_process_package_readiness=failed_readiness,
        )
    assert package_denied.value.error_code == (
        "ae.agent_runtime_worker.nsl_package_unready"
    )

    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s84-{suffix}"
    owner_id = f"employee-{suffix[:12]}"
    employee_id = f"EMP-P8-S84-{suffix[:10]}"
    batch_id = str(uuid4())
    attachment_id = str(uuid4())
    operation_id = str(uuid4())
    approved_work_item_id = str(uuid4())
    revoked_work_item_id = str(uuid4())
    project_id = str(uuid4())
    nvt_id = str(uuid4())
    debit_id = str(uuid4())
    credit_id = str(uuid4())
    requested_at = datetime.now(UTC).replace(microsecond=0)
    object_key = build_owner_object_key(
        payload_family="voucher-evidence",
        tenant_id=tenant_id,
        subject_id=owner_id,
        content_id=attachment_id,
        suffix="bin",
    )
    settings = ObjectStorageSettings(
        owner="nex-ae-api",
        endpoint_url=RUSTFS_ENDPOINT,
        bucket=BUCKET,
        access_key=RUSTFS_ACCESS_KEY,
        secret_key=RUSTFS_SECRET_KEY,
    )
    object_client = build_s3_client(settings)
    assert bootstrap_private_bucket(object_client, bucket=BUCKET).versioning_enabled
    raw_store = S3ObjectStore(object_client, settings)
    observed_store = _ObservedObjectStore(raw_store)
    ae_engine = create_engine(AE_DATABASE_URL, poolclass=NullPool)
    wc_engine = create_engine(WC_DATABASE_URL, poolclass=NullPool)
    oa_engine = create_engine(OA_DATABASE_URL, poolclass=NullPool)
    eos_engine = create_engine(EOS_DATABASE_URL, poolclass=NullPool)
    oa_server = None
    ae_server = None
    eos_runtime = None
    session_id = None
    try:
        oa_app = s43._build_oa_app(OA_DATABASE_URL)
        s43._seed_identity(
            oa_app,
            tenant_id=tenant_id,
            subject_id=owner_id,
            employee_id=employee_id,
            scopes=[
                DEFAULT_USER_SCOPE,
                "approval:read",
                "approval:decide",
                "finance:voucher-draft:create",
            ],
        )
        oa_server = browser_runtime.start_api_server(
            oa_app, browser_runtime.find_free_port()
        )
        oa_session_client = HttpOaUserSessionClient(
            base_url=oa_server.url,
            service_token=p8_s65._service_token("nex-ae-api", "nex-oa"),
        )
        login = oa_session_client.login_with_credentials(
            {
                "tenant_id": tenant_id,
                "employee_id": employee_id,
                "password": s43.PASSWORD,
                "requested_scopes": [DEFAULT_USER_SCOPE],
                "ttl_seconds": 3600,
            },
            request_id=str(uuid4()),
            trace_id=uuid4().hex,
        )
        session_id = login["session"]["session_id"]

        attachment_repository = s75h._attachment_repository(ae_engine)
        attachment_gateway = VoucherAttachmentObjectGateway(
            observed_store, attachment_repository
        )
        ae_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
        resolver_calls = {"count": 0}

        @ae_app.middleware("http")
        async def observe_resolver(request, call_next):
            if request.url.path == "/internal/v1/voucher-attachments/resolve":
                resolver_calls["count"] += 1
            return await call_next(request)

        register_voucher_attachment_routes(
            ae_app,
            repository=attachment_repository,
            gateway=attachment_gateway,
            oa_session_client=oa_session_client,
            session_mode=AUTH_SESSION_MODE_OA,
        )
        batch_path = f"/api/v1/voucher-attachments/batches/{batch_id}"
        with TestClient(ae_app) as client:
            client.cookies.set(SESSION_COOKIE_NAME, session_id)
            s75h._create_batch(
                client,
                {},
                batch_id=batch_id,
                conversation_id=str(uuid4()),
                interaction_id=str(uuid4()),
            )
            uploaded = client.post(
                f"{batch_path}/items",
                data={"attachment_id": attachment_id},
                files={
                    "file": (
                        "revocation-evidence.pdf",
                        b"p8-s84-protected-evidence",
                        "application/pdf",
                    )
                },
            )
            assert uploaded.status_code == 201, uploaded.text
            assert client.post(f"{batch_path}/finalize").status_code == 200
            locked = client.post(f"{batch_path}/lock")
            assert locked.status_code == 200, locked.text
            manifest = locked.json()
            content = client.get(
                f"{batch_path}/items/{attachment_id}/content"
            )
            assert content.status_code == 200
            assert content.content == b"p8-s84-protected-evidence"
        versions_before = _object_versions(object_client, object_key)
        assert len(versions_before) == 1

        authorization = HttpAuthorizationSource(
            base_url=oa_server.url,
            service_token=p8_s65._service_token(
                "nex-wc", "nex-oa", OA_AUTHORIZATION_READ_SCOPE
            ),
        )
        wc_repository = SqlAlchemyApprovalWorkItemRepository(
            sessionmaker(bind=wc_engine, expire_on_commit=False)
        )
        approved_item = s75f._approval_work_item(
            tenant_id=tenant_id,
            owner_id=owner_id,
            approval_work_item_id=approved_work_item_id,
            operation_id=operation_id,
            manifest_hash=manifest["attachment_manifest_hash"],
            now=requested_at,
        )
        revoked_item = s75f._approval_work_item(
            tenant_id=tenant_id,
            owner_id=owner_id,
            approval_work_item_id=revoked_work_item_id,
            operation_id=str(uuid4()),
            manifest_hash=manifest["attachment_manifest_hash"],
            now=requested_at,
        )
        work_items = ApprovalWorkItemService(wc_repository)
        assert work_items.create_or_get(approved_item)["created"]
        assert work_items.create_or_get(revoked_item)["created"]
        decision_service = ApprovalDecisionService(
            wc_repository,
            authorizer=ApprovalDecisionAuthorizer(authorization),
        )
        approved = decision_service.decide(
            tenant_id=tenant_id,
            approval_work_item_id=approved_work_item_id,
            decision="APPROVE",
            decided_by=owner_id,
            decision_comment="Approval before the P8-S84 revocation boundary.",
        )

        _replace_oa_scopes(
            oa_engine,
            tenant_id=tenant_id,
            subject_id=owner_id,
            scopes=(
                DEFAULT_USER_SCOPE,
                "approval:read",
                "finance:voucher-draft:create",
            ),
        )
        with pytest.raises(ApprovalDecisionAuthorizationError) as approval_denied:
            decision_service.decide(
                tenant_id=tenant_id,
                approval_work_item_id=revoked_work_item_id,
                decision="APPROVE",
                decided_by=owner_id,
            )
        assert approval_denied.value.status_code == 403
        assert _wc_counts(wc_engine, tenant_id) == {
            "wc_approval_work_item": 2,
            "wc_approval_decision": 1,
            "wc_approval_outbox": 1,
        }

        ae_server = browser_runtime.start_api_server(
            ae_app, browser_runtime.find_free_port()
        )
        eos_app = create_eos_app(
            environ={
                "NEX_EOS_SERVICE_ID": "nex-eos",
                "NEX_PROFILE": "test",
                "NEX_VERSION": "2.1.0-p8-s84",
                "NEX_BUILD_SHA": "p8s84protected",
                "NEX_EOS_DATABASE_URL": EOS_DATABASE_URL,
                "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
                "NEX_OA_BASE_URL": oa_server.url,
                "NEX_EOS_TO_OA_SERVICE_TOKEN": p8_s65._service_token(
                    "nex-eos", "nex-oa", OA_AUTHORIZATION_READ_SCOPE
                ),
                "NEX_AE_API_BASE_URL": ae_server.url,
                "NEX_EOS_TO_AE_SERVICE_TOKEN": p8_s65._service_token(
                    "nex-eos", "nex-ae-api"
                ),
            }
        )
        eos_runtime = eos_app.state.eos_database_runtime
        assert eos_runtime is not None
        s75f._seed_eos(
            eos_app,
            tenant_id=tenant_id,
            nvt_id=nvt_id,
            project_id=project_id,
            debit_id=debit_id,
            credit_id=credit_id,
        )
        command = s75f._voucher_command(
            tenant_id=tenant_id,
            owner_id=owner_id,
            operation_id=operation_id,
            project_id=project_id,
            debit_id=debit_id,
            credit_id=credit_id,
            manifest=manifest,
            approval_decision_id=approved["decision"]["decision_id"],
        )
        _replace_oa_scopes(
            oa_engine,
            tenant_id=tenant_id,
            subject_id=owner_id,
            scopes=(DEFAULT_USER_SCOPE, "approval:read"),
        )
        storage_before_denial = observed_store.read_observation
        with TestClient(eos_app) as client:
            denied = client.post(
                "/internal/v1/finance/voucher-drafts",
                json=command,
                headers={
                    "Authorization": "Bearer "
                    + p8_s65._service_token("nex-ae-api", "nex-eos"),
                    "X-NeX-Tenant-Id": tenant_id,
                },
            )
        assert denied.status_code == 403, denied.text
        assert denied.json()["error_code"] == "EOS_AUTHORIZATION_DENIED"
        assert resolver_calls["count"] == 0
        assert observed_store.read_observation == storage_before_denial
        assert _eos_mutation_counts(eos_engine, tenant_id) == {
            "eos_business_operation": 0,
            "eos_idempotency": 0,
            "eos_voucher_draft": 0,
            "eos_voucher_draft_attachment": 0,
            "eos_outbox": 0,
        }

        revoked_session = oa_session_client.revoke_session(
            session_id,
            request_id=str(uuid4()),
            trace_id=uuid4().hex,
        )
        assert revoked_session["revoked"] is True
        storage_before_session_denial = observed_store.read_observation
        with TestClient(ae_app) as client:
            client.cookies.set(SESSION_COOKIE_NAME, session_id)
            content_denied = client.get(
                f"{batch_path}/items/{attachment_id}/content"
            )
        assert content_denied.status_code == 401
        assert content_denied.json()["error_code"] == "ae.oa_session_inactive"
        assert observed_store.read_observation == storage_before_session_denial
        assert _object_versions(object_client, object_key) == versions_before
    finally:
        if ae_server is not None:
            ae_server.stop()
        if oa_server is not None:
            oa_server.stop()
        if eos_runtime is not None:
            eos_runtime.dispose()
        s75f._cleanup(eos_engine, wc_engine, ae_engine, oa_engine, tenant_id)
        assert all(
            count == 0
            for count in s75f._counts(
                ae_engine,
                wc_engine,
                oa_engine,
                eos_engine,
                tenant_id=tenant_id,
            ).values()
        )
        if raw_store.head(object_key) is not None:
            raw_store.delete(object_key)
        assert raw_store.head(object_key) is None
        ae_engine.dispose()
        wc_engine.dispose()
        oa_engine.dispose()
        eos_engine.dispose()


def _replace_oa_scopes(
    engine: Any,
    *,
    tenant_id: str,
    subject_id: str,
    scopes: tuple[str, ...],
) -> None:
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                UPDATE oa_tenant_memberships
                SET scopes = CAST(:scopes AS JSONB),
                    revision = revision + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = :tenant_id
                  AND subject_id = :subject_id
                  AND subject_ref_type = 'oa.user'
                  AND status = 'ACTIVE'
                """
            ),
            {
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "scopes": json.dumps(sorted(scopes)),
            },
        )
    assert result.rowcount == 1


def _wc_counts(engine: Any, tenant_id: str) -> dict[str, int]:
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


def _eos_mutation_counts(engine: Any, tenant_id: str) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: int(
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table in (
                "eos_business_operation",
                "eos_idempotency",
                "eos_voucher_draft",
                "eos_voucher_draft_attachment",
                "eos_outbox",
            )
        }


def _object_versions(client: Any, object_key: str) -> tuple[tuple[Any, ...], ...]:
    response = client.list_object_versions(Bucket=BUCKET, Prefix=object_key)
    return tuple(
        sorted(
            (
                item.get("VersionId"),
                item.get("IsLatest"),
                item.get("Size"),
                item.get("ETag"),
            )
            for item in response.get("Versions", ())
            if item.get("Key") == object_key
        )
    )
