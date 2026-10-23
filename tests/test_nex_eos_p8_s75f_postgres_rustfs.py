from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from typing import Any
from uuid import uuid4

import pytest
import run_ae_web_credential_login_playwright_postgres_smoke as browser_runtime
import run_p8_s65_golden_a_approval_journey as p8_s65
from fastapi.testclient import TestClient
from nex_ae_api.voucher_attachment_api import register_voucher_attachment_routes
from nex_ae_api.voucher_attachment_storage import VoucherAttachmentObjectGateway
from nex_ae_api.voucher_attachments import (
    ATTACHMENT_BATCH_SCHEMA_VERSION,
    SqlAlchemyVoucherAttachmentRepository,
)
from nex_eos import (
    AccountInput,
    NvtProjectInput,
    ProjectInput,
    create_eos_app,
    voucher_payload_hash,
)
from nex_oa.authorization_service import OA_AUTHORIZATION_READ_SCOPE
from nex_runtime import SERVICE_SPECS, build_service_app
from nex_runtime.object_storage import (
    ObjectStorageSettings,
    S3ObjectStore,
    build_owner_object_key,
    build_s3_client,
)
from nex_runtime.object_storage_lifecycle import bootstrap_private_bucket
from nex_wc.approvals import (
    ApprovalDecisionAuthorizer,
    ApprovalDecisionService,
    ApprovalWorkItemService,
    SqlAlchemyApprovalWorkItemRepository,
)
from nex_wc.coordination_clients import HttpAuthorizationSource
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

AE_DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL", "")
WC_DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL", "")
OA_DATABASE_URL = os.getenv("NEX_OA_TEST_DATABASE_URL", "")
EOS_DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
RUSTFS_ENDPOINT = os.getenv("NEX_AE_P8_S75F_RUSTFS_ENDPOINT", "")
RUSTFS_ACCESS_KEY = os.getenv("NEX_AE_P8_S75F_RUSTFS_ACCESS_KEY", "")
RUSTFS_SECRET_KEY = os.getenv("NEX_AE_P8_S75F_RUSTFS_SECRET_KEY", "")
SMOKE_ENABLED = os.getenv("NEX_P8_S75F_PROTECTED_SMOKE") == "1"
BUCKET = "nex-ae-p8-s75f"

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
    reason="Protected P8-S75F AE/WC/OA/EOS PostgreSQL and RustFS smoke is disabled",
)


