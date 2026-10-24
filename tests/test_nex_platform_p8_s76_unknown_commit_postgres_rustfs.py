from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import run_ae_web_credential_login_playwright_postgres_smoke as browser_runtime
import run_p8_s65_golden_a_approval_journey as p8_s65
import test_nex_eos_p8_s75f_postgres_rustfs as s75f
import test_nex_platform_p8_s75h_protected_attachment_journey as s75h
from fastapi.testclient import TestClient
from nex_ae_api.voucher_attachment_storage import VoucherAttachmentObjectGateway
from nex_eos import AccountInput, NvtProjectInput, ProjectInput, create_eos_app
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
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
AE_DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL", "")
WC_DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL", "")
OA_DATABASE_URL = os.getenv("NEX_OA_TEST_DATABASE_URL", "")
EOS_DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
RUSTFS_ENDPOINT = os.getenv("NEX_P8_S76_RUSTFS_ENDPOINT", "")
RUSTFS_ACCESS_KEY = os.getenv("NEX_P8_S76_RUSTFS_ACCESS_KEY", "")
RUSTFS_SECRET_KEY = os.getenv("NEX_P8_S76_RUSTFS_SECRET_KEY", "")
SMOKE_ENABLED = os.getenv("NEX_P8_S76_PROTECTED_SMOKE") == "1"
BUCKET = "nex-ae-p8-s76"

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
    reason="Protected P8-S76 UNKNOWN_COMMIT_STATE smoke is disabled",
)


