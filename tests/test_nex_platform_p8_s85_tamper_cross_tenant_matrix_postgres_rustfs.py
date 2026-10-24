from __future__ import annotations

import os
from copy import deepcopy
from io import BytesIO
from typing import Any
from uuid import uuid4

import pytest
import run_ae_web_credential_login_playwright_postgres_smoke as browser_runtime
import run_p8_s65_golden_a_approval_journey as p8_s65
import test_nex_ae_p8_s52_nsl_approval_resume_integration as s52
import test_nex_eos_p8_s75f_postgres_rustfs as s75f
import test_nex_platform_p8_s75h_protected_attachment_journey as s75h
import test_nex_wc_p8_s31_postgres_acceptance as s31
from fastapi.testclient import TestClient
from nex_ae_api.platform_approval_evidence import (
    PlatformApprovalEvidenceError,
    SqlAlchemyPlatformApprovalEvidenceRepository,
)
from nex_ae_api.voucher_attachment_api import register_voucher_attachment_routes
from nex_ae_api.voucher_attachment_storage import VoucherAttachmentObjectGateway
from nex_ae_api.voucher_attachments import (
    ATTACHMENT_BATCH_SCHEMA_VERSION,
    SqlAlchemyVoucherAttachmentRepository,
)
from nex_eos import create_eos_app, voucher_payload_hash
from nex_oa.authorization_service import OA_AUTHORIZATION_READ_SCOPE
from nex_runtime import SERVICE_SPECS, build_service_app
from nex_runtime.object_storage import (
    ObjectStorageSettings,
    S3ObjectStore,
    build_owner_object_key,
    build_s3_client,
)
from nex_runtime.object_storage_lifecycle import bootstrap_private_bucket
from nex_wc.work_items import WorkItemError, WorkItemService
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

AE_DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL", "")
WC_DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL", "")
OA_DATABASE_URL = os.getenv("NEX_OA_TEST_DATABASE_URL", "")
EOS_DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
RUSTFS_ENDPOINT = os.getenv("NEX_P8_S85_RUSTFS_ENDPOINT", "")
RUSTFS_ACCESS_KEY = os.getenv("NEX_P8_S85_RUSTFS_ACCESS_KEY", "")
RUSTFS_SECRET_KEY = os.getenv("NEX_P8_S85_RUSTFS_SECRET_KEY", "")
SMOKE_ENABLED = os.getenv("NEX_P8_S85_PROTECTED_SMOKE") == "1"
BUCKET = "nex-ae-p8-s85"

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
    reason="Protected P8-S85 tamper/cross-tenant matrix is disabled",
)


def _publish_manifest(
    repository: SqlAlchemyVoucherAttachmentRepository,
    gateway: VoucherAttachmentObjectGateway,
    *,
    tenant_id: str,
    owner_id: str,
    batch_id: str,
    attachment_id: str,
    payload: bytes,
) -> dict[str, Any]:
    repository.create_batch(
        {
            "schema_version": ATTACHMENT_BATCH_SCHEMA_VERSION,
            "tenant_id": tenant_id,
            "attachment_batch_id": batch_id,
            "owner_subject_ref": {"type": "oa.user", "id": owner_id},
            "conversation_id": str(uuid4()),
            "interaction_id": str(uuid4()),
            "trace": {
                "trace_id": f"trace-{batch_id}",
                "correlation_id": f"correlation-{batch_id}",
                "causation_id": f"upload-{attachment_id}",
            },
        }
    )
    repository.register_item(
        {
            "tenant_id": tenant_id,
            "attachment_batch_id": batch_id,
            "attachment_id": attachment_id,
            "display_name": f"evidence-{attachment_id}.pdf",
            "media_type": "application/pdf",
            "size_bytes": len(payload),
        }
    )
    gateway.publish(
        tenant_id=tenant_id,
        attachment_batch_id=batch_id,
        attachment_id=attachment_id,
        source=BytesIO(payload),
    )
    repository.finalize_batch(
        tenant_id=tenant_id,
        attachment_batch_id=batch_id,
    )
    return repository.lock_manifest(
        tenant_id=tenant_id,
        attachment_batch_id=batch_id,
    )


