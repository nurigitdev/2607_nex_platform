from __future__ import annotations

import os
from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest
import run_ae_web_credential_login_playwright_postgres_smoke as browser_runtime
import run_p8_s65_golden_a_approval_journey as p8_s65
import test_nex_eos_p8_s75f_postgres_rustfs as s75f
from fastapi.testclient import TestClient
from nex_ae_api.voucher_attachment_api import register_voucher_attachment_routes
from nex_ae_api.voucher_attachment_storage import VoucherAttachmentObjectGateway
from nex_ae_api.voucher_attachments import SqlAlchemyVoucherAttachmentRepository
from nex_eos import (
    AccountInput,
    NvtProjectInput,
    ProjectInput,
    create_eos_app,
    voucher_payload_hash,
)
from nex_oa.authorization_service import OA_AUTHORIZATION_READ_SCOPE
from nex_runtime import (
    DEFAULT_USER_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_user_token,
)
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
RUSTFS_ENDPOINT = os.getenv("NEX_P8_S75H_RUSTFS_ENDPOINT", "")
RUSTFS_ACCESS_KEY = os.getenv("NEX_P8_S75H_RUSTFS_ACCESS_KEY", "")
RUSTFS_SECRET_KEY = os.getenv("NEX_P8_S75H_RUSTFS_SECRET_KEY", "")
SMOKE_ENABLED = os.getenv("NEX_P8_S75H_PROTECTED_SMOKE") == "1"
BUCKET = "nex-ae-p8-s75h"

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
    reason="Protected P8-S75H attachment journey is disabled",
)


