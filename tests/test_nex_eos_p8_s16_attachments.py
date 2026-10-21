from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from nex_eos import (
    EOS_METADATA,
    AccountInput,
    EosAttachmentError,
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
)
from run_migrations import load_migrations
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NVT_ID = "81000000-0000-4000-8000-000000000001"
PROJECT_ID = "82000000-0000-4000-8000-000000000001"
DEBIT_ID = "83000000-0000-4000-8000-000000000001"
CREDIT_ID = "83000000-0000-4000-8000-000000000002"
VOUCHER_ID = "84000000-0000-4000-8000-000000000001"
ATTACHMENT_ID = "85000000-0000-4000-8000-000000000001"
OBJECT_REF = "objref:ownerissuedopaque0001"
CONTENT_SHA256 = "a" * 64
TX_DATE = date(2026, 10, 21)


class Resolver:
    def __init__(self, *, overrides=None, error=None):
        self.overrides = overrides or {}
        self.error = error
        self.calls = []

    def resolve_object_ref(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        values = {
            "object_ref": kwargs["object_ref"],
            "storage_owner": "nex-ae-api",
            "tenant_id": kwargs["tenant_id"],
            "purpose": "EOS_VOUCHER_ATTACHMENT",
            "status": "READY",
            "content_sha256": CONTENT_SHA256,
            "size_bytes": 128,
            "media_type": "application/pdf",
            "authenticated": True,
            "immutable": True,
            "version_ref": "version-0001",
        }
        values.update(self.overrides)
        return ResolvedObjectRef(**values)


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _seed_voucher(factory) -> None:
    projects = SqlAlchemyEosProjectRepository(factory)
    accounts = SqlAlchemyEosAccountRepository(factory)
    vouchers = SqlAlchemyEosVoucherRepository(factory)
    projects.create_nvt_project(
        NvtProjectInput("tenant-a", NVT_ID, "NVT-A", "NVT A")
    )
    projects.create_project(
        ProjectInput(
            "tenant-a", PROJECT_ID, "PROJECT-A", "Project A", nvt_project_id=NVT_ID
        )
    )
    for account_id, code, category in (
        (DEBIT_ID, "TRAVEL", "EXPENSE"),
        (CREDIT_ID, "CASH", "ASSET"),
    ):
        accounts.create_account(
            AccountInput(
                "tenant-a",
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
            "tenant-a",
            VOUCHER_ID,
            PROJECT_ID,
            TX_DATE,
            "Voucher with optional attachment",
            {"type": "oa.user", "id": "employee-1001"},
            {"type": "nsl.approval_request", "id": "approval-1001"},
            (
                VoucherLineInput(DEBIT_ID, Decimal("10.00"), "TRAVEL"),
                VoucherLineInput(CREDIT_ID, Decimal("-10.00"), "CASH"),
            ),
        )
    )


def _attachment(**overrides):
    values = {
        "attachment_id": ATTACHMENT_ID,
        "object_ref": OBJECT_REF,
        "display_name": "receipt.pdf",
        "media_type": "application/pdf",
        "size_bytes": 128,
        "content_sha256": CONTENT_SHA256,
        "evidence_ref": "evidence-1001",
    }
    values.update(overrides)
    return VoucherAttachmentInput(**values)


def test_s16_migration_keeps_binary_and_credentials_outside_eos() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2507_eos_voucher_attachment"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_voucher_draft_attachment" in compact
    assert "unique (tenant_id, voucher_id, object_ref)" in compact
    for forbidden in ("binary_data", "presigned_url", "secret_key", "filesystem_path"):
        assert forbidden not in compact


def test_zero_attachments_do_not_call_resolver_or_database(factory) -> None:
    resolver = Resolver()
    repository = SqlAlchemyEosAttachmentRepository(factory, resolver)
    assert repository.attach_many(
        tenant_id="tenant-a", voucher_id=VOUCHER_ID, attachments=()
    ) == []
    assert resolver.calls == []


def test_one_and_many_attachments_require_fresh_matching_resolution(factory) -> None:
    _seed_voucher(factory)
    resolver = Resolver()
    repository = SqlAlchemyEosAttachmentRepository(factory, resolver)
    values = (
        _attachment(),
        _attachment(
            attachment_id="85000000-0000-4000-8000-000000000002",
            object_ref="objref:ownerissuedopaque0002",
        ),
    )
    attached = repository.attach_many(
        tenant_id="tenant-a", voucher_id=VOUCHER_ID, attachments=values
    )

    assert len(attached) == len(resolver.calls) == 2
    assert all(call["requester_service"] == "nex-eos" for call in resolver.calls)
    assert all(
        call["required_purpose"] == "EOS_VOUCHER_ATTACHMENT"
        for call in resolver.calls
    )
    loaded = repository.list_attachments(
        tenant_id="tenant-a", voucher_id=VOUCHER_ID
    )
    assert [item["object_ref"] for item in loaded] == [
        "objref:ownerissuedopaque0001",
        "objref:ownerissuedopaque0002",
    ]
    assert all(item["resolver_authenticated"] is True for item in loaded)


@pytest.mark.parametrize(
    "overrides",
    (
        {"tenant_id": "tenant-b"},
        {"object_ref": "objref:differentopaque0001"},
        {"purpose": "CX_DOCUMENT"},
        {"status": "QUARANTINED"},
        {"authenticated": False},
        {"immutable": False},
        {"content_sha256": "b" * 64},
        {"size_bytes": 129},
        {"media_type": "image/png"},
    ),
)
def test_cross_tenant_state_auth_and_metadata_mismatches_are_denied(
    factory, overrides
) -> None:
    _seed_voucher(factory)
    repository = SqlAlchemyEosAttachmentRepository(
        factory, Resolver(overrides=overrides)
    )
    with pytest.raises(EosAttachmentError) as error:
        repository.attach_many(
            tenant_id="tenant-a",
            voucher_id=VOUCHER_ID,
            attachments=(_attachment(),),
        )
    assert error.value.error_code == "EOS_ATTACHMENT_OBJECT_REJECTED"


@pytest.mark.parametrize(
    "object_ref",
    (
        "https://storage.example/object",
        "s3://bucket/private-object",
        "/data/private-object",
        "objref:secret_key_material",
        "AKIA1234567890ABCDEF",
        "short",
    ),
)
def test_url_path_credential_and_nonopaque_refs_are_denied(factory, object_ref) -> None:
    repository = SqlAlchemyEosAttachmentRepository(factory, Resolver())
    with pytest.raises(EosAttachmentError) as error:
        repository.attach_many(
            tenant_id="tenant-a",
            voucher_id=VOUCHER_ID,
            attachments=(_attachment(object_ref=object_ref),),
        )
    assert error.value.error_code == "EOS_ATTACHMENT_INVALID"


@pytest.mark.parametrize(
    "overrides",
    (
        {"attachment_id": "bad"},
        {"display_name": " "},
        {"media_type": "not-media"},
        {"size_bytes": -1},
        {"size_bytes": True},
        {"content_sha256": "A" * 64},
        {"evidence_ref": "bad ref"},
    ),
)
def test_attachment_metadata_validation_fails_closed(factory, overrides) -> None:
    _seed_voucher(factory)
    repository = SqlAlchemyEosAttachmentRepository(factory, Resolver())
    with pytest.raises(EosAttachmentError) as error:
        repository.attach_many(
            tenant_id="tenant-a",
            voucher_id=VOUCHER_ID,
            attachments=(_attachment(**overrides),),
        )
    assert error.value.error_code == "EOS_ATTACHMENT_INVALID"


def test_resolver_unavailable_and_unknown_voucher_fail_closed(factory) -> None:
    unavailable = SqlAlchemyEosAttachmentRepository(
        factory, Resolver(error=RuntimeError("private endpoint"))
    )
    with pytest.raises(EosAttachmentError) as resolver_error:
        unavailable.attach_many(
            tenant_id="tenant-a",
            voucher_id=VOUCHER_ID,
            attachments=(_attachment(),),
        )
    assert resolver_error.value.error_code == "EOS_ATTACHMENT_RESOLVER_UNAVAILABLE"
    assert "private endpoint" not in resolver_error.value.detail

    missing = SqlAlchemyEosAttachmentRepository(factory, Resolver())
    with pytest.raises(EosAttachmentError) as voucher_error:
        missing.attach_many(
            tenant_id="tenant-a",
            voucher_id=VOUCHER_ID,
            attachments=(_attachment(),),
        )
    assert voucher_error.value.error_code == "EOS_ATTACHMENT_VOUCHER_NOT_FOUND"


def test_request_duplicates_and_persisted_conflict_are_denied(factory) -> None:
    _seed_voucher(factory)
    repository = SqlAlchemyEosAttachmentRepository(factory, Resolver())
    duplicate_id = (
        _attachment(),
        _attachment(object_ref="objref:ownerissuedopaque0002"),
    )
    with pytest.raises(EosAttachmentError) as duplicate:
        repository.attach_many(
            tenant_id="tenant-a", voucher_id=VOUCHER_ID, attachments=duplicate_id
        )
    assert duplicate.value.error_code == "EOS_ATTACHMENT_INVALID"

    duplicate_object = (
        _attachment(),
        _attachment(
            attachment_id="85000000-0000-4000-8000-000000000002"
        ),
    )
    with pytest.raises(EosAttachmentError) as duplicate_ref:
        repository.attach_many(
            tenant_id="tenant-a",
            voucher_id=VOUCHER_ID,
            attachments=duplicate_object,
        )
    assert duplicate_ref.value.error_code == "EOS_ATTACHMENT_INVALID"

    repository.attach_many(
        tenant_id="tenant-a", voucher_id=VOUCHER_ID, attachments=(_attachment(),)
    )
    with pytest.raises(EosAttachmentError) as conflict:
        repository.attach_many(
            tenant_id="tenant-a",
            voucher_id=VOUCHER_ID,
            attachments=(
                _attachment(
                    attachment_id="85000000-0000-4000-8000-000000000002"
                ),
            ),
        )
    assert conflict.value.error_code == "EOS_ATTACHMENT_CONFLICT"


def test_invalid_sequence_result_and_database_errors_are_redacted(factory) -> None:
    repository = SqlAlchemyEosAttachmentRepository(factory, Resolver())
    for attachments in ("bad", 42, (object(),)):
        with pytest.raises(EosAttachmentError) as invalid:
            repository.attach_many(
                tenant_id="tenant-a",
                voucher_id=VOUCHER_ID,
                attachments=attachments,
            )
        assert invalid.value.error_code == "EOS_ATTACHMENT_INVALID"

    invalid_result = SqlAlchemyEosAttachmentRepository(
        factory, Resolver()
    )
    invalid_result._resolver.resolve_object_ref = lambda **_kwargs: object()  # type: ignore[method-assign]
    with pytest.raises(EosAttachmentError) as rejected:
        invalid_result.attach_many(
            tenant_id="tenant-a",
            voucher_id=VOUCHER_ID,
            attachments=(_attachment(),),
        )
    assert rejected.value.error_code == "EOS_ATTACHMENT_OBJECT_REJECTED"

    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            raise SQLAlchemyError("private attachment read")

    broken = SqlAlchemyEosAttachmentRepository(
        lambda: BrokenSession(), Resolver()  # type: ignore[arg-type]
    )
    with pytest.raises(EosAttachmentError) as error:
        broken.list_attachments(tenant_id="tenant-a", voucher_id=VOUCHER_ID)
    assert error.value.error_code == "EOS_ATTACHMENT_PERSISTENCE_FAILED"
    assert "private attachment read" not in error.value.detail

    class BrokenWriteSession:
        def execute(self, _statement, *_args):
            raise SQLAlchemyError("private attachment write")

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    broken_write = SqlAlchemyEosAttachmentRepository(
        lambda: BrokenWriteSession(), Resolver()  # type: ignore[arg-type]
    )
    with pytest.raises(EosAttachmentError) as write_error:
        broken_write.attach_many(
            tenant_id="tenant-a",
            voucher_id=VOUCHER_ID,
            attachments=(_attachment(),),
        )
    assert write_error.value.error_code == "EOS_ATTACHMENT_PERSISTENCE_FAILED"
    assert "private attachment write" not in write_error.value.detail
