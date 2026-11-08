from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import pytest
from nex_eos import (
    EOS_ACCOUNT_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_PROJECT_TABLE,
    EOS_VOUCHER_ATTACHMENT_TABLE,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    AccountInput,
    NvtProjectInput,
    ProjectInput,
    ResolvedObjectRef,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosAttachmentRepository,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosVoucherRepository,
    VoucherAttachmentInput,
    VoucherDraftInput,
    VoucherLineInput,
    build_eos_database_runtime,
)
from sqlalchemy import text

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S16_POSTGRES_SMOKE") == "1"
TENANT = "p8-s16-pg"
NVT_ID = "86000000-0000-4000-8000-000000000001"
PROJECT_ID = "87000000-0000-4000-8000-000000000001"
DEBIT_ID = "88000000-0000-4000-8000-000000000001"
CREDIT_ID = "88000000-0000-4000-8000-000000000002"
VOUCHER_ID = "89000000-0000-4000-8000-000000000001"
ATTACHMENT_ID = "8a000000-0000-4000-8000-000000000001"
OBJECT_REF = "objref:postgresopaque00001"
SHA256 = "c" * 64

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S16 PostgreSQL smoke is disabled",
)


class Resolver:
    def resolve_object_ref(self, **kwargs):
        return ResolvedObjectRef(
            object_ref=kwargs["object_ref"],
            storage_owner="nex-ae-api",
            tenant_id=kwargs["tenant_id"],
            purpose=kwargs["required_purpose"],
            status="READY",
            content_sha256=SHA256,
            size_bytes=256,
            media_type="application/pdf",
            authenticated=True,
            immutable=True,
            version_ref="version-pg-1",
        )


def _cleanup(runtime) -> None:
    with runtime.engine.begin() as connection:
        for table in (
            EOS_VOUCHER_ATTACHMENT_TABLE,
            EOS_VOUCHER_DRAFT_LINE_TABLE,
            EOS_VOUCHER_DRAFT_TABLE,
            EOS_ACCOUNT_TABLE,
            EOS_PROJECT_TABLE,
            EOS_NVT_PROJECT_TABLE,
        ):
            connection.execute(table.delete().where(table.c.tenant_id == TENANT))


def test_s16_actual_postgres_attachment_metadata_and_zero_residue() -> None:
    runtime = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    projects = SqlAlchemyEosProjectRepository(runtime.session_factory)
    accounts = SqlAlchemyEosAccountRepository(runtime.session_factory)
    vouchers = SqlAlchemyEosVoucherRepository(runtime.session_factory)
    attachments = SqlAlchemyEosAttachmentRepository(runtime.session_factory, Resolver())
    _cleanup(runtime)
    try:
        with runtime.engine.connect() as connection:
            assert tuple(
                connection.execute(text("SELECT current_database(), current_user")).one()
            ) == ("nex_eos_test", "nex_eos_user")
            assert connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '2507_eos_voucher_attachment'"
                )
            ).scalar_one() == 1
        projects.create_nvt_project(
            NvtProjectInput(TENANT, NVT_ID, "NVT-S16", "NVT S16")
        )
        projects.create_project(
            ProjectInput(TENANT, PROJECT_ID, "PROJECT", "Project", nvt_project_id=NVT_ID)
        )
        for account_id, code, category in (
            (DEBIT_ID, "TRAVEL", "EXPENSE"),
            (CREDIT_ID, "CASH", "ASSET"),
        ):
            accounts.create_account(
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
        vouchers.create_draft(
            VoucherDraftInput(
                TENANT,
                VOUCHER_ID,
                PROJECT_ID,
                date(2026, 10, 21),
                "Voucher attachment PostgreSQL smoke",
                {"type": "oa.user", "id": "employee-1001"},
                {"type": "nsl.approval_request", "id": "approval-s16"},
                (
                    VoucherLineInput(DEBIT_ID, Decimal("5.00"), "TRAVEL"),
                    VoucherLineInput(CREDIT_ID, Decimal("-5.00"), "CASH"),
                ),
            )
        )
        attachments.attach_many(
            tenant_id=TENANT,
            voucher_id=VOUCHER_ID,
            attachments=(
                VoucherAttachmentInput(
                    ATTACHMENT_ID,
                    OBJECT_REF,
                    "receipt.pdf",
                    "application/pdf",
                    256,
                    SHA256,
                ),
            ),
        )
        loaded = attachments.list_attachments(
            tenant_id=TENANT, voucher_id=VOUCHER_ID
        )
        assert len(loaded) == 1
        assert loaded[0]["object_ref"] == OBJECT_REF
        assert loaded[0]["resolver_authenticated"] is True
    finally:
        _cleanup(runtime)
        with runtime.engine.connect() as connection:
            residue = connection.execute(
                text(
                    "SELECT count(*) FROM eos_voucher_draft_attachment "
                    "WHERE tenant_id = :tenant"
                ),
                {"tenant": TENANT},
            ).scalar_one()
        runtime.dispose()
    assert residue == 0
