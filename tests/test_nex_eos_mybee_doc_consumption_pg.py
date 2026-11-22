from __future__ import annotations

import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from nex_eos import (
    EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE,
    EOS_APPROVED_DOCUMENT_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_METADATA,
    EOS_OUTBOX_TABLE,
    ApprovedDocumentConsumptionInput,
    EosApprovedDocumentConsumptionAdapter,
    EosApprovedDocumentConsumptionError,
    EosBusinessOperationError,
    EosBusinessOperationRequest,
    SqlAlchemyEosApprovedDocumentRepository,
    SqlAlchemyEosBusinessTransactionCoordinator,
    approved_document_consumption_hash,
    approved_document_source_identity_hash,
)
from nex_runtime import psycopg_database_url
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, func, make_url, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from test_nex_eos_mybee_document_envelope import (
    COMPANY_ID,
    ENVELOPE_ID,
    TENANT,
)
from test_nex_eos_mybee_document_envelope import (
    _build_runtime as build_s2_01_runtime,
)
from test_nex_eos_mybee_document_envelope import (
    _value as s2_01_value,
)

NOW = datetime(2026, 11, 11, 5, 0, tzinfo=UTC)
CREATED_OPERATION_ID = "24000000-0000-4000-8000-000000000001"
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S2_04_POSTGRES_SMOKE") == "1"


def _runtime():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions.begin() as session:
        session.execute(
            EOS_BUSINESS_OPERATION_TABLE.insert().values(
                tenant_id=TENANT,
                business_operation_id=CREATED_OPERATION_ID,
                idempotency_key="s2-04-envelope-seed",
                operation="APPROVE_BUSINESS_DOCUMENT",
                payload_hash="sha256:" + "1" * 64,
                commit_state="COMMITTED",
                result_json={},
                created_at=NOW - timedelta(days=2),
                committed_at=NOW - timedelta(days=2),
            )
        )
        session.execute(
            EOS_APPROVED_DOCUMENT_TABLE.insert().values(
                tenant_id=TENANT,
                envelope_id=ENVELOPE_ID,
                company_id=COMPANY_ID,
                approved_document_id="proposal-s2-04",
                document_revision=1,
                document_type="BUSINESS_PROPOSAL",
                work_code="FL0004011",
                document_content_hash="sha256:" + "2" * 64,
                attachment_manifest_hash="sha256:" + "3" * 64,
                business_approval_proof_id=str(uuid.uuid4()),
                business_proof_hash="sha256:" + "4" * 64,
                approval_policy_id=str(uuid.uuid4()),
                approval_policy_version=1,
                approval_policy_hash="sha256:" + "5" * 64,
                scope_type="COMPANY",
                project_set_hash="sha256:" + "6" * 64,
                allowed_project_ids=[],
                approved_amount=Decimal("100.0000"),
                approved_currency="KRW",
                tolerance_policy_hash=None,
                valid_from=NOW - timedelta(days=1),
                valid_until=NOW + timedelta(days=30),
                state="ACTIVE",
                approved_at=NOW - timedelta(days=2),
                approved_by_ref_type="oa.user",
                approved_by_id="approver-s2-04",
                source_work_item_ref="wc.approval-work-item:s2-04",
                payload_hash="sha256:" + "7" * 64,
                created_business_operation_id=CREATED_OPERATION_ID,
                created_at=NOW - timedelta(days=2),
            )
        )
    return engine, sessions


def _value(
    *,
    operation_id: str,
    sequence: int = 1,
    amount: str = "40.0000",
    **overrides,
) -> ApprovedDocumentConsumptionInput:
    values = {
        "tenant_id": TENANT,
        "consumption_id": f"24000000-0000-4000-8000-{sequence:012d}",
        "company_id": COMPANY_ID,
        "envelope_id": ENVELOPE_ID,
        "source_document_line_ref": f"invoice-line-{sequence}",
        "supplier_invoice_ref": f"supplier-invoice-{sequence}",
        "payroll_period_ref": None,
        "candidate_revision_id": f"24000000-0000-4001-8000-{sequence:012d}",
        "posted_journal_id": f"24000000-0000-4002-8000-{sequence:012d}",
        "consumed_amount": Decimal(amount),
        "currency": "KRW",
        "operation_id": operation_id,
        "reversed_journal_ref": None,
    }
    values.update(overrides)
    return ApprovedDocumentConsumptionInput(**values)


