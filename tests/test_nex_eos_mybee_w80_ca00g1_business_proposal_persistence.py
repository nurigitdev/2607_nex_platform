from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from nex_eos import (
    EOS_BUSINESS_PROPOSAL_REVISION_TABLE,
    EOS_METADATA,
    BusinessProposalRevisionInput,
    BusinessProposalSubmissionInput,
    EosBusinessProposalError,
    LegalEntityInput,
    SqlAlchemyEosBusinessProposalRepository,
    SqlAlchemyEosLegalEntityRepository,
    build_eos_database_runtime,
)
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, make_url, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "VO00"
PROPOSAL_ID = "d1000000-0000-4000-8000-000000000001"
COMPANY_ID = "d2000000-0000-4000-8000-000000000001"
PROJECT_ID = "d3000000-0000-4000-8000-000000000001"
PROJECT_CODE = "VO00D260001"
REQUESTER = "employee-8101"
NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_W80_CA00G1_POSTGRES_SMOKE") == "1"


@pytest.fixture
def repository():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield SqlAlchemyEosBusinessProposalRepository(factory), factory
    engine.dispose()


def _draft(**overrides) -> BusinessProposalRevisionInput:
    values = {
        "tenant_id": TENANT,
        "proposal_id": PROPOSAL_ID,
        "revision_id": str(uuid.uuid4()),
        "company_id": COMPANY_ID,
        "requester_subject_id": REQUESTER,
        "document_type": "EXPENSE_PROPOSAL",
        "work_code": "FL0004001",
        "title": "외부 용역비 사용 품의",
        "purpose": "프로젝트 외부 용역비 집행",
        "business_justification": "납기 준수를 위해 외부 전문 인력이 필요합니다.",
        "transaction_type": "EXTERNAL_LABOR",
        "requested_amount": Decimal("10000.00"),
        "original_currency": "USD",
        "valid_from": NOW,
        "valid_until": NOW + timedelta(days=30),
        "scope_type": "PROJECT",
        "project_ids": (PROJECT_ID,),
        "project_codes": (PROJECT_CODE,),
        "attachment_manifest": (
            {
                "object_ref": "s3://private/vo00/proposal/quote.pdf",
                "size": 1024,
                "media_type": "application/pdf",
                "content_hash": "sha256:" + "a" * 64,
            },
        ),
    }
    values.update(overrides)
    return BusinessProposalRevisionInput(**values)


def test_create_revise_exact_replay_and_owner_projection(repository) -> None:
    proposals, factory = repository
    initial = _draft()
    created = proposals.create_draft(initial, created_at=NOW)
    assert created["state"] == "DRAFT"
    assert created["current_revision_no"] == 1
    assert created["version"] == 1
    assert created["current_revision"]["project_codes"] == [PROJECT_CODE]
    assert created["current_revision"]["requested_amount"] == "10000.0000"
    assert created["current_revision"]["content_hash"].startswith("sha256:")
    assert created["current_revision"]["attachment_manifest_hash"].startswith("sha256:")
    assert created["current_revision"]["policy_selection_input_hash"].startswith(
        "sha256:"
    )

    replay = proposals.create_draft(replace(initial, revision_id=str(uuid.uuid4())))
    assert replay == created
    with pytest.raises(EosBusinessProposalError) as conflicting_identity:
        proposals.create_draft(
            replace(initial, revision_id=str(uuid.uuid4()), title="다른 의미")
        )
    assert conflicting_identity.value.error_code == "BUSINESS_PROPOSAL_CONFLICT"

    revised = proposals.revise_draft(
        replace(
            initial,
            revision_id=str(uuid.uuid4()),
            requested_amount=Decimal(12000),
            business_justification="추가 범위를 포함한 외부 전문 인력이 필요합니다.",
        ),
        expected_version=1,
        expected_revision=1,
        actor_subject_id=REQUESTER,
    )
    assert revised["current_revision_no"] == 2
    assert revised["version"] == 2
    assert revised["current_revision"]["predecessor_revision_no"] == 1
    assert revised["current_revision"]["requested_amount"] == "12000.0000"
    assert (
        revised["current_revision"]["content_hash"]
        != created["current_revision"]["content_hash"]
    )

    with factory() as session:
        revisions = session.execute(
            select(
                EOS_BUSINESS_PROPOSAL_REVISION_TABLE.c.revision_no,
                EOS_BUSINESS_PROPOSAL_REVISION_TABLE.c.content_hash,
            ).order_by(EOS_BUSINESS_PROPOSAL_REVISION_TABLE.c.revision_no)
        ).all()
    assert [row.revision_no for row in revisions] == [1, 2]
    assert (
        proposals.get(
            tenant_id=TENANT,
            proposal_id=PROPOSAL_ID,
            requester_subject_id=REQUESTER,
        )
        == revised
    )
    assert (
        proposals.get(
            tenant_id=TENANT,
            proposal_id=PROPOSAL_ID,
            requester_subject_id="employee-other",
        )
        is None
    )
    assert [
        item["proposal_id"]
        for item in proposals.list_owner(
            tenant_id=TENANT,
            requester_subject_id=REQUESTER,
            states=("DRAFT",),
        )
    ] == [PROPOSAL_ID]


