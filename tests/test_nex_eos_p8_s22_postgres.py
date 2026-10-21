from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_ACCOUNT_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_PROJECT_TABLE,
    EOS_VOUCHER_ATTACHMENT_TABLE,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    AccountInput,
    EosCreateVoucherDraftService,
    EosVoucherAuthorizationClient,
    NvtProjectInput,
    ProjectInput,
    ResolvedObjectRef,
    SqlAlchemyEosAttachmentRepository,
    create_eos_app,
    voucher_payload_hash,
)
from nex_runtime import issue_mock_service_token
from run_migrations import load_migrations
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S22_POSTGRES_SMOKE") == "1"
BUILD_SHA = os.getenv("NEX_EOS_P8_S22_BUILD_SHA", "p8s22protected")

TENANT = "p8-s22-pg"
NVT_ID = "91000000-0000-4000-8000-000000000001"
PROJECT_ID = "92000000-0000-4000-8000-000000000001"
DEBIT_ID = "93000000-0000-4000-8000-000000000001"
CREDIT_ID = "93000000-0000-4000-8000-000000000002"
OPERATION_ID = "94000000-0000-4000-8000-000000000001"
VOUCHER_ID = "95000000-0000-4000-8000-000000000001"
ATTACHMENT_ID = "96000000-0000-4000-8000-000000000001"
OBJECT_REF = "objref:p8s22protectedopaque01"
CONTENT_SHA256 = "d" * 64
NOW = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)

postgres_smoke = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S22 PostgreSQL smoke is disabled",
)

_TENANT_TABLES = (
    EOS_VOUCHER_ATTACHMENT_TABLE,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_ACCOUNT_TABLE,
    EOS_PROJECT_TABLE,
    EOS_NVT_PROJECT_TABLE,
)


class AuthorizationSource:
    def __init__(self) -> None:
        self.calls = 0

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        self.calls += 1
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": ["finance:voucher-draft:create"],
            "project_ids": [PROJECT_ID],
            "resource_refs": [f"voucher_draft:{OPERATION_ID}"],
            "revision_hash": "a" * 64,
        }


class ObjectResolver:
    def resolve_object_ref(self, **kwargs):
        return ResolvedObjectRef(
            object_ref=kwargs["object_ref"],
            storage_owner="nex-ae-api",
            tenant_id=kwargs["tenant_id"],
            purpose=kwargs["required_purpose"],
            status="READY",
            content_sha256=CONTENT_SHA256,
            size_bytes=512,
            media_type="application/pdf",
            authenticated=True,
            immutable=True,
            version_ref="p8-s22-object-version-1",
        )


def _assert_test_database_target() -> None:
    target = make_url(DATABASE_URL)
    assert target.username == "nex_eos_user"
    assert target.database == "nex_eos_test"


def _cleanup(runtime) -> dict[str, int]:
    with runtime.engine.begin() as connection:
        for table in _TENANT_TABLES:
            connection.execute(table.delete().where(table.c.tenant_id == TENANT))
    return _tenant_counts(runtime)


def _tenant_counts(runtime) -> dict[str, int]:
    with runtime.engine.connect() as connection:
        return {
            table.name: connection.execute(
                select(func.count()).select_from(table).where(table.c.tenant_id == TENANT)
            ).scalar_one()
            for table in _TENANT_TABLES
        }


def _payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "eos_create_voucher_draft_command.v1",
        "tenant_id": TENANT,
        "business_operation_id": OPERATION_ID,
        "idempotency_key": "p8-s22-voucher-0001",
        "payload_hash": "sha256:" + "0" * 64,
        "requester_ref": {"type": "oa.user", "id": "employee-p8-s22"},
        "project_ref": {"type": "eos.project", "id": PROJECT_ID},
        "voucher_type": "GENERAL",
        "transaction_date": "2026-10-21",
        "currency": "KRW",
        "description": "P8-S22 protected PostgreSQL voucher",
        "lines": [
            {
                "line_no": 1,
                "account_ref": {"type": "eos.account", "id": DEBIT_ID},
                "signed_amount": "25000.00",
                "economic_category": "TRAVEL",
                "description": "Protected smoke debit",
                "evidence_refs": ["approval-evidence-p8-s22"],
            },
            {
                "line_no": 2,
                "account_ref": {"type": "eos.account", "id": CREDIT_ID},
                "signed_amount": "-25000.00",
                "economic_category": "CASH",
                "description": "Protected smoke credit",
                "evidence_refs": ["approval-evidence-p8-s22"],
            },
        ],
        "nsl_approval_request_id": "approval-request-p8-s22",
        "nsl_approval_evidence_ref": "approval-evidence-p8-s22",
        "business_approval_proof_ref": None,
        "attachments": [
            {
                "attachment_id": ATTACHMENT_ID,
                "object_ref": OBJECT_REF,
                "display_name": "p8-s22-receipt.pdf",
                "media_type": "application/pdf",
                "size_bytes": 512,
                "content_sha256": CONTENT_SHA256,
                "evidence_ref": "approval-evidence-p8-s22",
            }
        ],
        "trace": {
            "trace_id": "trace-p8-s22",
            "correlation_id": "correlation-p8-s22",
            "causation_id": "nsl-write-p8-s22",
        },
    }
    payload["payload_hash"] = voucher_payload_hash(payload)
    return payload