def _execute(
    sessions,
    value: ApprovedDocumentConsumptionInput,
    *,
    adapter: EosApprovedDocumentConsumptionAdapter | None = None,
):
    adapter = adapter or EosApprovedDocumentConsumptionAdapter(clock=lambda: NOW)
    coordinator = SqlAlchemyEosBusinessTransactionCoordinator(
        sessions, clock=lambda: NOW
    )
    request = EosBusinessOperationRequest(
        tenant_id=value.tenant_id,
        business_operation_id=value.operation_id,
        idempotency_key=f"post-{value.operation_id}",
        operation="POST_APPROVED_DOCUMENT",
        payload_hash=semantic_sha256_hash_ref(
            {
                "candidate_revision_id": value.candidate_revision_id,
                "amount": str(value.consumed_amount),
            }
        ),
    )

    def mutation(session):
        projection, created = adapter.consume_in_session(session, value)
        return {"consumption": projection, "consumption_created": created}

    return coordinator.execute(request, mutation)


def test_s2_04_migration_identity_and_transaction_only_boundary() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2529_eos_approved_document_consumption"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_approved_document_consumption" in compact
    assert "ux_eos_doc_cons_candidate" in compact
    assert "ux_eos_doc_cons_source" in compact
    assert "eos_guard_doc_cons_immutable" in compact
    assert all(
        constraint.name is None or len(constraint.name) <= 63
        for constraint in EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.constraints
    )
    adapter = EosApprovedDocumentConsumptionAdapter(clock=lambda: NOW)
    with pytest.raises(EosApprovedDocumentConsumptionError) as error:
        adapter.consume_in_session(
            None,
            _value(operation_id=str(uuid.uuid4())),
        )
    assert error.value.status_code == 422


def test_partial_consumption_updates_remaining_amount_and_exact_replay() -> None:
    _engine, sessions = _runtime()
    first = _value(operation_id=str(uuid.uuid4()), amount="40")
    first_result = _execute(sessions, first)
    assert first_result.result["consumption_created"] is True
    assert first_result.result["consumption"]["remaining_amount"] == "60.0000"

    second = _value(operation_id=str(uuid.uuid4()), sequence=2, amount="60")
    second_result = _execute(sessions, second)
    assert second_result.result["consumption"]["consumed_total"] == "100.0000"
    projection = SqlAlchemyEosApprovedDocumentRepository(
        sessions, clock=lambda: NOW
    ).get(tenant_id=TENANT, envelope_id=ENVELOPE_ID)
    assert projection is not None
    assert projection["remaining_amount"] == "0.0000"

    replay = _execute(sessions, second)
    assert replay.created is False
    with sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(
                EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE
            )
        ) == 2


def test_adapter_exact_replay_in_same_transaction_and_hash_helpers() -> None:
    _engine, sessions = _runtime()
    operation_id = str(uuid.uuid4())
    value = _value(operation_id=operation_id)
    adapter = EosApprovedDocumentConsumptionAdapter(clock=lambda: NOW)
    coordinator = SqlAlchemyEosBusinessTransactionCoordinator(
        sessions, clock=lambda: NOW
    )

    def mutation(session):
        first, first_created = adapter.consume_in_session(session, value)
        replay, replay_created = adapter.consume_in_session(session, value)
        assert replay == first
        return {"first": first_created, "replay": replay_created}

    result = coordinator.execute(
        EosBusinessOperationRequest(
            TENANT,
            operation_id,
            f"post-{operation_id}",
            "POST_APPROVED_DOCUMENT",
            "sha256:" + "8" * 64,
        ),
        mutation,
    )
    assert result.result == {"first": True, "replay": False}
    source_hash = approved_document_source_identity_hash(
        source_document_line_ref="invoice-line-1",
        supplier_invoice_ref="supplier-invoice-1",
        payroll_period_ref=None,
    )
    assert source_hash.startswith("sha256:")
    assert approved_document_consumption_hash(
        {"source_identity_hash": source_hash}
    ).startswith("sha256:")