def test_revision_is_owner_scoped_and_optimistically_locked(repository) -> None:
    proposals, _factory = repository
    initial = _draft()
    proposals.create_draft(initial, created_at=NOW)
    changed = replace(
        initial,
        revision_id=str(uuid.uuid4()),
        title="수정 품의",
    )
    with pytest.raises(EosBusinessProposalError) as denied:
        proposals.revise_draft(
            changed,
            expected_version=1,
            expected_revision=1,
            actor_subject_id="employee-other",
        )
    assert denied.value.status_code == 403

    with pytest.raises(EosBusinessProposalError) as stale:
        proposals.revise_draft(
            changed,
            expected_version=2,
            expected_revision=1,
            actor_subject_id=REQUESTER,
        )
    assert stale.value.error_code == "BUSINESS_PROPOSAL_VERSION_CONFLICT"

    proposals.revise_draft(
        changed,
        expected_version=1,
        expected_revision=1,
        actor_subject_id=REQUESTER,
    )
    assert (
        proposals.revise_draft(
            replace(changed, revision_id=str(uuid.uuid4())),
            expected_version=2,
            expected_revision=2,
            actor_subject_id=REQUESTER,
        )["current_revision_no"]
        == 2
    )

    with pytest.raises(EosBusinessProposalError) as missing:
        proposals.revise_draft(
            replace(changed, proposal_id=str(uuid.uuid4())),
            expected_version=1,
            expected_revision=1,
            actor_subject_id=REQUESTER,
        )
    assert missing.value.error_code == "BUSINESS_PROPOSAL_NOT_FOUND"


def test_revision_rejects_submitted_state_and_immutable_identity(repository) -> None:
    proposals, factory = repository
    initial = _draft()
    proposals.create_draft(initial, created_at=NOW)
    with pytest.raises(EosBusinessProposalError, match="immutable"):
        proposals.revise_draft(
            replace(
                initial,
                revision_id=str(uuid.uuid4()),
                company_id=str(uuid.uuid4()),
            ),
            expected_version=1,
            expected_revision=1,
            actor_subject_id=REQUESTER,
        )
    with factory.begin() as session:
        session.execute(
            update(proposals_table())
            .where(proposals_table().c.proposal_id == PROPOSAL_ID)
            .values(state="SUBMITTED")
        )
    with pytest.raises(EosBusinessProposalError, match="DRAFT or REJECTED"):
        proposals.revise_draft(
            replace(initial, revision_id=str(uuid.uuid4()), title="Too late"),
            expected_version=1,
            expected_revision=1,
            actor_subject_id=REQUESTER,
        )