def _variant(command: dict[str, Any], label: str) -> dict[str, Any]:
    value = deepcopy(command)
    value["business_operation_id"] = str(uuid4())
    value["idempotency_key"] = f"p8-s85-{label}-{uuid4().hex}"
    return value


def _command_attachment(item: dict[str, Any], evidence_ref: str) -> dict[str, Any]:
    return {
        "attachment_id": item["attachment_id"],
        "object_ref": item["object_ref"],
        "display_name": item["display_name"],
        "media_type": item["media_type"],
        "size_bytes": item["size_bytes"],
        "content_sha256": item["content_sha256"],
        "evidence_ref": evidence_ref,
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
                "eos_voucher_draft_line",
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


def test_actual_ae_approval_evidence_tamper_is_detected_before_write() -> None:
    s75h._prepare_databases()
    engine = create_engine(AE_DATABASE_URL, poolclass=NullPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    repository = SqlAlchemyPlatformApprovalEvidenceRepository(sessions)
    evidence = s52._evidence()
    tenant_id = evidence["tenant_id"]
    agent_id = str(uuid4())
    try:
        with engine.begin() as connection:
            for table in (
                "ae_approval_evidence",
                "ae_nsl_write_evidence",
                "ae_nsl_idem_evidence",
                "ae_nsl_approval_request",
                "ae_executable_step",
                "ae_agent_execution",
                "ae_agent_identity",
            ):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                )
            connection.execute(
                text(
                    "INSERT INTO ae_agent_identity (tenant_id, agent_id, agent_type, "
                    "profile_ref, status) VALUES (:tenant_id, :agent_id, 'IA', "
                    "'profile://p8-s85', 'ACTIVE')"
                ),
                {"tenant_id": tenant_id, "agent_id": agent_id},
            )
            connection.execute(
                text(
                    "INSERT INTO ae_agent_execution (tenant_id, agent_execution_id, "
                    "agent_id, agent_type, principal_id, trigger_id, source_type, "
                    "source_ref, state, phase, correlation_id, received_at) VALUES "
                    "(:tenant_id, :execution_id, :agent_id, 'IA', 'employee-p8-s85', "
                    ":trigger_id, 'PROMPT', 'prompt://p8-s85', 'WAITING_APPROVAL', "
                    "'STEP_EXECUTION', :correlation_id, now())"
                ),
                {
                    "tenant_id": tenant_id,
                    "execution_id": evidence["agent_execution_id"],
                    "agent_id": agent_id,
                    "trigger_id": str(uuid4()),
                    "correlation_id": f"correlation-{uuid4().hex}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO ae_nsl_approval_request (tenant_id, "
                    "approval_request_id, nsl_execution_id, business_operation_id, "
                    "protected_request_ref, approval_request_hash, request_size_bytes, "
                    "content_type, data_classification, created_at, "
                    "approval_request_bytes) VALUES (:tenant_id, :request_id, "
                    ":nsl_execution_id, :business_operation_id, :protected_ref, "
                    ":request_hash, 2, 'application/json', 'INTERNAL', now(), :body)"
                ),
                {
                    "tenant_id": tenant_id,
                    "request_id": evidence["approval_request_id"],
                    "nsl_execution_id": evidence["nsl_execution_id"],
                    "business_operation_id": evidence["business_operation_id"],
                    "protected_ref": evidence["protected_request_ref"],
                    "request_hash": "sha256:" + "8" * 64,
                    "body": b"{}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO ae_executable_step (tenant_id, executable_step_id, "
                    "agent_execution_id, step_kind, state, legacy_interaction_id, "
                    "correlation_id) VALUES (:tenant_id, :step_id, :execution_id, "
                    "'P4_CHAT_RAG_COMPATIBILITY', 'WAITING', :interaction_id, "
                    ":correlation_id)"
                ),
                {
                    "tenant_id": tenant_id,
                    "step_id": evidence["executable_step_id"],
                    "execution_id": evidence["agent_execution_id"],
                    "interaction_id": str(uuid4()),
                    "correlation_id": f"correlation-{uuid4().hex}",
                },
            )
        repository.create_or_get(evidence)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE ae_approval_evidence "
                    "SET payload_hash = :payload_hash "
                    "WHERE tenant_id = :tenant_id "
                    "AND approval_request_id = :approval_request_id"
                ),
                {
                    "tenant_id": tenant_id,
                    "approval_request_id": evidence["approval_request_id"],
                    "payload_hash": "sha256:" + "0" * 64,
                },
            )

        with pytest.raises(PlatformApprovalEvidenceError) as denied:
            repository.get(
                tenant_id=tenant_id,
                approval_request_id=evidence["approval_request_id"],
            )
        assert denied.value.error_code == "ae.approval_evidence_integrity_failed"
        with engine.connect() as connection:
            counts = dict(
                connection.execute(
                    text(
                        "SELECT 'approval' AS kind, count(*) AS total "
                        "FROM ae_approval_evidence WHERE tenant_id = :tenant_id "
                        "UNION ALL SELECT 'idempotency', count(*) "
                        "FROM ae_nsl_idem_evidence WHERE tenant_id = :tenant_id "
                        "UNION ALL SELECT 'write', count(*) "
                        "FROM ae_nsl_write_evidence WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).all()
            )
        assert counts == {"approval": 1, "idempotency": 0, "write": 0}
    finally:
        with engine.begin() as connection:
            for table in (
                "ae_approval_evidence",
                "ae_nsl_write_evidence",
                "ae_nsl_idem_evidence",
                "ae_nsl_approval_request",
                "ae_executable_step",
                "ae_agent_execution",
                "ae_agent_identity",
            ):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                )
        engine.dispose()


def test_actual_postgres_rustfs_cross_tenant_matrix_has_zero_mutation() -> None:
    s75h._prepare_databases()
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s85-{suffix}"
    foreign_tenant_id = f"tenant-p8-s85-foreign-{suffix}"
    owner_id = f"employee-{suffix[:12]}"
    foreign_owner_id = f"employee-foreign-{suffix[:8]}"
    batch_id, substitute_batch_id, foreign_batch_id = (str(uuid4()) for _ in range(3))
    attachment_id, substitute_id, foreign_id = (str(uuid4()) for _ in range(3))
    project_id, foreign_project_id = str(uuid4()), str(uuid4())
    nvt_id, foreign_nvt_id = str(uuid4()), str(uuid4())
    debit_id, credit_id, foreign_account_id = (str(uuid4()) for _ in range(3))
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
    object_specs = (
        (tenant_id, owner_id, attachment_id, b"p8-s85-primary"),
        (tenant_id, owner_id, substitute_id, b"p8-s85-substitute"),
        (
            foreign_tenant_id,
            foreign_owner_id,
            foreign_id,
            b"p8-s85-foreign",
        ),
    )
    object_keys = tuple(
        build_owner_object_key(
            payload_family="voucher-evidence",
            tenant_id=scoped_tenant,
            subject_id=owner,
            content_id=attachment,
            suffix="bin",
        )
        for scoped_tenant, owner, attachment, _payload in object_specs
    )
    ae_engine = create_engine(AE_DATABASE_URL, poolclass=NullPool)
    wc_engine = create_engine(WC_DATABASE_URL, poolclass=NullPool)
    oa_engine = create_engine(OA_DATABASE_URL, poolclass=NullPool)
    eos_engine = create_engine(EOS_DATABASE_URL, poolclass=NullPool)
    repository = SqlAlchemyVoucherAttachmentRepository(
        sessionmaker(bind=ae_engine, expire_on_commit=False)
    )
    gateway = VoucherAttachmentObjectGateway(store, repository)
    oa_server = None
    ae_server = None
    eos_runtime = None
    try:
        manifest = _publish_manifest(
            repository,
            gateway,
            tenant_id=tenant_id,
            owner_id=owner_id,
            batch_id=batch_id,
            attachment_id=attachment_id,
            payload=object_specs[0][3],
        )
        substitute_manifest = _publish_manifest(
            repository,
            gateway,
            tenant_id=tenant_id,
            owner_id=owner_id,
            batch_id=substitute_batch_id,
            attachment_id=substitute_id,
            payload=object_specs[1][3],
        )
        foreign_manifest = _publish_manifest(
            repository,
            gateway,
            tenant_id=foreign_tenant_id,
            owner_id=foreign_owner_id,
            batch_id=foreign_batch_id,
            attachment_id=foreign_id,
            payload=object_specs[2][3],
        )
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
            scopes=["finance:voucher-draft:create"],
        )
        oa_server = browser_runtime.start_api_server(
            oa_app, browser_runtime.find_free_port()
        )
        ae_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
        register_voucher_attachment_routes(
            ae_app,
            repository=repository,
            gateway=gateway,
        )
        ae_server = browser_runtime.start_api_server(
            ae_app, browser_runtime.find_free_port()
        )
        eos_app = create_eos_app(
            environ={
                "NEX_EOS_SERVICE_ID": "nex-eos",
                "NEX_PROFILE": "test",
                "NEX_VERSION": "2.1.0-p8-s85",
                "NEX_BUILD_SHA": "p8s85protected",
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
        s75f._seed_eos(
            eos_app,
            tenant_id=foreign_tenant_id,
            nvt_id=foreign_nvt_id,
            project_id=foreign_project_id,
            debit_id=foreign_account_id,
            credit_id=str(uuid4()),
        )
        command = s75f._voucher_command(
            tenant_id=tenant_id,
            owner_id=owner_id,
            operation_id=str(uuid4()),
            project_id=project_id,
            debit_id=debit_id,
            credit_id=credit_id,
            manifest=manifest,
            approval_decision_id=str(uuid4()),
        )
        headers = {
            "Authorization": "Bearer " + p8_s65._service_token("nex-ae-api", "nex-eos"),
            "X-NeX-Tenant-Id": tenant_id,
        }
        attacks: list[tuple[str, dict[str, Any], int, str]] = []

        payload_mismatch = _variant(command, "payload-hash")
        payload_mismatch["description"] = "tampered without canonical rehash"
        attacks.append(
            (
                "payload_hash_mismatch",
                payload_mismatch,
                422,
                "EOS_VOUCHER_PAYLOAD_HASH_MISMATCH",
            )
        )

        cross_project = _variant(command, "cross-project")
        cross_project["project_ref"] = {
            "type": "eos.project",
            "id": foreign_project_id,
        }
        cross_project["payload_hash"] = voucher_payload_hash(cross_project)
        attacks.append(
            (
                "cross_tenant_project",
                cross_project,
                422,
                "EOS_VOUCHER_PROJECT_NOT_FOUND",
            )
        )

        cross_account = _variant(command, "cross-account")
        cross_account["lines"][0]["account_ref"] = {
            "type": "eos.account",
            "id": foreign_account_id,
        }
        cross_account["payload_hash"] = voucher_payload_hash(cross_account)
        attacks.append(
            (
                "cross_tenant_account",
                cross_account,
                422,
                "EOS_VOUCHER_ACCOUNT_NOT_FOUND",
            )
        )

        manifest_drift = _variant(command, "manifest-drift")
        manifest_drift["attachment_manifest_hash"] = "sha256:" + "0" * 64
        manifest_drift["payload_hash"] = voucher_payload_hash(manifest_drift)
        attacks.append(
            (
                "manifest_drift",
                manifest_drift,
                422,
                "EOS_ATTACHMENT_OBJECT_REJECTED",
            )
        )

        substituted = _variant(command, "attachment-substitution")
        substituted["attachments"] = [
            _command_attachment(
                substitute_manifest["items"][0],
                command["attachments"][0]["evidence_ref"],
            )
        ]
        substituted["payload_hash"] = voucher_payload_hash(substituted)
        attacks.append(
            (
                "attachment_substitution",
                substituted,
                422,
                "EOS_ATTACHMENT_OBJECT_REJECTED",
            )
        )

        foreign_attachment = _variant(command, "cross-tenant-attachment")
        foreign_attachment["attachments"] = [
            _command_attachment(
                foreign_manifest["items"][0],
                command["attachments"][0]["evidence_ref"],
            )
        ]
        foreign_attachment["payload_hash"] = voucher_payload_hash(foreign_attachment)
        attacks.append(
            (
                "cross_tenant_attachment",
                foreign_attachment,
                503,
                "EOS_ATTACHMENT_RESOLVER_UNAVAILABLE",
            )
        )

        baseline = _eos_mutation_counts(eos_engine, tenant_id)
        foreign_baseline = _eos_mutation_counts(eos_engine, foreign_tenant_id)
        assert all(count == 0 for count in baseline.values())
        assert all(count == 0 for count in foreign_baseline.values())
        with TestClient(eos_app) as client:
            for label, payload, status_code, error_code in attacks:
                response = client.post(
                    "/internal/v1/finance/voucher-drafts",
                    json=payload,
                    headers=headers,
                )
                assert response.status_code == status_code, (label, response.text)
                assert response.json()["error_code"] == error_code
                assert _eos_mutation_counts(eos_engine, tenant_id) == baseline
                assert (
                    _eos_mutation_counts(eos_engine, foreign_tenant_id)
                    == foreign_baseline
                )
                assert {
                    key: _object_versions(object_client, key) for key in object_keys
                } == versions_before

        resolver_response = TestClient(ae_app).post(
            "/internal/v1/voucher-attachments/resolve",
            headers={
                "Authorization": "Bearer "
                + p8_s65._service_token("nex-eos", "nex-ae-api"),
                "X-NeX-Tenant-Id": tenant_id,
            },
            json={
                "object_ref": foreign_manifest["items"][0]["object_ref"],
                "required_purpose": "EOS_VOUCHER_ATTACHMENT",
            },
        )
        assert resolver_response.status_code == 404, resolver_response.text
        assert _eos_mutation_counts(eos_engine, tenant_id) == baseline
        assert {
            key: _object_versions(object_client, key) for key in object_keys
        } == versions_before
    finally:
        if ae_server is not None:
            ae_server.stop()
        if oa_server is not None:
            oa_server.stop()
        if eos_runtime is not None:
            eos_runtime.dispose()
        for scoped_tenant in (tenant_id, foreign_tenant_id):
            s75f._cleanup(
                eos_engine,
                wc_engine,
                ae_engine,
                oa_engine,
                scoped_tenant,
            )
        for object_key in object_keys:
            if store.head(object_key) is not None:
                store.delete(object_key)
            assert store.head(object_key) is None
        ae_engine.dispose()
        wc_engine.dispose()
        oa_engine.dispose()
        eos_engine.dispose()


def test_actual_wc_stale_claim_delegation_has_zero_child_rows() -> None:
    s75h._prepare_databases()
    tenant_id = f"tenant-p8-s85-wc-{uuid4().hex}"
    engine = create_engine(WC_DATABASE_URL, pool_size=5, max_overflow=1)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with engine.begin() as connection:
        s31._cleanup(connection, tenant_id)
    try:
        harness = s31.Harness(sessions, tenant_id)
        root_id = harness.create("s85-root")
        parent = harness.claim_and_ack(
            root_id,
            s31._agent("s85-parent"),
            "s85-parent",
        )
        with engine.connect() as connection:
            baseline = s31._tenant_counts(connection, tenant_id)
        stale_payload = s31._payload(tenant_id, "s85-stale-child", parent)
        stale_payload["delegation_spec"]["parent_claim_generation"] = 2
        stale_id = s31._stable_uuid(f"{tenant_id}-work-s85-stale-child")

        with pytest.raises(WorkItemError) as denied:
            WorkItemService(
                harness.work_items,
                authorization_source=s31.Authorization(),
                id_factory=lambda: stale_id,
                clock=lambda: s31.NOW_DT,
                delegation_guard_enabled=True,
            ).create(stale_payload)

        assert denied.value.error_code == "wc.delegation_parent_authority_stale"
        with engine.connect() as connection:
            assert s31._tenant_counts(connection, tenant_id) == baseline
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM wc_work_item "
                        "WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id"
                    ),
                    {"tenant_id": tenant_id, "work_item_id": stale_id},
                ).scalar_one()
                == 0
            )
    finally:
        with engine.begin() as connection:
            s31._cleanup(connection, tenant_id)
            residue = s31._tenant_counts(connection, tenant_id)
        engine.dispose()
    assert all(count == 0 for count in residue.values()), residue