def test_over_consumption_duplicate_source_and_candidate_drift_fail_closed() -> None:
    _engine, sessions = _runtime()
    first = _value(operation_id=str(uuid.uuid4()), amount="70")
    _execute(sessions, first)

    with pytest.raises(EosApprovedDocumentConsumptionError) as exceeded:
        _execute(
            sessions,
            _value(operation_id=str(uuid.uuid4()), sequence=2, amount="31"),
        )
    assert exceeded.value.error_code == "EOS_APPROVED_DOCUMENT_ALLOWANCE_EXCEEDED"

    duplicate_source = _value(
        operation_id=str(uuid.uuid4()),
        sequence=3,
        amount="10",
        source_document_line_ref=first.source_document_line_ref,
        supplier_invoice_ref=first.supplier_invoice_ref,
    )
    with pytest.raises(EosApprovedDocumentConsumptionError) as duplicate:
        _execute(sessions, duplicate_source)
    assert duplicate.value.status_code == 409

    drift = _value(
        operation_id=str(uuid.uuid4()),
        sequence=4,
        amount="10",
        candidate_revision_id=first.candidate_revision_id,
    )
    with pytest.raises(EosApprovedDocumentConsumptionError) as candidate:
        _execute(sessions, drift)
    assert candidate.value.status_code == 409


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"currency": "USD"}, "EOS_APPROVED_DOCUMENT_CURRENCY_MISMATCH"),
        ({"company_id": str(uuid.uuid4())}, "EOS_APPROVED_DOCUMENT_CONSUMPTION_CONFLICT"),
        ({"tenant_id": "other-tenant"}, "EOS_APPROVED_DOCUMENT_CONSUMPTION_NOT_FOUND"),
        ({"envelope_id": str(uuid.uuid4())}, "EOS_APPROVED_DOCUMENT_CONSUMPTION_NOT_FOUND"),
    ],
)
def test_scope_currency_and_missing_envelope_rejections(overrides, error_code) -> None:
    _engine, sessions = _runtime()
    value = _value(operation_id=str(uuid.uuid4()), **overrides)
    with pytest.raises(EosApprovedDocumentConsumptionError) as error:
        _execute(sessions, value)
    assert error.value.error_code == error_code


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": " bad"},
        {"consumption_id": "not-a-uuid"},
        {"company_id": "not-a-uuid"},
        {"candidate_revision_id": "not-a-uuid"},
        {"posted_journal_id": "not-a-uuid"},
        {"operation_id": "not-a-uuid"},
        {"reversed_journal_ref": "not-a-uuid"},
        {"source_document_line_ref": " bad"},
        {"supplier_invoice_ref": ""},
        {"payroll_period_ref": "bad\nref"},
        {"consumed_amount": Decimal(0)},
        {"consumed_amount": Decimal("1.00001")},
        {"consumed_amount": Decimal("NaN")},
        {"consumed_amount": object()},
        {"consumed_amount": Decimal("1E+1000000")},
        {"currency": "krw"},
    ],
)
def test_invalid_consumption_input_is_rejected(overrides) -> None:
    _engine, sessions = _runtime()
    values = {"operation_id": str(uuid.uuid4()), **overrides}
    value = _value(**values)
    adapter = EosApprovedDocumentConsumptionAdapter(clock=lambda: NOW)
    with (
        sessions.begin() as session,
        pytest.raises(EosApprovedDocumentConsumptionError) as error,
    ):
        adapter.consume_in_session(session, value)
    assert error.value.status_code == 422


def test_invalid_clock_and_hash_money_fail_closed() -> None:
    _engine, sessions = _runtime()
    value = _value(operation_id=str(uuid.uuid4()))
    adapter = EosApprovedDocumentConsumptionAdapter(clock=lambda: "not-a-datetime")
    with (
        sessions.begin() as session,
        pytest.raises(EosApprovedDocumentConsumptionError) as clock_error,
    ):
        adapter.consume_in_session(session, value)
    assert clock_error.value.status_code == 422

    for invalid in ("not-a-decimal", Decimal("NaN")):
        with pytest.raises(EosApprovedDocumentConsumptionError) as amount_error:
            approved_document_consumption_hash({"consumed_amount": invalid})
        assert amount_error.value.status_code == 409


@pytest.mark.parametrize(
    "envelope_changes",
    [
        {"state": "REVOKED"},
        {"valid_from": NOW + timedelta(seconds=1)},
        {"valid_until": NOW},
    ],
)
def test_inactive_or_out_of_window_envelope_is_rejected(envelope_changes) -> None:
    _engine, sessions = _runtime()
    with sessions.begin() as session:
        session.execute(
            EOS_APPROVED_DOCUMENT_TABLE.update()
            .where(EOS_APPROVED_DOCUMENT_TABLE.c.tenant_id == TENANT)
            .values(**envelope_changes)
        )
    with pytest.raises(EosApprovedDocumentConsumptionError) as error:
        _execute(sessions, _value(operation_id=str(uuid.uuid4())))
    assert error.value.status_code == 409


