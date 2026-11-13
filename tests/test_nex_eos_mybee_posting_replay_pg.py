from __future__ import annotations

import copy
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
import test_nex_eos_mybee_voucher_candidate as posting_fixture
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_JOURNAL_HEADER_TABLE,
    EOS_JOURNAL_LINE_TABLE,
    EOS_OUTBOX_TABLE,
    EosJournalOperationError,
    EosJournalOperationService,
    EosJournalOutboxEventError,
    EosJournalPostingError,
    EosOutboxPublicationError,
    EosOutboxPublishReceipt,
    SqlAlchemyEosOutboxPublisher,
    admit_journal_posted_event,
    journal_post_payload_hash,
    parse_journal_post_command,
)
from nex_eos import journal_operations as journal_operations_module
from nex_eos import journal_outbox_events as journal_outbox_events_module
from nex_eos.finance_v2_api import register_finance_v2_routes
from nex_runtime import psycopg_database_url
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, make_url, select, update
from sqlalchemy.exc import SQLAlchemyError

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_W40_S4_04_POSTGRES_SMOKE") == "1"


def _posted_runtime():
    _engine, sessions, candidates, command, _authorization = posting_fixture._runtime()
    command.execute(posting_fixture._payload(), caller=posting_fixture.CALLER)
    service, payload = posting_fixture._prepare_atomic_posting(sessions, candidates)
    result = service.execute(posting_fixture.CANDIDATE_ID, payload)
    return sessions, service, payload, result


def test_ack_loss_reconciles_same_committed_journal_and_exact_replay() -> None:
    sessions, service, payload, committed = _posted_runtime()
    reconciliation = EosJournalOperationService(sessions).reconcile(
        tenant_id=posting_fixture.TENANT,
        business_operation_id=payload["business_operation_id"],
    )
    replay = service.execute(posting_fixture.CANDIDATE_ID, payload)

    assert reconciliation["commit_state"] == "COMMITTED"
    assert reconciliation["reconciliation_status"] == "COMMITTED_CONFIRMED"
    assert reconciliation["verification_status"] == "VERIFIED"
    assert reconciliation["retry_disposition"] == "DO_NOT_REPOST"
    assert reconciliation["new_idempotency_key_allowed"] is False
    assert reconciliation["journal"]["journal_id"] == committed["result"]["journal_id"]
    assert (
        reconciliation["journal"]["journal_hash"] == committed["result"]["journal_hash"]
    )
    assert reconciliation["journal"]["project_codes"] == [posting_fixture.PROJECT_CODE]
    assert reconciliation["outbox"]["projector_state"] == "STALE"
    assert replay["idempotency_disposition"] == "REPLAYED"
    assert replay["result"]["journal_id"] == reconciliation["journal"]["journal_id"]


def test_outbox_ack_loss_never_rolls_back_posted_journal() -> None:
    sessions, _service, payload, committed = _posted_runtime()
    with sessions.begin() as session:
        session.execute(
            update(EOS_OUTBOX_TABLE)
            .where(EOS_OUTBOX_TABLE.c.event_type != "FINANCE.JOURNAL_POSTED.v1")
            .values(
                delivery_state="PUBLISHED",
                attempt_count=1,
                updated_at=posting_fixture.NOW,
                published_at=posting_fixture.NOW,
            )
        )

    class LostAck:
        def publish(self, _event):
            raise OSError("downstream ACK was lost")

    publisher = SqlAlchemyEosOutboxPublisher(sessions)
    failed = publisher.publish_next(LostAck(), tenant_id=posting_fixture.TENANT)
    assert failed is not None
    assert failed.delivery_state == "PENDING"
    assert failed.error_code == "EOS_OUTBOX_ACK_UNCONFIRMED"

    reconciliation = EosJournalOperationService(sessions).reconcile(
        tenant_id=posting_fixture.TENANT,
        business_operation_id=payload["business_operation_id"],
    )
    assert reconciliation["commit_state"] == "COMMITTED"
    assert reconciliation["journal"]["journal_id"] == committed["result"]["journal_id"]
    assert reconciliation["outbox"]["attempt_count"] == 1
    assert reconciliation["outbox"]["projector_state"] == "STALE"
    with sessions() as session:
        assert (
            session.execute(
                select(func.count()).select_from(EOS_JOURNAL_HEADER_TABLE)
            ).scalar_one()
            == 1
        )