def test_attachment_write_ack_loss_preserves_exactly_one_committed_state() -> None:
    s75h._prepare_databases()
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s76-{suffix}"
    owner_id = f"employee-{suffix[:12]}"
    batch_id = str(uuid4())
    operation_id = str(uuid4())
    approval_work_item_id = str(uuid4())
    project_id = str(uuid4())
    nvt_id = str(uuid4())
    debit_id = str(uuid4())
    credit_id = str(uuid4())
    attachment_specs = (
        (str(uuid4()), "taxi.png", "image/png", b"p8-s76-image"),
        (str(uuid4()), "statement.pdf", "application/pdf", b"p8-s76-pdf"),
        (str(uuid4()), "evidence.zip", "application/zip", b"p8-s76-zip"),
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
            for attachment_id, name, media_type, payload in attachment_specs:
                response = client.post(
                    f"{batch_path}/items",
                    headers=owner_headers,
                    data={"attachment_id": attachment_id},
                    files={"file": (name, payload, media_type)},
                )
                assert response.status_code == 201, response.text
            assert client.post(
                f"{batch_path}/finalize", headers=owner_headers
            ).status_code == 200
            manifest_response = client.post(
                f"{batch_path}/lock", headers=owner_headers
            )
            assert manifest_response.status_code == 200, manifest_response.text
            manifest = manifest_response.json()

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
            decision_comment="Approve the immutable P8-S76 evidence manifest.",
        )

        ae_server = browser_runtime.start_api_server(
            ae_app, browser_runtime.find_free_port()
        )
        eos_app = create_eos_app(
            environ={
                "NEX_EOS_SERVICE_ID": "nex-eos",
                "NEX_PROFILE": "test",
                "NEX_VERSION": "2.1.0-p8-s76",
                "NEX_BUILD_SHA": "p8s76protected",
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
        eos_server = browser_runtime.start_api_server(
            eos_app, browser_runtime.find_free_port()
        )
        try:
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
            command["idempotency_key"] = "idem:sha256:" + "7" * 64
            fault_result = _execute_ack_loss(
                command,
                eos_base_url=eos_server.url,
                service_token=p8_s65._service_token("nex-ae-api", "nex-eos"),
            )
        finally:
            eos_server.stop()

        assert fault_result == {
            "business_operation_id": operation_id,
            "dispatch_attempts": 1,
            "idempotency_key": command["idempotency_key"],
            "observed_commit_state": "UNKNOWN_COMMIT_STATE",
            "payload_hash": command["payload_hash"],
            "reason_code": "EOS_COMMIT_ACKNOWLEDGEMENT_LOST",
            "reconciliation_status": "RECONCILIATION_REQUIRED",
            "response_status_discarded": 201,
        }

        persisted = repository.get_batch(
            tenant_id=tenant_id,
            attachment_batch_id=batch_id,
        )
        assert persisted is not None
        assert persisted["state"] == "LOCKED"
        assert persisted["attachment_manifest_hash"] == manifest[
            "attachment_manifest_hash"
        ]
        assert [item["attachment_id"] for item in persisted["items"]] == [
            item["attachment_id"] for item in manifest["items"]
        ]
        assert [item["object_ref"] for item in persisted["items"]] == [
            item["object_ref"] for item in manifest["items"]
        ]
        assert {
            key: _object_versions(object_client, key) for key in object_keys
        } == versions_before

        assert s75h._journey_counts(
            ae_engine,
            wc_engine,
            eos_engine,
            tenant_id=tenant_id,
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
            assert connection.execute(
                text(
                    "SELECT count(*) FROM eos_outbox "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one() == 1
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
        NvtProjectInput(tenant_id, nvt_id, "NVT-76", "P8-S76 NVT")
    )
    app.state.eos_projects.create_project(
        ProjectInput(
            tenant_id,
            project_id,
            "PROJECT-76",
            "P8-S76 Project",
            nvt_project_id=nvt_id,
        )
    )
    for account_id, code, category in (
        (debit_id, "TRAVEL-76", "EXPENSE"),
        (credit_id, "CASH-76", "ASSET"),
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


def _execute_ack_loss(
    command: dict[str, Any],
    *,
    eos_base_url: str,
    service_token: str,
) -> dict[str, Any]:
    wheel = (
        ROOT
        / "reports/deployment/p8-nsl-v0.2-wheel"
        / "nex_skill_language-0.2.0-py3-none-any.whl"
    )
    readiness = ROOT / "reports/deployment/p8-s04-nsl-v0.2-readiness.json"
    assert wheel.is_file()
    assert readiness.is_file()
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _ACK_LOSS_PROBE,
            str(wheel),
            str(readiness),
            str(ROOT / "services/nex-ae-api"),
            str(ROOT / "services/_shared"),
            str(ROOT / "scripts/smoke"),
        ],
        input=json.dumps(
            {
                "command": command,
                "eos_base_url": eos_base_url,
                "service_token": service_token,
            },
            ensure_ascii=False,
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    return json.loads(completed.stdout)


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


_ACK_LOSS_PROBE = r"""
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta

sys.path[:0] = [sys.argv[1], sys.argv[3], sys.argv[4], sys.argv[5]]

from nex_ae_api.nsl_eos_write_execution import HttpEosWriteExecutionPort
from nex_ae_api.nsl_v02_public_api import load_nsl_v02_public_api
from nsl.api import BusinessPreconditionEvidence, BusinessPreconditionMechanism, WriteCallRequest, compute_payload_hash
from nsl.core import ApprovalRequestId, BusinessOperationId, DataClassification, IdempotencyKey, STRING, ValueEnvelope
from p8_reliability_faults import EosCommitAckLossFaultPort

payload = json.load(sys.stdin)
command = payload["command"]
readiness = json.loads(open(sys.argv[2], encoding="utf-8").read())["readiness"]
public_api = load_nsl_v02_public_api(readiness)
business_payload = {
    key: value
    for key, value in command.items()
    if key not in {
        "business_operation_id",
        "idempotency_key",
        "payload_hash",
        "nsl_approval_request_id",
        "nsl_approval_evidence_ref",
        "business_approval_proof_ref",
        "trace",
    }
}
business_payload["description_text"] = business_payload.pop("description")
arguments = {
    key: ValueEnvelope.complete(value, STRING)
    for key, value in business_payload.items()
}
payload_hash = compute_payload_hash(arguments)
if str(payload_hash) != command["payload_hash"]:
    raise RuntimeError("NSL and EOS payload hashes differ")
now = datetime.now(UTC).replace(microsecond=0)
business_operation_id = BusinessOperationId(command["business_operation_id"])
precondition = BusinessPreconditionEvidence(
    evidence_id="precondition-p8-s76",
    tenant_id=command["tenant_id"],
    business_operation_id=business_operation_id,
    write_node_id="write-voucher-draft",
    tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
    contract_hash="sha256:" + "6" * 64,
    payload_hash=payload_hash,
    write_intent_hash="sha256:" + "8" * 64,
    mechanism=BusinessPreconditionMechanism.ETAG,
    evidence_ref="etag:opaque:p8-s76",
    observed_at=now,
    expires_at=now + timedelta(hours=1),
    provider_atomic_enforcement=True,
)
request = WriteCallRequest(
    tenant_id=command["tenant_id"],
    execution_id="nsl-execution-p8-s76",
    business_operation_id=business_operation_id,
    invocation_id="invocation-p8-s76",
    node_id="write-voucher-draft",
    tool_ref="urn:nex:tool:finance-create-voucher-draft:v1",
    tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
    contract_hash="sha256:" + "6" * 64,
    arguments=arguments,
    idempotency_key=IdempotencyKey(command["idempotency_key"]),
    payload_hash=payload_hash,
    approval_id="APPROVE_VOUCHER_DRAFT",
    approval_request_id=ApprovalRequestId(command["nsl_approval_request_id"]),
    write_intent_hash="sha256:" + "8" * 64,
    business_preconditions=precondition,
    trace_refs=tuple(f"{key}:{value}" for key, value in command["trace"].items()),
)
delegate = HttpEosWriteExecutionPort(
    public_api=public_api,
    base_url=payload["eos_base_url"],
    service_token=payload["service_token"],
    result_type=STRING,
    result_classification=DataClassification.CONFIDENTIAL,
)
fault_port = EosCommitAckLossFaultPort(delegate, public_api)
outcome = asyncio.run(fault_port.execute(request))
evidence = fault_port.evidence
print(json.dumps({
    "business_operation_id": str(outcome.identity.business_operation_id),
    "dispatch_attempts": evidence.dispatch_attempts,
    "idempotency_key": str(outcome.identity.idempotency_key),
    "observed_commit_state": outcome.commit_state.value,
    "payload_hash": str(outcome.identity.payload_hash),
    "reason_code": outcome.reason_code,
    "reconciliation_status": evidence.reconciliation_status,
    "response_status_discarded": evidence.response_status_discarded,
}, sort_keys=True))
"""