def test_revision_rejects_invalid_scope_attachment_and_time(repository) -> None:
    proposals, _factory = repository
    cases = (
        _draft(scope_type="PROJECT_SET"),
        _draft(project_codes=()),
        _draft(
            attachment_manifest=(
                {
                    "object_ref": "s3://private/vo00/proposal/quote.pdf",
                    "size": 1,
                    "media_type": "application/pdf",
                    "content_hash": "not-a-hash",
                },
            )
        ),
        _draft(valid_until=NOW),
    )
    for value in cases:
        with pytest.raises(EosBusinessProposalError) as invalid:
            proposals.create_draft(value)
        assert invalid.value.error_code == "BUSINESS_PROPOSAL_INVALID"
        assert invalid.value.status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"proposal_id": "bad"},
        {"title": ""},
        {"work_code": "BAD"},
        {"original_currency": "US"},
        {"scope_type": "PERSONAL"},
        {"project_codes": ("bad-code",)},
        {"requested_amount": "not-money"},
        {"requested_amount": Decimal(0)},
        {"valid_from": NOW.replace(tzinfo=None)},
        {
            "attachment_manifest": (
                {
                    "object_ref": "s3://duplicate",
                    "size": 1,
                    "media_type": "text/plain",
                    "content_hash": "sha256:" + "1" * 64,
                },
                {
                    "object_ref": "s3://duplicate",
                    "size": 2,
                    "media_type": "text/plain",
                    "content_hash": "sha256:" + "2" * 64,
                },
            )
        },
        {"attachment_manifest": ("not-an-object",)},
        {
            "attachment_manifest": (
                {
                    "object_ref": "s3://invalid-size",
                    "size": -1,
                    "media_type": "text/plain",
                    "content_hash": "sha256:" + "1" * 64,
                },
            )
        },
    ],
)
def test_malformed_proposal_fields_fail_closed(repository, overrides) -> None:
    proposals, _factory = repository
    with pytest.raises(EosBusinessProposalError) as invalid:
        proposals.create_draft(_draft(**overrides))
    assert invalid.value.error_code == "BUSINESS_PROPOSAL_INVALID"


def test_company_and_project_set_scopes_and_unfiltered_owner_list(repository) -> None:
    proposals, _factory = repository
    company = proposals.create_draft(
        _draft(
            proposal_id=str(uuid.uuid4()),
            scope_type="COMPANY",
            project_ids=(),
            project_codes=(),
        )
    )
    project_set = proposals.create_draft(
        _draft(
            proposal_id=str(uuid.uuid4()),
            scope_type="PROJECT_SET",
            project_ids=(PROJECT_ID, "d3000000-0000-4000-8000-000000000002"),
            project_codes=(PROJECT_CODE, "VO00D260002"),
        )
    )
    assert company["current_revision"]["scope_type"] == "COMPANY"
    assert project_set["current_revision"]["scope_type"] == "PROJECT_SET"
    assert (
        len(
            proposals.list_owner(
                tenant_id=TENANT,
                requester_subject_id=REQUESTER,
            )
        )
        == 2
    )
    assert proposals.get(tenant_id=TENANT, proposal_id=str(uuid.uuid4())) is None
    with pytest.raises(EosBusinessProposalError):
        proposals.list_owner(
            tenant_id=TENANT,
            requester_subject_id=REQUESTER,
            states=("UNKNOWN",),
        )


def test_duplicate_revision_identity_and_unavailable_database_fail_closed(
    repository,
) -> None:
    proposals, factory = repository
    initial = _draft()
    proposals.create_draft(initial, created_at=NOW)
    with pytest.raises(EosBusinessProposalError) as duplicate:
        proposals.create_draft(
            replace(
                initial,
                proposal_id=str(uuid.uuid4()),
                title="Different proposal",
            )
        )
    assert duplicate.value.error_code == "BUSINESS_PROPOSAL_CONFLICT"

    factory.kw["bind"].dispose()
    factory.kw["bind"] = create_engine("sqlite+pysqlite:///:memory:")
    with pytest.raises(EosBusinessProposalError) as unavailable:
        proposals.get(tenant_id=TENANT, proposal_id=PROPOSAL_ID)
    assert unavailable.value.error_code == "BUSINESS_PROPOSAL_PERSISTENCE_UNAVAILABLE"
    assert unavailable.value.retryable is True