def test_exact_approved_manifest_commits_once_across_actual_services() -> None:
    _prepare_databases()
    _assert_database_targets()
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s75f-{suffix}"
    owner_id = f"employee-{suffix[:12]}"
    batch_id = str(uuid4())
    attachment_id = str(uuid4())
    conversation_id = str(uuid4())
    interaction_id = str(uuid4())
    approval_work_item_id = str(uuid4())
    operation_id = str(uuid4())
    project_id = str(uuid4())
    nvt_id = str(uuid4())
    debit_id = str(uuid4())
    credit_id = str(uuid4())
    payload = b"P8-S75F actual RustFS receipt evidence"
    now = datetime.now(UTC)

    settings = ObjectStorageSettings(
        owner="nex-ae-api",
        endpoint_url=RUSTFS_ENDPOINT,
        bucket=BUCKET,
        access_key=RUSTFS_ACCESS_KEY,
        secret_key=RUSTFS_SECRET_KEY,
    )
    object_client = build_s3_client(settings)
    assert bootstrap_private_bucket(object_client, bucket=BUCKET).versioning_enabled
    store = S3ObjectStore(object_client, settings)
    object_key = build_owner_object_key(
        payload_family="voucher-evidence",
        tenant_id=tenant_id,
        subject_id=owner_id,
        content_id=attachment_id,
        suffix="bin",
    )

    ae_engine = create_engine(AE_DATABASE_URL, poolclass=NullPool)
    wc_engine = create_engine(WC_DATABASE_URL, poolclass=NullPool)
    oa_engine = create_engine(OA_DATABASE_URL, poolclass=NullPool)
    eos_engine = create_engine(EOS_DATABASE_URL, poolclass=NullPool)
    ae_repository = SqlAlchemyVoucherAttachmentRepository(
        sessionmaker(bind=ae_engine, expire_on_commit=False)
    )
    gateway = VoucherAttachmentObjectGateway(store, ae_repository)
    ae_server = None
    oa_server = None
    eos_runtime = None
    decision: dict[str, Any] | None = None
    try:
        ae_repository.create_batch(
            {
                "schema_version": ATTACHMENT_BATCH_SCHEMA_VERSION,
                "tenant_id": tenant_id,
                "attachment_batch_id": batch_id,
                "owner_subject_ref": {"type": "oa.user", "id": owner_id},
                "conversation_id": conversation_id,
                "interaction_id": interaction_id,
                "trace": {
                    "trace_id": f"trace-{suffix}",
                    "correlation_id": f"correlation-{suffix}",
                    "causation_id": interaction_id,
                },
            }
        )
        ae_repository.register_item(
            {
                "tenant_id": tenant_id,
                "attachment_batch_id": batch_id,
                "attachment_id": attachment_id,
                "display_name": "receipt.pdf",
                "media_type": "application/pdf",
                "size_bytes": len(payload),
            }
        )
        resolved = gateway.publish(
            tenant_id=tenant_id,
            attachment_batch_id=batch_id,
            attachment_id=attachment_id,
            source=BytesIO(payload),
        )
        ae_repository.finalize_batch(
            tenant_id=tenant_id,
            attachment_batch_id=batch_id,
        )
        manifest = ae_repository.lock_manifest(
            tenant_id=tenant_id,
            attachment_batch_id=batch_id,
        )
        assert manifest["items"][0]["object_ref"] == resolved["object_ref"]
        assert store.head(object_key) is not None

        oa_app = p8_s65._build_oa_app(OA_DATABASE_URL)
        p8_s65._seed_identity(
            oa_app,
            tenant_id=tenant_id,
            subject_id=owner_id,
            roles=["employee"],
            scopes=["approval:decide", "finance:voucher-draft:create"],
        )
        oa_server = browser_runtime.start_api_server(
            oa_app, browser_runtime.find_free_port()
        )

        wc_factory = sessionmaker(bind=wc_engine, expire_on_commit=False)
        wc_repository = SqlAlchemyApprovalWorkItemRepository(wc_factory)
        approval = _approval_work_item(
            tenant_id=tenant_id,
            owner_id=owner_id,
            approval_work_item_id=approval_work_item_id,
            operation_id=operation_id,
            manifest_hash=manifest["attachment_manifest_hash"],
            now=now,
        )
        assert ApprovalWorkItemService(wc_repository).create_or_get(approval)["created"]
        authorization = HttpAuthorizationSource(
            base_url=oa_server.url,
            service_token=p8_s65._service_token(
                "nex-wc", "nex-oa", OA_AUTHORIZATION_READ_SCOPE
            ),
        )
        decision = ApprovalDecisionService(
            wc_repository,
            authorizer=ApprovalDecisionAuthorizer(authorization),
        ).decide(
            tenant_id=tenant_id,
            approval_work_item_id=approval_work_item_id,
            decision="APPROVE",
            decided_by=owner_id,
            decision_comment="Approve the exact locked attachment manifest.",
        )
        assert decision["decision"]["authorized_by_oa"] is True

        ae_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
        register_voucher_attachment_routes(
            ae_app,
            repository=ae_repository,
            gateway=gateway,
        )
        ae_server = browser_runtime.start_api_server(
            ae_app, browser_runtime.find_free_port()
        )
        eos_to_oa = p8_s65._service_token(
            "nex-eos", "nex-oa", OA_AUTHORIZATION_READ_SCOPE
        )
        eos_to_ae = p8_s65._service_token("nex-eos", "nex-ae-api")
        ae_to_eos = p8_s65._service_token("nex-ae-api", "nex-eos")
        eos_app = create_eos_app(
            environ={
                "NEX_EOS_SERVICE_ID": "nex-eos",
                "NEX_PROFILE": "test",
                "NEX_VERSION": "2.1.0-p8-s75f",
                "NEX_BUILD_SHA": "p8s75fprotected",
                "NEX_EOS_DATABASE_URL": EOS_DATABASE_URL,
                "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
                "NEX_OA_BASE_URL": oa_server.url,
                "NEX_EOS_TO_OA_SERVICE_TOKEN": eos_to_oa,
                "NEX_AE_API_BASE_URL": ae_server.url,
                "NEX_EOS_TO_AE_SERVICE_TOKEN": eos_to_ae,
            }
        )
        eos_runtime = eos_app.state.eos_database_runtime
        assert eos_runtime is not None
        _seed_eos(
            eos_app,
            tenant_id=tenant_id,
            nvt_id=nvt_id,
            project_id=project_id,
            debit_id=debit_id,
            credit_id=credit_id,
        )
        command = _voucher_command(
            tenant_id=tenant_id,
            owner_id=owner_id,
            operation_id=operation_id,
            project_id=project_id,
            debit_id=debit_id,
            credit_id=credit_id,
            manifest=manifest,
            approval_decision_id=decision["decision"]["decision_id"],
        )
        headers = {
            "Authorization": f"Bearer {ae_to_eos}",
            "X-NeX-Tenant-Id": tenant_id,
        }
        with TestClient(eos_app) as client:
            created = client.post(
                "/internal/v1/finance/voucher-drafts",
                json=command,
                headers=headers,
            )
            replayed = client.post(
                "/internal/v1/finance/voucher-drafts",
                json=command,
                headers=headers,
            )
            assert created.status_code == 201, created.text
            assert replayed.status_code == 200, replayed.text
            assert replayed.json()["idempotency_disposition"] == "REPLAYED"
            voucher_id = created.json()["voucher_ref"]["id"]
            verified = client.get(
                f"/internal/v1/finance/voucher-drafts/{voucher_id}/verification",
                params={"business_operation_id": operation_id},
                headers=headers,
            )
            assert verified.status_code == 200, verified.text
            assert verified.json()["attachment_batch_id"] == batch_id
            assert (
                verified.json()["attachment_manifest_hash"]
                == manifest["attachment_manifest_hash"]
            )
            assert verified.json()["attachment_ids"] == [attachment_id]

            substituted = {
                **command,
                "business_operation_id": str(uuid4()),
                "idempotency_key": f"p8-s75f-substitution-{suffix}",
                "attachment_manifest_hash": "sha256:" + "0" * 64,
            }
            substituted["payload_hash"] = voucher_payload_hash(substituted)
            rejected = client.post(
                "/internal/v1/finance/voucher-drafts",
                json=substituted,
                headers=headers,
            )
            assert rejected.status_code == 422, rejected.text
            assert rejected.json()["error_code"] == "EOS_ATTACHMENT_OBJECT_REJECTED"

        assert _counts(
            ae_engine,
            wc_engine,
            oa_engine,
            eos_engine,
            tenant_id=tenant_id,
        ) == {
            "ae_voucher_attach_batch": 1,
            "ae_voucher_attachment": 1,
            "wc_approval_work_item": 1,
            "wc_approval_decision": 1,
            "wc_approval_outbox": 1,
            "oa_tenant_memberships": 1,
            "eos_voucher_draft": 1,
            "eos_voucher_draft_attachment": 1,
            "eos_business_operation": 1,
        }
    finally:
        if ae_server is not None:
            ae_server.stop()
        if oa_server is not None:
            oa_server.stop()
        if eos_runtime is not None:
            eos_runtime.dispose()
        _cleanup(eos_engine, wc_engine, ae_engine, oa_engine, tenant_id)
        assert all(
            value == 0
            for value in _counts(
                ae_engine,
                wc_engine,
                oa_engine,
                eos_engine,
                tenant_id=tenant_id,
            ).values()
        )
        if store.head(object_key) is not None:
            store.delete(object_key)
        assert store.head(object_key) is None
        ae_engine.dispose()
        wc_engine.dispose()
        oa_engine.dispose()
        eos_engine.dispose()
    assert decision is not None