def test_mutation_failure_rolls_back_consumption_operation_and_outbox() -> None:
    _engine, sessions = _runtime()
    operation_id = str(uuid.uuid4())
    value = _value(operation_id=operation_id)
    adapter = EosApprovedDocumentConsumptionAdapter(clock=lambda: NOW)
    coordinator = SqlAlchemyEosBusinessTransactionCoordinator(
        sessions, clock=lambda: NOW
    )

    def mutation(session):
        adapter.consume_in_session(session, value)
        raise RuntimeError("journal commit failed")

    with pytest.raises(EosBusinessOperationError) as error:
        coordinator.execute(
            EosBusinessOperationRequest(
                TENANT,
                operation_id,
                f"post-{operation_id}",
                "POST_APPROVED_DOCUMENT",
                "sha256:" + "9" * 64,
            ),
            mutation,
        )
    assert error.value.error_code == "EOS_BUSINESS_MUTATION_FAILED"
    with sessions() as session:
        for table in (
            EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE,
            EOS_IDEMPOTENCY_TABLE,
            EOS_OUTBOX_TABLE,
        ):
            assert session.scalar(select(func.count()).select_from(table)) == 0
        assert session.scalar(
            select(func.count())
            .select_from(EOS_BUSINESS_OPERATION_TABLE)
            .where(EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id == operation_id)
        ) == 0


def test_requires_matching_pending_operation_and_persistence_failure_is_typed() -> None:
    _engine, sessions = _runtime()
    value = _value(operation_id=CREATED_OPERATION_ID)
    adapter = EosApprovedDocumentConsumptionAdapter(clock=lambda: NOW)
    with (
        sessions.begin() as session,
        pytest.raises(EosApprovedDocumentConsumptionError) as error,
    ):
        adapter.consume_in_session(session, value)
    assert error.value.status_code == 409

    class BrokenSession:
        def execute(self, *_args, **_kwargs):
            from sqlalchemy.exc import OperationalError

            raise OperationalError("select", {}, RuntimeError("offline"))

    with pytest.raises(EosApprovedDocumentConsumptionError) as unavailable:
        adapter.consume_in_session(BrokenSession(), value)  # type: ignore[arg-type]
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected S2-04 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_row_lock_overspend_guard_and_immutability() -> None:
    schema_name = f"mybee_s204_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with psycopg.connect(psycopg_url, autocommit=True) as connection:
        assert connection.execute(
            "SELECT current_database(), current_user"
        ).fetchone() == ("nex_eos_test", "nex_eos_user")
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    run_service_migrations("nex-eos", database_url=scoped_url, profile="test")
    engine = create_engine(scoped_url, pool_pre_ping=True, pool_size=4)
    try:
        _runtime_engine, sessions, document = build_s2_01_runtime(
            engine=engine,
            value=s2_01_value(
                approved_amount=Decimal("100.0000"),
                valid_from=NOW - timedelta(hours=1),
                valid_until=NOW + timedelta(days=1),
            ),
        )
        created, was_created = SqlAlchemyEosApprovedDocumentRepository(
            sessions, clock=lambda: NOW
        ).create(document)
        assert was_created is True and created["remaining_amount"] == "100.0000"

        barrier = threading.Barrier(2)
        results: list[str] = []
        errors: list[str] = []
        lock = threading.Lock()

        def consume(sequence: int) -> None:
            try:
                value = _value(
                    operation_id=str(uuid.uuid4()),
                    sequence=sequence,
                    amount="60.0000",
                )
                barrier.wait(timeout=5)
                result = _execute(sessions, value)
                with lock:
                    results.append(result.result["consumption"]["consumption_id"])
            except EosApprovedDocumentConsumptionError as exc:
                with lock:
                    errors.append(exc.error_code)

        threads = [
            threading.Thread(target=consume, args=(10,), daemon=True),
            threading.Thread(target=consume, args=(11,), daemon=True),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        assert all(not thread.is_alive() for thread in threads)
        assert len(results) == 1
        assert errors == ["EOS_APPROVED_DOCUMENT_ALLOWANCE_EXCEEDED"]
        projection = SqlAlchemyEosApprovedDocumentRepository(
            sessions, clock=lambda: NOW
        ).get(tenant_id=TENANT, envelope_id=ENVELOPE_ID)
        assert projection is not None
        assert projection["remaining_amount"] == "40.0000"

        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            with pytest.raises(psycopg.Error):
                connection.execute(
                    sql.SQL(
                        "UPDATE {}.eos_approved_document_consumption "
                        "SET consumed_amount = 1"
                    ).format(sql.Identifier(schema_name))
                )
            with pytest.raises(psycopg.Error):
                connection.execute(
                    sql.SQL(
                        "DELETE FROM {}.eos_approved_document_consumption"
                    ).format(sql.Identifier(schema_name))
                )
    finally:
        engine.dispose()
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
