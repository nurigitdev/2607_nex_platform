from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest
import run_ae_web_credential_login_playwright_postgres_smoke as browser_runtime
import run_p8_s65_golden_a_approval_journey as p8_s65
import test_nex_eos_p8_s75f_postgres_rustfs as s75f
import test_nex_platform_p8_s75h_protected_attachment_journey as s75h
from fastapi.testclient import TestClient
from nex_ae_api.voucher_attachment_storage import VoucherAttachmentObjectGateway
from nex_eos import (
    AccountInput,
    EosOutboxPublishReceipt,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosOutboxPublisher,
    create_eos_app,
)
from nex_oa.authorization_service import OA_AUTHORIZATION_READ_SCOPE
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
from p8_reliability_faults import EosOutboxAckLossFaultTransport
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

AE_DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL", "")
WC_DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL", "")
OA_DATABASE_URL = os.getenv("NEX_OA_TEST_DATABASE_URL", "")
EOS_DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
RUSTFS_ENDPOINT = os.getenv("NEX_P8_S80_RUSTFS_ENDPOINT", "")
RUSTFS_ACCESS_KEY = os.getenv("NEX_P8_S80_RUSTFS_ACCESS_KEY", "")
RUSTFS_SECRET_KEY = os.getenv("NEX_P8_S80_RUSTFS_SECRET_KEY", "")
SMOKE_ENABLED = os.getenv("NEX_P8_S80_PROTECTED_SMOKE") == "1"
BUCKET = "nex-ae-p8-s80"

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
    reason="Protected P8-S80 outbox ACK-loss smoke is disabled",
)


class _IdempotentEventSink:
    def __init__(self) -> None:
        self.attempts = 0
        self.events: dict[str, object] = {}

    def publish(self, event: Any) -> EosOutboxPublishReceipt:
        self.attempts += 1
        self.events.setdefault(event.event_id, event)
        return EosOutboxPublishReceipt(
            event_id=event.event_id,
            event_payload_hash=event.event_payload_hash,
            receipt_ref=f"p8-s80-sink:{event.event_id}",
        )