def test_outbox_retry_publishes_once_and_reconciliation_becomes_current() -> None:
    sessions, _service, payload, _committed = _posted_runtime()
    with sessions.begin() as session:
        session.execute(
            update(EOS_OUTBOX_TABLE)
            .where(EOS_OUTBOX_TABLE.c.event_type != "FINANCE.JOURNAL_POSTED.v1")
            .values(
                delivery_state="PUBLISHED",
                attempt_count=1,
                updated_at=posting_fixture.NOW,
                published_at=posting_fixture.NOW,
            )
        )

    class Accepted:
        def publish(self, event):
            return EosOutboxPublishReceipt(
                event_id=event.event_id,
                event_payload_hash=event.event_payload_hash,
                receipt_ref="projector:journal-posted:accepted",
            )

    published = SqlAlchemyEosOutboxPublisher(sessions).publish_next(
        Accepted(), tenant_id=posting_fixture.TENANT
    )
    assert published is not None
    assert published.delivery_state == "PUBLISHED"
    assert (
        SqlAlchemyEosOutboxPublisher(sessions).publish_next(
            Accepted(), tenant_id=posting_fixture.TENANT
        )
        is None
    )
    reconciliation = EosJournalOperationService(sessions).reconcile(
        tenant_id=posting_fixture.TENANT,
        business_operation_id=payload["business_operation_id"],
    )
    assert reconciliation["outbox"]["projector_state"] == "CURRENT"


def test_reconciliation_distinguishes_unknown_and_committed_verification_failure() -> (
    None
):
    sessions, _service, payload, _committed = _posted_runtime()
    reconciler = EosJournalOperationService(sessions)
    with sessions.begin() as session:
        session.execute(
            update(EOS_BUSINESS_OPERATION_TABLE)
            .where(
                EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                == payload["business_operation_id"]
            )
            .values(commit_state="PENDING")
        )
    unknown = reconciler.reconcile(
        tenant_id=posting_fixture.TENANT,
        business_operation_id=payload["business_operation_id"],
    )
    assert unknown["commit_state"] == "UNKNOWN_COMMIT_STATE"
    assert unknown["reconciliation_status"] == "RECONCILIATION_REQUIRED"
    assert unknown["journal"] is None

    with sessions.begin() as session:
        session.execute(
            update(EOS_BUSINESS_OPERATION_TABLE)
            .where(
                EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                == payload["business_operation_id"]
            )
            .values(commit_state="COMMITTED")
        )
        session.execute(
            update(EOS_OUTBOX_TABLE)
            .where(
                EOS_OUTBOX_TABLE.c.business_operation_id
                == payload["business_operation_id"]
            )
            .values(event_payload_hash="sha256:" + "0" * 64)
        )
    failed = reconciler.reconcile(
        tenant_id=posting_fixture.TENANT,
        business_operation_id=payload["business_operation_id"],
    )
    assert failed["commit_state"] == "COMMITTED"
    assert failed["reconciliation_status"] == "COMMITTED_VERIFICATION_FAILED"
    assert failed["verification_status"] == "FAILED"
    assert failed["retry_disposition"] == "DO_NOT_REPOST"


def test_reconciliation_api_returns_typed_unknown_and_fail_closed_errors(
    monkeypatch,
) -> None:
    posting_fixture._admit_service_token(monkeypatch)
    sessions, _service, payload, _committed = _posted_runtime()
    with sessions.begin() as session:
        session.execute(
            update(EOS_BUSINESS_OPERATION_TABLE)
            .where(
                EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                == payload["business_operation_id"]
            )
            .values(commit_state="PENDING")
        )
    app = FastAPI()
    register_finance_v2_routes(app)
    app.state.eos_journal_operation_service = EosJournalOperationService(sessions)
    path = (
        "/internal/v2/finance/business-operations/"
        f"{payload['business_operation_id']}/journal-status"
    )
    with TestClient(app) as client:
        unknown = client.get(
            path,
            headers={
                "Authorization": "Bearer service-token",
                "X-NeX-Tenant-Id": posting_fixture.TENANT,
            },
        )
        missing = client.get(
            path.replace(payload["business_operation_id"], str(uuid.uuid4())),
            headers={
                "Authorization": "Bearer service-token",
                "X-NeX-Tenant-Id": posting_fixture.TENANT,
            },
        )
    assert unknown.status_code == 202
    assert unknown.json()["commit_state"] == "UNKNOWN_COMMIT_STATE"
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "EOS_JOURNAL_OPERATION_NOT_FOUND"