def _prepare_databases() -> None:
    for service_id, database_url in (
        ("nex-ae-api", AE_DATABASE_URL),
        ("nex-wc", WC_DATABASE_URL),
        ("nex-oa", OA_DATABASE_URL),
        ("nex-eos", EOS_DATABASE_URL),
    ):
        run_service_migrations(service_id, database_url=database_url, profile="test")


def _assert_database_targets() -> None:
    expected = (
        (AE_DATABASE_URL, "nex_ae_user", "nex_ae_test"),
        (WC_DATABASE_URL, "nex_wc_user", "nex_wc_test"),
        (OA_DATABASE_URL, "nex_oa_user", "nex_oa_test"),
        (EOS_DATABASE_URL, "nex_eos_user", "nex_eos_test"),
    )
    for database_url, user, database in expected:
        target = make_url(database_url)
        assert target.username == user
        assert target.database == database
        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with engine.connect() as connection:
                assert tuple(
                    connection.execute(
                        text("SELECT current_database(), current_user")
                    ).one()
                ) == (database, user)
        finally:
            engine.dispose()


def _approval_work_item(
    *,
    tenant_id: str,
    owner_id: str,
    approval_work_item_id: str,
    operation_id: str,
    manifest_hash: str,
    now: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": tenant_id,
        "approval_work_item_id": approval_work_item_id,
        "approval_domain": "NSL_WRITE",
        "source_ref": f"approval-request-{approval_work_item_id}",
        "semantic_hash": manifest_hash,
        "title": "Approve Voucher evidence manifest",
        "display_safe_summary": "Approve one immutable receipt for Voucher commit.",
        "approval_provider_type": "NSL",
        "approval_target_ref": f"attachment-manifest-{approval_work_item_id}",
        "target_approver_ref": owner_id,
        "target_role_ref": None,
        "target_org_scope_ref": None,
        "target_project_scope_ref": None,
        "agent_execution_id": f"agent-execution-{approval_work_item_id}",
        "executable_step_id": f"step-{approval_work_item_id}",
        "nsl_execution_id": f"nsl-execution-{approval_work_item_id}",
        "business_operation_id": operation_id,
        "approval_request_id": f"approval-request-{approval_work_item_id}",
        "protected_request_ref": f"ae-private:{approval_work_item_id}",
        "resume_target_ref": f"ae-wait:{approval_work_item_id}",
        "state": "PENDING",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "version": 1,
    }