def test_s22_operation_migration_matches_canonical_runtime_contract() -> None:
    migrations = load_migrations("nex-eos")
    assert migrations[-1].version == "2508_eos_operation_name_compatibility"
    sql = migrations[-1].sql
    assert sql.count("CHECK (operation ~ '^[A-Z][A-Z0-9_.]{0,127}$')") == 2
    assert "FINANCE.CREATE_VOUCHER_DRAFT" in (
        ROOT / "services/nex-eos/nex_eos/voucher_commands.py"
    ).read_text(encoding="utf-8")


@postgres_smoke
def test_s22_actual_postgres_foundation_gate_and_zero_residue() -> None:
    _assert_test_database_target()
    environment = {
        "NEX_EOS_SERVICE_ID": "nex-eos",
        "NEX_PROFILE": "test",
        "NEX_VERSION": "2.1.0-p8-s22",
        "NEX_BUILD_SHA": BUILD_SHA,
        "NEX_EOS_DATABASE_URL": DATABASE_URL,
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
    }
    app = create_eos_app(environ=environment)
    runtime = app.state.eos_database_runtime
    assert runtime is not None
    authorization_source = AuthorizationSource()
    app.state.eos_voucher_command_service = EosCreateVoucherDraftService(
        coordinator=app.state.eos_business_transactions,
        vouchers=app.state.eos_vouchers,
        attachments=SqlAlchemyEosAttachmentRepository(
            runtime.session_factory,
            ObjectResolver(),
        ),
        authorizer=EosVoucherAuthorizationClient(
            authorization_source,
            clock=lambda: NOW,
        ),
        id_factory=lambda: VOUCHER_ID,
        clock=lambda: NOW,
    )
    _cleanup(runtime)
    counts: dict[str, int] = {}
    try:
        with runtime.engine.connect() as connection:
            assert tuple(
                connection.execute(text("SELECT current_database(), current_user")).one()
            ) == ("nex_eos_test", "nex_eos_user")
            applied = set(
                connection.execute(text("SELECT version FROM schema_migrations")).scalars()
            )
        assert "2508_eos_operation_name_compatibility" in applied

        app.state.eos_projects.create_nvt_project(
            NvtProjectInput(TENANT, NVT_ID, "NVT-S22", "NVT S22")
        )
        app.state.eos_projects.create_project(
            ProjectInput(
                TENANT,
                PROJECT_ID,
                "PROJECT-S22",
                "Project S22",
                nvt_project_id=NVT_ID,
            )
        )
        for account_id, code, category in (
            (DEBIT_ID, "TRAVEL-S22", "EXPENSE"),
            (CREDIT_ID, "CASH-S22", "ASSET"),
        ):
            app.state.eos_accounts.create_account(
                AccountInput(
                    TENANT,
                    account_id,
                    code,
                    code,
                    category,
                    "GENERAL",
                    date(2026, 1, 1),
                )
            )

        token = issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-eos",
        )
        headers = {
            "Authorization": f"Bearer {token.access_token}",
            "X-NeX-Tenant-Id": TENANT,
        }
        with TestClient(app) as client:
            assert client.get("/ready").status_code == 200
            assert client.get("/version").json() == {
                "service_id": "nex-eos",
                "service_name": "NeX Enterprise Operations System",
                "version": "2.1.0-p8-s22",
                "api_version": "v1",
                "contract_catalog_version": "p8-s07",
                "build_sha": BUILD_SHA,
            }
            created = client.post(
                "/internal/v1/finance/voucher-drafts",
                json=_payload(),
                headers=headers,
            )
            replayed = client.post(
                "/internal/v1/finance/voucher-drafts",
                json=_payload(),
                headers=headers,
            )
            assert created.status_code == 201, created.text
            assert replayed.status_code == 200, replayed.text
            assert created.json()["idempotency_disposition"] == "CREATED"
            assert replayed.json()["idempotency_disposition"] == "REPLAYED"
            assert authorization_source.calls == 2

            operation = client.get(
                f"/internal/v1/business-operations/{OPERATION_ID}",
                headers=headers,
            )
            assert operation.status_code == 200, operation.text
            assert operation.json()["reconciliation_status"] == "COMMITTED_CONFIRMED"

            statements: list[str] = []

            def observe_sql(_connection, _cursor, statement, *_args):
                statements.append(statement.lstrip().split(maxsplit=1)[0].upper())

            event.listen(runtime.engine, "before_cursor_execute", observe_sql)
            try:
                verified = client.get(
                    f"/internal/v1/finance/voucher-drafts/{VOUCHER_ID}/verification",
                    params={"business_operation_id": OPERATION_ID},
                    headers=headers,
                )
            finally:
                event.remove(runtime.engine, "before_cursor_execute", observe_sql)
            assert verified.status_code == 200, verified.text
            assert verified.json()["balance"] == "0.00"
            assert verified.json()["line_count"] == 2
            assert verified.json()["attachment_count"] == 1
            assert statements and set(statements) == {"SELECT"}

        counts = _tenant_counts(runtime)
        assert counts == {
            "eos_voucher_draft_attachment": 1,
            "eos_voucher_draft_line": 2,
            "eos_voucher_draft": 1,
            "eos_outbox": 1,
            "eos_idempotency": 1,
            "eos_business_operation": 1,
            "eos_account": 2,
            "eos_project": 1,
            "eos_nvt_project": 1,
        }
    finally:
        residue = _cleanup(runtime)
        runtime.dispose()
    assert counts["eos_outbox"] == 1
    assert all(value == 0 for value in residue.values()), residue