def test_authenticated_attachment_approval_and_voucher_journey_is_restart_safe() -> None:
    _prepare_databases()
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s75h-{suffix}"
    other_tenant_id = f"tenant-p8-s75h-other-{suffix}"
    owner_id = f"employee-{suffix[:12]}"
    other_owner_id = f"employee-other-{suffix[:8]}"
    batch_id = str(uuid4())
    partial_batch_id = str(uuid4())
    other_batch_id = str(uuid4())
    conversation_id = str(uuid4())
    interaction_id = str(uuid4())
    operation_id = str(uuid4())
    approval_work_item_id = str(uuid4())
    project_id = str(uuid4())
    nvt_id = str(uuid4())
    debit_id = str(uuid4())
    credit_id = str(uuid4())
    attachment_specs = (
        (str(uuid4()), "taxi-receipt.png", "image/png", b"p8-s75h-image"),
        (str(uuid4()), "expense-statement.pdf", "application/pdf", b"p8-s75h-pdf"),
        (
            str(uuid4()),
            "supporting-evidence.zip",
            "application/zip",
            b"p8-s75h-opaque-zip",
        ),
    )
    partial_attachment_id = str(uuid4())
    other_attachment_id = str(uuid4())
    other_payload = b"p8-s75h-cross-tenant"
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
    object_keys = [
        build_owner_object_key(
            payload_family="voucher-evidence",
            tenant_id=tenant_id,
            subject_id=owner_id,
            content_id=attachment_id,
            suffix="bin",
        )
        for attachment_id, _name, _media_type, _payload in attachment_specs
    ]
    other_object_key = build_owner_object_key(
        payload_family="voucher-evidence",
        tenant_id=other_tenant_id,
        subject_id=other_owner_id,
        content_id=other_attachment_id,
        suffix="bin",
    )
    ae_engine = create_engine(AE_DATABASE_URL, poolclass=NullPool)
    wc_engine = create_engine(WC_DATABASE_URL, poolclass=NullPool)
    oa_engine = create_engine(OA_DATABASE_URL, poolclass=NullPool)
    eos_engine = create_engine(EOS_DATABASE_URL, poolclass=NullPool)
    ae_server = None
    oa_server = None
    eos_runtime = None
    try:
        first_repository = _attachment_repository(ae_engine)
        first_gateway = VoucherAttachmentObjectGateway(store, first_repository)
        first_app = _attachment_app(first_repository, first_gateway)
        owner_headers = _owner_headers(tenant_id, owner_id)
        batch_path = f"/api/v1/voucher-attachments/batches/{batch_id}"
        with TestClient(first_app) as client:
            _create_batch(
                client,
                owner_headers,
                batch_id=batch_id,
                conversation_id=conversation_id,
                interaction_id=interaction_id,
            )
            for index, (attachment_id, name, media_type, payload) in enumerate(
                attachment_specs
            ):
                uploaded = client.post(
                    f"{batch_path}/items",
                    headers=owner_headers,
                    data={"attachment_id": attachment_id},
                    files={"file": (name, payload, media_type)},
                )
                assert uploaded.status_code == 201, uploaded.text
                if index == 0:
                    replayed = client.post(
                        f"{batch_path}/items",
                        headers=owner_headers,
                        data={"attachment_id": attachment_id},
                        files={"file": (name, payload, media_type)},
                    )
                    assert replayed.status_code == 200, replayed.text

            _create_batch(
                client,
                owner_headers,
                batch_id=partial_batch_id,
                conversation_id=conversation_id,
                interaction_id=str(uuid4()),
            )
            first_repository.register_item(
                {
                    "tenant_id": tenant_id,
                    "attachment_batch_id": partial_batch_id,
                    "attachment_id": partial_attachment_id,
                    "display_name": "partial.pdf",
                    "media_type": "application/pdf",
                    "size_bytes": 7,
                }
            )

        # Rebuild every AE runtime adapter from durable PostgreSQL and RustFS state.
        ae_engine.dispose()
        ae_engine = create_engine(AE_DATABASE_URL, poolclass=NullPool)
        store = S3ObjectStore(build_s3_client(settings), settings)
        repository = _attachment_repository(ae_engine)
        gateway = VoucherAttachmentObjectGateway(store, repository)
        ae_app = _attachment_app(repository, gateway)
        other_headers = _owner_headers(other_tenant_id, other_owner_id)
        other_batch_path = (
            f"/api/v1/voucher-attachments/batches/{other_batch_id}"
        )
        with TestClient(ae_app) as client:
            restored = client.get(batch_path, headers=owner_headers)
            assert restored.status_code == 200, restored.text
            assert restored.json()["attachment_count"] == 3
            assert restored.json()["state"] == "UPLOADING"

            partial = client.post(
                f"/api/v1/voucher-attachments/batches/{partial_batch_id}/finalize",
                headers=owner_headers,
            )
            assert partial.status_code == 409, partial.text

            ready = client.post(f"{batch_path}/finalize", headers=owner_headers)
            assert ready.status_code == 200, ready.text
            manifest_response = client.post(
                f"{batch_path}/lock", headers=owner_headers
            )
            assert manifest_response.status_code == 200, manifest_response.text
            manifest = manifest_response.json()
            assert manifest["attachment_count"] == 3
            assert [item["media_type"] for item in manifest["items"]] == sorted(
                ("image/png", "application/pdf", "application/zip"),
                key=lambda media_type: next(
                    attachment_id
                    for attachment_id, _name, candidate, _payload in attachment_specs
                    if candidate == media_type
                ),
            )
            assert client.post(
                f"{batch_path}/lock", headers=owner_headers
            ).json() == manifest

            late_upload = client.post(
                f"{batch_path}/items",
                headers=owner_headers,
                data={"attachment_id": str(uuid4())},
                files={"file": ("late.pdf", b"late", "application/pdf")},
            )
            assert late_upload.status_code == 409, late_upload.text
            late_remove = client.delete(
                f"{batch_path}/items/{attachment_specs[0][0]}",
                headers=owner_headers,
            )
            assert late_remove.status_code == 409, late_remove.text
            for attachment_id, _name, _media_type, payload in attachment_specs:
                content = client.get(
                    f"{batch_path}/items/{attachment_id}/content",
                    headers=owner_headers,
                )
                assert content.status_code == 200
                assert content.content == payload

            _create_batch(
                client,
                other_headers,
                batch_id=other_batch_id,
                conversation_id=str(uuid4()),
                interaction_id=str(uuid4()),
            )
            uploaded_other = client.post(
                f"{other_batch_path}/items",
                headers=other_headers,
                data={"attachment_id": other_attachment_id},
                files={
                    "file": (
                        "other-tenant.pdf",
                        other_payload,
                        "application/pdf",
                    )
                },
            )
            assert uploaded_other.status_code == 201, uploaded_other.text
            assert client.post(
                f"{other_batch_path}/finalize", headers=other_headers
            ).status_code == 200
            other_manifest = client.post(
                f"{other_batch_path}/lock", headers=other_headers
            ).json()

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
        assert ApprovalWorkItemService(wc_repository).create_or_get(approval)[
            "created"
        ]
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
            decision_comment="Approve three immutable Voucher attachments.",
        )
        assert decision["decision"]["authorized_by_oa"] is True

        ae_server = browser_runtime.start_api_server(
            ae_app, browser_runtime.find_free_port()
        )
        eos_app = create_eos_app(
            environ={
                "NEX_EOS_SERVICE_ID": "nex-eos",
                "NEX_PROFILE": "test",
                "NEX_VERSION": "2.1.0-p8-s75h",
                "NEX_BUILD_SHA": "p8s75hprotected",
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
        eos_headers = {
            "Authorization": "Bearer "
            + p8_s65._service_token("nex-ae-api", "nex-eos"),
            "X-NeX-Tenant-Id": tenant_id,
        }
        with TestClient(eos_app) as client:
            created = client.post(
                "/internal/v1/finance/voucher-drafts",
                json=command,
                headers=eos_headers,
            )
            replayed = client.post(
                "/internal/v1/finance/voucher-drafts",
                json=command,
                headers=eos_headers,
            )
            assert created.status_code == 201, created.text
            assert replayed.status_code == 200, replayed.text
            assert replayed.json()["idempotency_disposition"] == "REPLAYED"
            voucher_id = created.json()["voucher_ref"]["id"]
            verified = client.get(
                f"/internal/v1/finance/voucher-drafts/{voucher_id}/verification",
                params={"business_operation_id": operation_id},
                headers=eos_headers,
            )
            assert verified.status_code == 200, verified.text
            assert verified.json()["attachment_batch_id"] == batch_id
            assert verified.json()["attachment_manifest_hash"] == manifest[
                "attachment_manifest_hash"
            ]
            assert verified.json()["attachment_ids"] == sorted(
                attachment_id
                for attachment_id, _name, _media_type, _payload in attachment_specs
            )

            tampered = _variant_command(
                command,
                suffix=suffix,
                label="tampered",
                attachment_manifest_hash="sha256:" + "0" * 64,
            )
            rejected_tamper = client.post(
                "/internal/v1/finance/voucher-drafts",
                json=tampered,
                headers=eos_headers,
            )
            assert rejected_tamper.status_code == 422, rejected_tamper.text

            cross_tenant = _variant_command(
                command,
                suffix=suffix,
                label="cross-tenant",
            )
            cross_tenant["attachments"][0]["object_ref"] = other_manifest["items"][
                0
            ]["object_ref"]
            cross_tenant["payload_hash"] = voucher_payload_hash(cross_tenant)
            rejected_cross_tenant = client.post(
                "/internal/v1/finance/voucher-drafts",
                json=cross_tenant,
                headers=eos_headers,
            )
            assert (
                rejected_cross_tenant.status_code == 503
            ), rejected_cross_tenant.text
            assert rejected_cross_tenant.json()["error_code"] == (
                "EOS_ATTACHMENT_RESOLVER_UNAVAILABLE"
            )

        assert _journey_counts(
            ae_engine,
            wc_engine,
            eos_engine,
            tenant_id=tenant_id,
        ) == {
            "ae_voucher_attach_batch": 2,
            "ae_voucher_attachment": 4,
            "wc_approval_work_item": 1,
            "wc_approval_decision": 1,
            "eos_voucher_draft": 1,
            "eos_voucher_draft_attachment": 3,
            "eos_business_operation": 1,
        }
    finally:
        if ae_server is not None:
            ae_server.stop()
        if oa_server is not None:
            oa_server.stop()
        if eos_runtime is not None:
            eos_runtime.dispose()
        for scoped_tenant in (tenant_id, other_tenant_id):
            s75f._cleanup(
                eos_engine,
                wc_engine,
                ae_engine,
                oa_engine,
                scoped_tenant,
            )
            assert all(
                value == 0
                for value in s75f._counts(
                    ae_engine,
                    wc_engine,
                    oa_engine,
                    eos_engine,
                    tenant_id=scoped_tenant,
                ).values()
            )
        for object_key in (*object_keys, other_object_key):
            if store.head(object_key) is not None:
                store.delete(object_key)
            assert store.head(object_key) is None
        ae_engine.dispose()
        wc_engine.dispose()
        oa_engine.dispose()
        eos_engine.dispose()


def _prepare_databases() -> None:
    expected = (
        ("nex-ae-api", AE_DATABASE_URL, "nex_ae_user", "nex_ae_test"),
        ("nex-wc", WC_DATABASE_URL, "nex_wc_user", "nex_wc_test"),
        ("nex-oa", OA_DATABASE_URL, "nex_oa_user", "nex_oa_test"),
        ("nex-eos", EOS_DATABASE_URL, "nex_eos_user", "nex_eos_test"),
    )
    for service_id, database_url, expected_user, expected_database in expected:
        result = run_service_migrations(
            service_id, database_url=database_url, profile="test"
        )
        assert len(result.planned) == len(result.applied) + len(result.skipped)
        target = make_url(database_url)
        assert (target.username, target.database) == (expected_user, expected_database)
        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with engine.connect() as connection:
                assert tuple(
                    connection.execute(
                        text("SELECT current_user, current_database()")
                    ).one()
                ) == (expected_user, expected_database)
        finally:
            engine.dispose()


def _attachment_repository(engine: Any) -> SqlAlchemyVoucherAttachmentRepository:
    return SqlAlchemyVoucherAttachmentRepository(
        sessionmaker(bind=engine, expire_on_commit=False)
    )


def _attachment_app(repository: Any, gateway: Any) -> Any:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_voucher_attachment_routes(app, repository=repository, gateway=gateway)
    return app


def _owner_headers(tenant_id: str, owner_id: str) -> dict[str, str]:
    token = issue_mock_user_token(
        tenant_id=tenant_id,
        user_id=owner_id,
        scopes=[DEFAULT_USER_SCOPE],
        roles=["employee"],
    )
    return {"Authorization": f"Bearer {token.access_token}"}


def _create_batch(
    client: TestClient,
    headers: dict[str, str],
    *,
    batch_id: str,
    conversation_id: str,
    interaction_id: str,
) -> None:
    response = client.post(
        "/api/v1/voucher-attachments/batches",
        headers=headers,
        json={
            "attachment_batch_id": batch_id,
            "conversation_id": conversation_id,
            "interaction_id": interaction_id,
        },
    )
    assert response.status_code == 201, response.text


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
        NvtProjectInput(tenant_id, nvt_id, "NVT-75H", "P8-S75H NVT")
    )
    app.state.eos_projects.create_project(
        ProjectInput(
            tenant_id,
            project_id,
            "PROJECT-75H",
            "P8-S75H Project",
            nvt_project_id=nvt_id,
        )
    )
    for account_id, code, category in (
        (debit_id, "TRAVEL-75H", "EXPENSE"),
        (credit_id, "CASH-75H", "ASSET"),
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
    value: dict[str, Any] = {
        "schema_version": "eos_create_voucher_draft_command.v1",
        "tenant_id": tenant_id,
        "business_operation_id": operation_id,
        "idempotency_key": f"p8-s75h-{operation_id}",
        "payload_hash": "sha256:" + "0" * 64,
        "requester_ref": {"type": "oa.user", "id": owner_id},
        "project_ref": {"type": "eos.project", "id": project_id},
        "voucher_type": "GENERAL",
        "transaction_date": "2026-10-23",
        "currency": "KRW",
        "description": "P8-S75H multi-attachment Voucher",
        "lines": [
            {
                "line_no": 1,
                "account_ref": {"type": "eos.account", "id": debit_id},
                "signed_amount": "75000.00",
                "economic_category": "TRAVEL",
                "description": "Receipt evidence",
                "evidence_refs": [evidence_ref],
            },
            {
                "line_no": 2,
                "account_ref": {"type": "eos.account", "id": credit_id},
                "signed_amount": "-75000.00",
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
            for item in manifest["items"]
        ],
        "trace": {
            "trace_id": f"trace-{operation_id}",
            "correlation_id": f"correlation-{operation_id}",
            "causation_id": f"approval-{approval_decision_id}",
        },
    }
    value["payload_hash"] = voucher_payload_hash(value)
    return value


def _variant_command(
    command: dict[str, Any],
    *,
    suffix: str,
    label: str,
    attachment_manifest_hash: str | None = None,
) -> dict[str, Any]:
    value = deepcopy(command)
    value["business_operation_id"] = str(uuid4())
    value["idempotency_key"] = f"p8-s75h-{label}-{suffix}"
    if attachment_manifest_hash is not None:
        value["attachment_manifest_hash"] = attachment_manifest_hash
    value["payload_hash"] = voucher_payload_hash(value)
    return value


def _journey_counts(
    ae_engine: Any,
    wc_engine: Any,
    eos_engine: Any,
    *,
    tenant_id: str,
) -> dict[str, int]:
    result: dict[str, int] = {}
    for engine, tables in (
        (ae_engine, ("ae_voucher_attach_batch", "ae_voucher_attachment")),
        (wc_engine, ("wc_approval_work_item", "wc_approval_decision")),
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