def _seed_eos(
    app: Any,
    *,
    tenant_id: str,
    nvt_id: str,
    project_id: str,
    debit_id: str,
    credit_id: str,
) -> None:
    app.state.eos_projects.create_nvt_project(
        NvtProjectInput(tenant_id, nvt_id, "NVT-75F", "P8-S75F NVT")
    )
    app.state.eos_projects.create_project(
        ProjectInput(
            tenant_id,
            project_id,
            "PROJECT-75F",
            "P8-S75F Project",
            nvt_project_id=nvt_id,
        )
    )
    for account_id, code, category in (
        (debit_id, "TRAVEL-75F", "EXPENSE"),
        (credit_id, "CASH-75F", "ASSET"),
    ):
        app.state.eos_accounts.create_account(
            AccountInput(
                tenant_id,
                account_id,
                code,
                code,
                category,
                "GENERAL",
                date(2026, 1, 1),
            )
        )


def _voucher_command(
    *,
    tenant_id: str,
    owner_id: str,
    operation_id: str,
    project_id: str,
    debit_id: str,
    credit_id: str,
    manifest: dict[str, Any],
    approval_decision_id: str,
) -> dict[str, Any]:
    evidence_ref = f"wc-decision:{approval_decision_id}"
    item = manifest["items"][0]
    value: dict[str, Any] = {
        "schema_version": "eos_create_voucher_draft_command.v1",
        "tenant_id": tenant_id,
        "business_operation_id": operation_id,
        "idempotency_key": f"p8-s75f-{operation_id}",
        "payload_hash": "sha256:" + "0" * 64,
        "requester_ref": {"type": "oa.user", "id": owner_id},
        "project_ref": {"type": "eos.project", "id": project_id},
        "voucher_type": "GENERAL",
        "transaction_date": "2026-10-23",
        "currency": "KRW",
        "description": "P8-S75F attachment-bearing Voucher",
        "lines": [
            {
                "line_no": 1,
                "account_ref": {"type": "eos.account", "id": debit_id},
                "signed_amount": "12000.00",
                "economic_category": "TRAVEL",
                "description": "Receipt",
                "evidence_refs": [evidence_ref],
            },
            {
                "line_no": 2,
                "account_ref": {"type": "eos.account", "id": credit_id},
                "signed_amount": "-12000.00",
                "economic_category": "CASH",
                "description": "Offset",
                "evidence_refs": [evidence_ref],
            },
        ],
        "nsl_approval_request_id": approval_decision_id,
        "nsl_approval_evidence_ref": evidence_ref,
        "business_approval_proof_ref": None,
        "attachment_batch_id": manifest["attachment_batch_id"],
        "attachment_manifest_hash": manifest["attachment_manifest_hash"],
        "attachments": [
            {
                "attachment_id": item["attachment_id"],
                "object_ref": item["object_ref"],
                "display_name": item["display_name"],
                "media_type": item["media_type"],
                "size_bytes": item["size_bytes"],
                "content_sha256": item["content_sha256"],
                "evidence_ref": evidence_ref,
            }
        ],
        "trace": {
            "trace_id": f"trace-{operation_id}",
            "correlation_id": f"correlation-{operation_id}",
            "causation_id": f"approval-{approval_decision_id}",
        },
    }
    value["payload_hash"] = voucher_payload_hash(value)
    return value