def test_rejected_revision_returns_to_draft_without_mutating_history(
    repository,
) -> None:
    proposals, factory = repository
    initial = _draft()
    proposals.create_draft(initial, created_at=NOW)
    with factory.begin() as session:
        session.execute(
            update(proposals_table())
            .where(proposals_table().c.proposal_id == PROPOSAL_ID)
            .values(
                state="REJECTED",
                submitted_revision_no=1,
                approval_policy_id=str(uuid.uuid4()),
                approval_policy_hash="sha256:" + "b" * 64,
                approval_line_hash="sha256:" + "c" * 64,
                approval_case_id=str(uuid.uuid4()),
                version=2,
                decided_at=NOW + timedelta(hours=1),
            )
        )
    revised = proposals.revise_draft(
        replace(initial, revision_id=str(uuid.uuid4()), title="반려 보완 품의"),
        expected_version=2,
        expected_revision=1,
        actor_subject_id=REQUESTER,
    )
    assert revised["state"] == "DRAFT"
    assert revised["submitted_revision_no"] is None
    assert revised["approval_case_id"] is None
    assert revised["current_revision_no"] == 2


def proposals_table():
    from nex_eos import EOS_BUSINESS_PROPOSAL_TABLE

    return EOS_BUSINESS_PROPOSAL_TABLE


def test_migration_is_admitted_and_protects_revision_history() -> None:
    migrations = load_migrations("nex-eos")
    assert "2549_eos_business_proposal_draft" in {
        migration.version for migration in migrations
    }
    source = Path(
        "database/nex-eos/migrations/2549_eos_business_proposal_draft.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS eos_business_proposal" in source
    assert "CREATE TABLE IF NOT EXISTS eos_business_proposal_revision" in source
    assert "BEFORE UPDATE OR DELETE ON eos_business_proposal_revision" in source
    assert "Business proposal cannot be deleted" in source


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W80-CA00G.1 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_migration_revision_replay_and_zero_residue() -> None:
    schema_name = f"mybee_w80g1_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_eos_test", "nex_eos_user")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    try:
        migration = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2549_eos_business_proposal_draft" in migration.applied
        runtime = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        SqlAlchemyEosLegalEntityRepository(runtime.session_factory).create_legal_entity(
            LegalEntityInput(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                company_code="M1CO",
                name="W80 Acceptance Company",
                functional_currency="KRW",
                presentation_currency="KRW",
                business_timezone="Asia/Seoul",
                effective_from=date(2026, 1, 1),
            )
        )
        proposals = SqlAlchemyEosBusinessProposalRepository(runtime.session_factory)
        created = proposals.create_draft(_draft(), created_at=NOW)
        assert (
            proposals.create_draft(
                replace(_draft(), revision_id=str(uuid.uuid4())), created_at=NOW
            )
            == created
        )
        revised = proposals.revise_draft(
            replace(
                _draft(),
                revision_id=str(uuid.uuid4()),
                title="PostgreSQL 보완 품의",
            ),
            expected_version=1,
            expected_revision=1,
            actor_subject_id=REQUESTER,
        )
        assert revised["current_revision_no"] == 2
        submitted = proposals.submit(
            BusinessProposalSubmissionInput(
                tenant_id=TENANT,
                proposal_id=PROPOSAL_ID,
                requester_subject_id=REQUESTER,
                expected_version=2,
                expected_revision=2,
                content_hash=revised["current_revision"]["content_hash"],
                approval_policy_id="d4000000-0000-4000-8000-000000000001",
                approval_policy_hash="sha256:" + "b" * 64,
                approval_preview_hash="sha256:" + "c" * 64,
                candidate_evidence_hash="sha256:" + "d" * 64,
                approval_line_hash="sha256:" + "e" * 64,
                normalized_amount=Decimal("10000"),
                functional_currency="KRW",
                normalization_hash="sha256:" + "f" * 64,
            ),
            submitted_at=NOW,
        )
        assert submitted["state"] == "SUBMITTED"
        assert submitted["journey"]["current_stage"] == "BUSINESS_APPROVAL"
        assert submitted["submitted_revision_no"] == 2
        assert submitted["approval_preview_hash"] == "sha256:" + "c" * 64
        runtime.dispose()
    finally:
        with (
            psycopg.connect(psycopg_url, autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            cursor.execute("SELECT to_regnamespace(%s)", (schema_name,))
            assert cursor.fetchone() == (None,)