def test_outbox_ack_loss_retries_publication_only_with_actual_state() -> None:
    s75h._prepare_databases()
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s80-{suffix}"
    owner_id = f"employee-{suffix[:12]}"
    batch_id = str(uuid4())
    operation_id = str(uuid4())
    approval_work_item_id = str(uuid4())
    project_id = str(uuid4())
    nvt_id = str(uuid4())
    debit_id = str(uuid4())
    credit_id = str(uuid4())
    attachment_specs = (
        (str(uuid4()), "taxi.png", "image/png", b"p8-s80-image"),
        (str(uuid4()), "statement.pdf", "application/pdf", b"p8-s80-pdf"),
        (str(uuid4()), "evidence.zip", "application/zip", b"p8-s80-zip"),
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
    store = S3ObjectStore(object_client, settings)
    object_keys = tuple(
        build_owner_object_key(
            payload_family="voucher-evidence",
            tenant_id=tenant_id,
            subject_id=owner_id,
            content_id=attachment_id,
            suffix="bin",
        )
        for attachment_id, _name, _media_type, _payload in attachment_specs
    )
    ae_engine = create_engine(AE_DATABASE_URL, poolclass=NullPool)
    wc_engine = create_engine(WC_DATABASE_URL, poolclass=NullPool)
    oa_engine = create_engine(OA_DATABASE_URL, poolclass=NullPool)
    eos_engine = create_engine(EOS_DATABASE_URL, poolclass=NullPool)
    ae_server = None
    oa_server = None
    eos_runtime = None
    try:
        repository = s75h._attachment_repository(ae_engine)
        gateway = VoucherAttachmentObjectGateway(store, repository)
        ae_app = s75h._attachment_app(repository, gateway)
        owner_headers = s75h._owner_headers(tenant_id, owner_id)
        batch_path = f"/api/v1/voucher-attachments/batches/{batch_id}"
        with TestClient(ae_app) as client:
            s75h._create_batch(
                client,
                owner_headers,
                batch_id=batch_id,
                conversation_id=str(uuid4()),
                interaction_id=str(uuid4()),
            )
            for attachment_id, name, media_type, content in attachment_specs:
                uploaded = client.post(
                    f"{batch_path}/items",
                    headers=owner_headers,
                    data={"attachment_id": attachment_id},
                    files={"file": (name, content, media_type)},
                )
                assert uploaded.status_code == 201, uploaded.text
            assert client.post(
                f"{batch_path}/finalize", headers=owner_headers
            ).status_code == 200
            locked = client.post(f"{batch_path}/lock", headers=owner_headers)
            assert locked.status_code == 200, locked.text
            manifest = locked.json()
        versions_before = {
            key: _object_versions(object_client, key) for key in object_keys
        }
        assert all(len(versions) == 1 for versions in versions_before.values())

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
        wc_repository = SqlAlchemyApprovalWorkItemRepository(
            sessionmaker(bind=wc_engine, expire_on_commit=False)
        )
        approval = s75f._approval_work_item(
            tenant_id=tenant_id,
            owner_id=owner_id,
            approval_work_item_id=approval_work_item_id,
            operation_id=operation_id,
            manifest_hash=manifest["attachment_manifest_hash"],
            now=datetime.now(UTC),
        )
        assert ApprovalWorkItemService(wc_repository).create_or_get(approval)["created"]
        decision = ApprovalDecisionService(
            wc_repository,
            authorizer=ApprovalDecisionAuthorizer(
                HttpAuthorizationSource(
                    base_url=oa_server.url,
                    service_token=p8_s65._service_token(
                        "nex-wc", "nex-oa", OA_AUTHORIZATION_READ_SCOPE
                    ),
                )
            ),
        ).decide(
            tenant_id=tenant_id,
            approval_work_item_id=approval_work_item_id,
            decision="APPROVE",
            decided_by=owner_id,
            decision_comment="Approve P8-S80 outbox ACK-loss evidence.",
        )

        ae_server = browser_runtime.start_api_server(
            ae_app, browser_runtime.find_free_port()
        )
        eos_app = create_eos_app(
            environ={
                "NEX_EOS_SERVICE_ID": "nex-eos",
                "NEX_PROFILE": "test",
                "NEX_VERSION": "2.1.0-p8-s80",
                "NEX_BUILD_SHA": "p8s80protected",
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
        _seed_eos(
            eos_app,
            tenant_id=tenant_id,
            nvt_id=nvt_id,
            project_id=project_id,
            debit_id=debit_id,
            credit_id=credit_id,
        )
        command = s75h._voucher_command(
            tenant_id=tenant_id,
            owner_id=owner_id,
            operation_id=operation_id,
            project_id=project_id,
            debit_id=debit_id,
            credit_id=credit_id,
            manifest=manifest,
            approval_decision_id=decision["decision"]["decision_id"],
        )
        command["idempotency_key"] = "idem:sha256:" + "8" * 64
        headers = {
            "Authorization": "Bearer "
            + p8_s65._service_token("nex-ae-api", "nex-eos"),
            "X-NeX-Tenant-Id": tenant_id,
        }
        with TestClient(eos_app) as client:
            created = client.post(
                "/internal/v1/finance/voucher-drafts",
                json=command,
                headers=headers,
            )
        assert created.status_code == 201, created.text

        sink = _IdempotentEventSink()
        fault = EosOutboxAckLossFaultTransport(sink)
        publisher = SqlAlchemyEosOutboxPublisher(eos_runtime.session_factory)
        lost = publisher.publish_next(fault, tenant_id=tenant_id)
        assert lost is not None
        assert (lost.delivery_state, lost.attempt_count, lost.retry_required) == (
            "PENDING",
            1,
            True,
        )
        published = publisher.publish_next(fault, tenant_id=tenant_id)
        assert published is not None
        assert (
            published.delivery_state,
            published.attempt_count,
            published.retry_required,
        ) == ("PUBLISHED", 2, False)
        assert published.event_id == lost.event_id
        assert published.event_payload_hash == lost.event_payload_hash
        assert publisher.publish_next(fault, tenant_id=tenant_id) is None
        assert fault.evidence.publication_attempts == 2
        assert fault.evidence.downstream_acceptances == 2
        assert fault.evidence.acknowledged_attempts == 1
        assert fault.evidence.unique_event_count == 1
        assert sink.attempts == 2
        assert tuple(sink.events) == (published.event_id,)

        assert s75h._journey_counts(
            ae_engine, wc_engine, eos_engine, tenant_id=tenant_id
        ) == {
            "ae_voucher_attach_batch": 1,
            "ae_voucher_attachment": 3,
            "wc_approval_work_item": 1,
            "wc_approval_decision": 1,
            "eos_voucher_draft": 1,
            "eos_voucher_draft_attachment": 3,
            "eos_business_operation": 1,
        }
        with eos_engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT business_operation_id, delivery_state, attempt_count "
                    "FROM eos_outbox WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).one()
        assert (str(row[0]), row[1], row[2]) == (operation_id, "PUBLISHED", 2)
        assert {
            key: _object_versions(object_client, key) for key in object_keys
        } == versions_before
        persisted = repository.get_batch(
            tenant_id=tenant_id, attachment_batch_id=batch_id
        )
        assert persisted is not None
        assert persisted["attachment_manifest_hash"] == manifest[
            "attachment_manifest_hash"
        ]
    finally:
        if ae_server is not None:
            ae_server.stop()
        if oa_server is not None:
            oa_server.stop()
        if eos_runtime is not None:
            eos_runtime.dispose()
        s75f._cleanup(eos_engine, wc_engine, ae_engine, oa_engine, tenant_id)
        assert all(
            value == 0
            for value in s75f._counts(
                ae_engine,
                wc_engine,
                oa_engine,
                eos_engine,
                tenant_id=tenant_id,
            ).values()
        )
        for object_key in object_keys:
            if store.head(object_key) is not None:
                store.delete(object_key)
            assert store.head(object_key) is None
        ae_engine.dispose()
        wc_engine.dispose()
        oa_engine.dispose()
        eos_engine.dispose()


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
        NvtProjectInput(tenant_id, nvt_id, "NVT-80", "P8-S80 NVT")
    )
    app.state.eos_projects.create_project(
        ProjectInput(
            tenant_id,
            project_id,
            "PROJECT-80",
            "P8-S80 Project",
            nvt_project_id=nvt_id,
        )
    )
    for account_id, code, category in (
        (debit_id, "TRAVEL-80", "EXPENSE"),
        (credit_id, "CASH-80", "ASSET"),
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


def _object_versions(
    client: Any,
    object_key: str,
) -> tuple[tuple[Any, ...], ...]:
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