def test_reconciliation_rejects_invalid_or_non_journal_operation() -> None:
    sessions, _service, payload, _committed = _posted_runtime()
    reconciler = EosJournalOperationService(sessions)
    with pytest.raises(EosJournalOperationError) as invalid:
        reconciler.reconcile(
            tenant_id="bad tenant",
            business_operation_id=payload["business_operation_id"],
        )
    assert invalid.value.status_code == 422
    with sessions.begin() as session:
        session.execute(
            update(EOS_BUSINESS_OPERATION_TABLE)
            .where(
                EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                == payload["business_operation_id"]
            )
            .values(operation="FINANCE.OTHER.OPERATION")
        )
    with pytest.raises(EosJournalOperationError) as mismatch:
        reconciler.reconcile(
            tenant_id=posting_fixture.TENANT,
            business_operation_id=payload["business_operation_id"],
        )
    assert mismatch.value.status_code == 409


def test_reconciliation_maps_not_committed_and_rejects_invalid_state_or_uuid() -> None:
    sessions, _service, payload, _committed = _posted_runtime()
    reconciler = EosJournalOperationService(sessions)
    with sessions.begin() as session:
        session.execute(
            update(EOS_BUSINESS_OPERATION_TABLE)
            .where(
                EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                == payload["business_operation_id"]
            )
            .values(commit_state="NOT_COMMITTED")
        )
    not_committed = reconciler.reconcile(
        tenant_id=posting_fixture.TENANT,
        business_operation_id=payload["business_operation_id"],
    )
    assert not_committed["commit_state"] == "NOT_COMMITTED"
    assert not_committed["retry_disposition"] == "RETRY_SAME_IDENTITY_ONLY"

    with sessions.begin() as session:
        session.execute(
            update(EOS_BUSINESS_OPERATION_TABLE)
            .where(
                EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                == payload["business_operation_id"]
            )
            .values(commit_state="CORRUPT")
        )
    with pytest.raises(EosJournalOperationError) as corrupt:
        reconciler.reconcile(
            tenant_id=posting_fixture.TENANT,
            business_operation_id=payload["business_operation_id"],
        )
    assert corrupt.value.status_code == 503
    with pytest.raises(EosJournalOperationError) as invalid_uuid:
        reconciler.reconcile(
            tenant_id=posting_fixture.TENANT,
            business_operation_id="not-a-uuid",
        )
    assert invalid_uuid.value.status_code == 422


def test_reconciliation_translates_persistence_failure() -> None:
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _statement):
            raise SQLAlchemyError("database unavailable")

    with pytest.raises(EosJournalOperationError) as unavailable:
        EosJournalOperationService(BrokenSession).reconcile(
            tenant_id=posting_fixture.TENANT,
            business_operation_id=str(uuid.uuid4()),
        )
    assert unavailable.value.error_code == "EOS_JOURNAL_RECONCILIATION_UNAVAILABLE"
    assert unavailable.value.retryable is True


@pytest.mark.parametrize(
    "drift",
    (
        "missing_outbox",
        "idempotency_state",
        "result_type",
        "event_lineage",
        "outbox_state",
        "result_lineage",
    ),
)
def test_committed_reconciliation_fails_closed_on_lineage_drift(drift: str) -> None:
    sessions, _service, payload, _committed = _posted_runtime()
    with sessions.begin() as session:
        if drift == "missing_outbox":
            session.execute(
                EOS_OUTBOX_TABLE.delete().where(
                    EOS_OUTBOX_TABLE.c.business_operation_id
                    == payload["business_operation_id"]
                )
            )
        elif drift == "idempotency_state":
            session.execute(
                update(EOS_IDEMPOTENCY_TABLE)
                .where(
                    EOS_IDEMPOTENCY_TABLE.c.business_operation_id
                    == payload["business_operation_id"]
                )
                .values(idempotency_state="IN_PROGRESS")
            )
        elif drift == "result_type":
            session.execute(
                update(EOS_BUSINESS_OPERATION_TABLE)
                .where(
                    EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                    == payload["business_operation_id"]
                )
                .values(result_json=[])
            )
        elif drift == "event_lineage":
            event = session.execute(
                select(EOS_OUTBOX_TABLE.c.event_payload).where(
                    EOS_OUTBOX_TABLE.c.business_operation_id
                    == payload["business_operation_id"]
                )
            ).scalar_one()
            event = {**event, "journal_no": "VO00-2026-999999"}
            session.execute(
                update(EOS_OUTBOX_TABLE)
                .where(
                    EOS_OUTBOX_TABLE.c.business_operation_id
                    == payload["business_operation_id"]
                )
                .values(
                    event_payload=event,
                    event_payload_hash=semantic_sha256_hash_ref(event),
                )
            )
        elif drift == "outbox_state":
            session.execute(
                update(EOS_OUTBOX_TABLE)
                .where(
                    EOS_OUTBOX_TABLE.c.business_operation_id
                    == payload["business_operation_id"]
                )
                .values(delivery_state="BROKEN")
            )
        else:
            result = session.execute(
                select(EOS_BUSINESS_OPERATION_TABLE.c.result_json).where(
                    EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                    == payload["business_operation_id"]
                )
            ).scalar_one()
            session.execute(
                update(EOS_BUSINESS_OPERATION_TABLE)
                .where(
                    EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                    == payload["business_operation_id"]
                )
                .values(result_json={**result, "journal_no": "VO00-2026-999999"})
            )
    projection = EosJournalOperationService(sessions).reconcile(
        tenant_id=posting_fixture.TENANT,
        business_operation_id=payload["business_operation_id"],
    )
    assert projection["reconciliation_status"] == "COMMITTED_VERIFICATION_FAILED"