def _counts(*engines: Any, tenant_id: str) -> dict[str, int]:
    ae_engine, wc_engine, oa_engine, eos_engine = engines
    result: dict[str, int] = {}
    for engine, tables in (
        (ae_engine, ("ae_voucher_attach_batch", "ae_voucher_attachment")),
        (
            wc_engine,
            ("wc_approval_work_item", "wc_approval_decision", "wc_approval_outbox"),
        ),
        (oa_engine, ("oa_tenant_memberships",)),
        (
            eos_engine,
            (
                "eos_voucher_draft",
                "eos_voucher_draft_attachment",
                "eos_business_operation",
            ),
        ),
    ):
        with engine.connect() as connection:
            for table_name in tables:
                result[table_name] = int(
                    connection.execute(
                        text(
                            f"SELECT count(*) FROM {table_name} "
                            "WHERE tenant_id = :tenant_id"
                        ),
                        {"tenant_id": tenant_id},
                    ).scalar_one()
                )
    return result


def _cleanup(
    eos_engine: Any,
    wc_engine: Any,
    ae_engine: Any,
    oa_engine: Any,
    tenant_id: str,
) -> None:
    table_groups = (
        (
            eos_engine,
            (
                "eos_voucher_draft_attachment",
                "eos_voucher_draft_line",
                "eos_voucher_draft",
                "eos_outbox",
                "eos_idempotency",
                "eos_business_operation",
                "eos_account",
                "eos_project",
                "eos_nvt_project",
            ),
        ),
        (
            wc_engine,
            ("wc_approval_outbox", "wc_approval_decision", "wc_approval_work_item"),
        ),
        (ae_engine, ("ae_voucher_attach_batch",)),
        (
            oa_engine,
            (
                "oa_user_sessions",
                "oa_local_credentials",
                "oa_tenant_memberships",
                "oa_subjects",
                "oa_tenants",
            ),
        ),
    )
    for engine, tables in table_groups:
        with engine.begin() as connection:
            for table_name in tables:
                connection.execute(
                    text(f"DELETE FROM {table_name} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                )