def test_committed_reconciliation_fails_closed_when_journal_disappears() -> None:
    sessions, _service, payload, _committed = _posted_runtime()
    reconciler = EosJournalOperationService(sessions)

    class MissingJournal:
        def get_in_session(self, _session, **_identity):
            return None

    reconciler._journals = MissingJournal()
    projection = reconciler.reconcile(
        tenant_id=posting_fixture.TENANT,
        business_operation_id=payload["business_operation_id"],
    )
    assert projection["reconciliation_status"] == "COMMITTED_VERIFICATION_FAILED"


def test_reconciliation_internal_guards_reject_cross_record_drift() -> None:
    operation = {
        "tenant_id": posting_fixture.TENANT,
        "business_operation_id": str(uuid.uuid4()),
        "idempotency_key": "same-key",
        "operation": "FINANCE.VOUCHER.APPROVE_AND_POST",
        "payload_hash": "sha256:" + "1" * 64,
    }
    idempotency = {**operation, "idempotency_state": "COMPLETED"}
    outbox = {
        "tenant_id": posting_fixture.TENANT,
        "business_operation_id": operation["business_operation_id"],
        "event_payload": {},
        "event_payload_hash": semantic_sha256_hash_ref({}),
    }
    journal = {
        "header": {
            "business_operation_id": operation["business_operation_id"],
            "idempotency_key": "different-key",
            "payload_hash": operation["payload_hash"],
        }
    }
    with pytest.raises(ValueError, match="PostedJournal operation lineage"):
        journal_operations_module._require_lineage(
            operation, idempotency, outbox, journal
        )
    with pytest.raises(ValueError, match="Idempotency lineage"):
        journal_operations_module._require_lineage(
            operation,
            {**idempotency, "payload_hash": "sha256:" + "2" * 64},
            outbox,
            journal,
        )
    with pytest.raises(ValueError, match="Outbox lineage"):
        journal_operations_module._require_lineage(
            operation,
            idempotency,
            {**outbox, "tenant_id": "OTHER"},
            journal,
        )
    with pytest.raises(TypeError, match="Persisted timestamp"):
        journal_operations_module._wire_time("not-a-datetime")
    with pytest.raises(TypeError, match="Persisted timestamp"):
        journal_operations_module._database_time(None)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "old"),
        ("commit_state", "PENDING"),
        ("candidate_revision", 0),
        ("candidate_revision", True),
        ("project_codes", []),
        ("project_codes", posting_fixture.PROJECT_CODE),
        ("project_codes", [posting_fixture.PROJECT_CODE] * 2),
        ("tenant_id", "bad tenant"),
        ("company_id", "not-a-uuid"),
        ("journal_hash", "not-a-hash"),
        ("posted_at", None),
        ("posted_at", "not-a-time"),
        ("posted_at", "2026-11-12T02:01:00"),
    ),
)
def test_journal_posted_event_admission_rejects_drift(
    field: str, value: object
) -> None:
    _sessions, _service, _payload, committed = _posted_runtime()
    event = {
        "schema_version": "eos_journal_posted_event.v1",
        "tenant_id": posting_fixture.TENANT,
        "business_operation_id": committed["business_operation_id"],
        "operation": committed["operation"],
        "company_id": committed["result"]["company_id"],
        "journal_id": committed["result"]["journal_id"],
        "journal_no": committed["result"]["journal_no"],
        "journal_hash": committed["result"]["journal_hash"],
        "candidate_id": committed["result"]["candidate_id"],
        "candidate_revision": committed["result"]["candidate_revision"],
        "accounting_acceptance_id": committed["result"]["accounting_acceptance_id"],
        "accounting_period_id": committed["result"]["accounting_period_id"],
        "project_codes": committed["result"]["project_codes"],
        "commit_state": "COMMITTED",
        "posted_at": committed["result"]["posted_at"],
    }
    event[field] = value
    with pytest.raises(EosJournalOutboxEventError):
        admit_journal_posted_event(event)


def test_journal_posted_event_rejects_non_object_and_field_drift() -> None:
    with pytest.raises(EosJournalOutboxEventError, match="result must be an object"):
        journal_outbox_events_module.build_journal_posted_event_payload(
            tenant_id=posting_fixture.TENANT,
            business_operation_id=str(uuid.uuid4()),
            operation="FINANCE.VOUCHER.APPROVE_AND_POST",
            result=[],  # type: ignore[arg-type]
        )
    with pytest.raises(EosJournalOutboxEventError, match="fields do not match"):
        admit_journal_posted_event({})


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W40-S4-04 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_replay_race_conflict_and_outbox_recovery() -> None:
    schema_name = f"mybee_w40s404_{uuid.uuid4().hex}"
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
    engine = None
    try:
        migration = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2540_eos_atomic_journal_posting" in migration.applied
        engine = create_engine(
            scoped_url,
            pool_pre_ping=True,
            pool_size=20,
            max_overflow=5,
        )
        _engine, sessions, candidates, command, _authorization = (
            posting_fixture._runtime(engine=engine)
        )
        command.execute(posting_fixture._payload(), caller=posting_fixture.CALLER)
        service, payload = posting_fixture._prepare_atomic_posting(sessions, candidates)

        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(
                executor.map(
                    lambda _index: service.execute(
                        posting_fixture.CANDIDATE_ID, payload
                    ),
                    range(20),
                )
            )
        assert (
            sum(item["idempotency_disposition"] == "CREATED" for item in results) == 1
        )
        assert (
            sum(item["idempotency_disposition"] == "REPLAYED" for item in results) == 19
        )
        journal_ids = {item["result"]["journal_id"] for item in results}
        assert len(journal_ids) == 1

        reconciliation = EosJournalOperationService(sessions).reconcile(
            tenant_id=posting_fixture.TENANT,
            business_operation_id=payload["business_operation_id"],
        )
        assert reconciliation["journal"]["journal_id"] == next(iter(journal_ids))

        conflicting = copy.deepcopy(payload)
        conflicting["expected_candidate_version"] = 99
        conflicting["payload_hash"] = "sha256:" + "0" * 64
        conflicting["payload_hash"] = journal_post_payload_hash(
            parse_journal_post_command(posting_fixture.CANDIDATE_ID, conflicting)
        )
        with pytest.raises(EosJournalPostingError) as rejected:
            service.execute(posting_fixture.CANDIDATE_ID, conflicting)
        assert rejected.value.status_code == 409

        with sessions.begin() as session:
            session.execute(
                update(EOS_OUTBOX_TABLE)
                .where(EOS_OUTBOX_TABLE.c.event_type != "FINANCE.JOURNAL_POSTED.v1")
                .values(
                    delivery_state="PUBLISHED",
                    attempt_count=1,
                    updated_at=posting_fixture.NOW,
                    published_at=posting_fixture.NOW,
                )
            )

        class DownstreamUnavailable:
            def publish(self, _event):
                raise EosOutboxPublicationError(
                    "PROJECTOR_UNAVAILABLE", "projector is unavailable", retryable=True
                )

        outcome = SqlAlchemyEosOutboxPublisher(sessions).publish_next(
            DownstreamUnavailable(), tenant_id=posting_fixture.TENANT
        )
        assert outcome is not None and outcome.delivery_state == "PENDING"
        after_outage = EosJournalOperationService(sessions).reconcile(
            tenant_id=posting_fixture.TENANT,
            business_operation_id=payload["business_operation_id"],
        )
        assert after_outage["commit_state"] == "COMMITTED"
        assert after_outage["outbox"]["projector_state"] == "STALE"

        with sessions() as session:
            assert (
                session.execute(
                    select(func.count()).select_from(EOS_JOURNAL_HEADER_TABLE)
                ).scalar_one()
                == 1
            )
            assert (
                session.execute(
                    select(func.count()).select_from(EOS_JOURNAL_LINE_TABLE)
                ).scalar_one()
                == 2
            )
            assert (
                session.execute(
                    select(func.count())
                    .select_from(EOS_IDEMPOTENCY_TABLE)
                    .where(
                        EOS_IDEMPOTENCY_TABLE.c.business_operation_id
                        == payload["business_operation_id"]
                    )
                ).scalar_one()
                == 1
            )
        engine.dispose()
        engine = None
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            assert connection.execute(
                "SELECT to_regnamespace(%s)", (schema_name,)
            ).fetchone() == (None,)
