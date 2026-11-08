from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from nex_ae_api import work_result_events as events
from nex_ae_api import workspace_result_publication as publication
from nex_ae_api.runtime_jobs import RuntimeJobError
from nex_ae_api.work_result_events import (
    SqlAlchemyWorkResultEventService,
    WorkResultEventError,
    validate_work_result_event,
)
from nex_ae_api.workspace_result_publication import (
    SqlAlchemyInstalledIaResultCloser,
    SqlAlchemyInteractionAgentResultSource,
    SqlAlchemyWorkspaceResultPublisher,
    WorkspaceResultPublicationError,
)
from sqlalchemy.exc import SQLAlchemyError

NOW = "2026-11-01T02:00:00Z"
WORK_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_ID = "22222222-2222-4222-8222-222222222222"
CLAIM_ID = "33333333-3333-4333-8333-333333333333"
ASSIGNMENT_ID = "44444444-4444-4444-8444-444444444444"
AGENT_ID = "55555555-5555-4555-8555-555555555555"
DELIVERY_ID = "66666666-6666-4666-8666-666666666666"


class _Result:
    def __init__(self, *, first=None, rows=(), rowcount=1):
        self._first = first
        self._rows = list(rows)
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return list(self._rows)


class _Session:
    def __init__(self, *results, dialect="postgresql"):
        self.results = list(results)
        self.commits = 0
        self.executed = []
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params))
        return self.results.pop(0) if self.results else _Result()

    def commit(self):
        self.commits += 1

    def get_bind(self):
        return self.bind


class _FailingFactory:
    def __call__(self):
        raise SQLAlchemyError("database unavailable")


def _factory(session):
    return lambda: session


def _event():
    return {
        "schema_version": "2.1",
        "event_id": "event-s20d",
        "event_name": "WORK_RESULT_SUBMITTED",
        "tenant_id": "VO00",
        "work_item_id": WORK_ID,
        "result_id": "result-s20d",
        "revision_no": 1,
        "result_type": "REPORT",
        "result_schema_ref": "urn:nex:result:s20d:1",
        "technical_outcome": "SUCCEEDED",
        "business_outcome": "VERIFIED",
        "source_execution_ref": SOURCE_ID,
        "claim_ref": CLAIM_ID,
        "claim_generation": 1,
        "assignment_ref": ASSIGNMENT_ID,
        "submitted_by": {"entity_type": "AGENT", "entity_id": AGENT_ID},
        "resume_match_ref": WORK_ID,
        "correlation_id": "trace-s20d",
        "causation_id": "cause-s20d",
        "occurred_at": NOW,
    }


def _context():
    return {
        "wait_id": "wait-s20d",
        "wait_state": "PENDING",
        "parent_state": "WAITING_DEPENDENCY",
        "step_state": "WAITING",
        "executor_kind": "WC_DELEGATE_WORK",
        "result_contract_ref": "urn:nex:result:s20d:1",
        "parent_correlation_id": "trace-s20d",
        "child_execution_id": SOURCE_ID,
        "child_agent_id": AGENT_ID,
        "source_type": "CLAIMED_WORKITEM",
        "work_item_ref": WORK_ID,
        "claim_ref": CLAIM_ID,
        "claim_generation": 1,
        "assignment_ref": ASSIGNMENT_ID,
    }


@pytest.mark.parametrize(
    "mutation",
    (
        lambda _value: [],
        lambda value: {**value, "unknown": True},
        lambda value: {key: item for key, item in value.items() if key != "result_id"},
        lambda value: {**value, "schema_version": "1.0"},
        lambda value: {**value, "technical_outcome": "MAYBE"},
        lambda value: {**value, "business_outcome": "MAYBE"},
        lambda value: {**value, "submitted_by": {"entity_type": "USER", "entity_id": AGENT_ID}},
        lambda value: {**value, "revision_no": True},
    ),
)
def test_work_result_event_rejects_malformed_contract(mutation):
    with pytest.raises(WorkResultEventError):
        validate_work_result_event(mutation(_event()))


def test_work_result_event_semantic_and_terminal_reason_matrix():
    event = _event()
    context = _context()
    assert events._semantic_rejection(event, context) is None
    assert events._semantic_rejection(event, {**context, "parent_correlation_id": "other"}) == "CORRELATION_MISMATCH"
    assert events._semantic_rejection(event, {**context, "child_execution_id": None}) == "SOURCE_EXECUTION_AUTHORITY_MISSING"
    assert events._semantic_rejection(event, {**context, "claim_generation": 2}) == "CURRENT_AUTHORITY_MISMATCH"
    assert events._terminal_parent_reason({**context, "wait_state": "CANCELLED"}) == "WAIT_CANCELLED"
    assert events._terminal_parent_reason({**context, "parent_state": "FAILED"}) == "PARENT_FAILED"
    assert events._terminal_parent_reason({**context, "step_state": "BLOCKED"}) == "STEP_BLOCKED"
    assert events._terminal_parent_reason(context) is None
    assert events._parent_ready(context) is True
    assert events._parent_ready({**context, "wait_state": "PENDING_REVIEW"}) is False


def test_work_result_event_mapping_and_helper_failures():
    with pytest.raises(WorkResultEventError):
        events._entity_ref([])
    with pytest.raises(WorkResultEventError):
        events._entity_ref({"entity_type": "AGENT", "entity_id": AGENT_ID, "extra": True})
    with pytest.raises(WorkResultEventError):
        events._payload([])
    with pytest.raises(WorkResultEventError):
        events._positive_int("revision", 0)
    with pytest.raises(WorkResultEventError):
        events._required("tenant", "", 10)
    with pytest.raises(WorkResultEventError):
        events._uuid("work_item", "bad")
    with pytest.raises(WorkResultEventError):
        events._timestamp("occurred_at", "2026-11-01T02:00:00")
    with pytest.raises(WorkResultEventError):
        events._projection(None, created=False)
    assert events._load_inbox(
        _Session(_Result(first=None)), tenant_id="VO00", event_id="event", lock=True
    ) is None

    with pytest.raises(WorkResultEventError) as conflict:
        events._mark_matched(
            _Session(_Result(rowcount=0)),
            event=_event(),
            wait_id="wait",
            runtime_job_id="job",
            now=NOW,
        )
    assert conflict.value.retryable is True


def test_work_result_reconcile_limit_and_store_failures():
    service = SqlAlchemyWorkResultEventService(
        _FailingFactory(), runtime_jobs=SimpleNamespace()
    )
    with pytest.raises(WorkResultEventError):
        service.reconcile_pending(limit=True)
    with pytest.raises(WorkResultEventError) as unavailable:
        service.reconcile_pending(limit=1)
    assert unavailable.value.retryable is True


def _publication_record(**overrides):
    record = {
        "tenant_id": "VO00",
        "delivery_id": DELIVERY_ID,
        "result_id": "result-s20d",
        "agent_execution_id": SOURCE_ID,
        "target_type": "WORKSPACE_RESULT",
        "target_ref": WORK_ID,
        "delivery_state": "PENDING",
        "attempt_no": 0,
        "publication_operation_id": "publish-s20d",
        "external_delivery_ref": None,
        "result_status": "SUCCEEDED",
        "result_hash": "sha256:" + "a" * 64,
        "agent_result": {
            "created_at": NOW,
            "structured_result": {"external_refs": []},
            "business_refs": [],
        },
        "agent_type": "IA",
        "principal_id": "E0001",
        "source_type": "PROMPT",
        "workspace_id": WORK_ID,
        "legacy_interaction_id": ASSIGNMENT_ID,
        "execution_state": "RUNNING",
        "execution_phase": "RESULT_PUBLISH",
        "correlation_id": "trace-s20d",
        "owner_user_id": "E0001",
    }
    record.update(overrides)
    return record


def test_workspace_publication_helper_denials_and_replay_conflict():
    record = _publication_record()
    publication._require_workspace_result_lineage(record)
    with pytest.raises(WorkspaceResultPublicationError):
        publication._require_workspace_result_lineage({**record, "owner_user_id": "other"})
    activity = publication._workspace_activity(record)
    with pytest.raises(WorkspaceResultPublicationError) as missing:
        publication._require_activity_semantics(None, activity)
    assert missing.value.retryable is True
    with pytest.raises(WorkspaceResultPublicationError):
        publication._require_activity_semantics({**activity, "summary": "drift"}, activity)
    with pytest.raises(WorkspaceResultPublicationError) as replay:
        publication._require_replay_state(
            {**record, "external_delivery_ref": "wrong"}, activity, activity
        )
    assert replay.value.error_code == "ae.workspace_result_replay_conflict"


def test_workspace_publication_identity_timestamp_and_json_guards():
    with pytest.raises(WorkspaceResultPublicationError):
        publication._required_text("tenant_id", "", 128)
    with pytest.raises(WorkspaceResultPublicationError):
        publication._required_uuid("delivery_id", "bad")
    with pytest.raises(WorkspaceResultPublicationError):
        publication._timestamp("not-a-time")
    with pytest.raises(WorkspaceResultPublicationError):
        publication._timestamp("2026-11-01T02:00:00")
    with pytest.raises(WorkspaceResultPublicationError):
        publication._json_object("[]")
    assert publication._datetime_text(datetime(2026, 11, 1, 2, tzinfo=UTC)) == NOW
    assert publication._json_object(json.dumps({"ok": True})) == {"ok": True}


def test_workspace_publication_store_and_notifier_failures(monkeypatch):
    publisher = SqlAlchemyWorkspaceResultPublisher(_FailingFactory())
    with pytest.raises(WorkspaceResultPublicationError) as unavailable:
        publisher.publish(tenant_id="VO00", delivery_id=DELIVERY_ID, now=NOW)
    assert unavailable.value.retryable is True

    class _Notifier:
        def notify_agent_result(self, **_kwargs):
            raise RuntimeError("best-effort notification failed")

    SqlAlchemyWorkspaceResultPublisher(
        _factory(_Session()), completion_notifier=_Notifier()
    )._notify(_publication_record())

    closer = SqlAlchemyInstalledIaResultCloser(
        _FailingFactory(),
        finalizer=SimpleNamespace(),
        publisher=SimpleNamespace(),
    )
    with pytest.raises(WorkspaceResultPublicationError) as query:
        closer.close_ready()
    assert query.value.error_code == "ae.workspace_result_candidate_query_unavailable"

    source = SqlAlchemyInteractionAgentResultSource(_FailingFactory())
    with pytest.raises(WorkspaceResultPublicationError) as read:
        source.get_owner_result(
            tenant_id="VO00", owner_user_id="E0001", interaction_id=ASSIGNMENT_ID
        )
    assert read.value.error_code == "ae.interaction_agent_result_store_unavailable"


def test_workspace_publication_execution_and_commit_races(monkeypatch):
    record = _publication_record()
    activity = publication._workspace_activity(record)
    monkeypatch.setattr(publication, "_load_activity", lambda *_a, **_k: activity)

    monkeypatch.setattr(
        publication,
        "_load_publication",
        lambda *_a, **_k: {**record, "execution_state": "SUCCEEDED"},
    )
    with pytest.raises(WorkspaceResultPublicationError) as invalid_state:
        SqlAlchemyWorkspaceResultPublisher(_factory(_Session())).publish(
            tenant_id="VO00", delivery_id=DELIVERY_ID, now=NOW
        )
    assert invalid_state.value.error_code == "ae.workspace_result_execution_state_invalid"

    monkeypatch.setattr(publication, "_load_publication", lambda *_a, **_k: record)
    with pytest.raises(WorkspaceResultPublicationError) as ack_conflict:
        SqlAlchemyWorkspaceResultPublisher(
            _factory(_Session(_Result(rowcount=0)))
        ).publish(tenant_id="VO00", delivery_id=DELIVERY_ID, now=NOW)
    assert ack_conflict.value.error_code == "ae.workspace_result_delivery_conflict"
    assert ack_conflict.value.retryable is True

    with pytest.raises(WorkspaceResultPublicationError) as execution_conflict:
        SqlAlchemyWorkspaceResultPublisher(
            _factory(_Session(_Result(rowcount=1), _Result(rowcount=0)))
        ).publish(tenant_id="VO00", delivery_id=DELIVERY_ID, now=NOW)
    assert execution_conflict.value.error_code == "ae.workspace_result_execution_conflict"
    assert execution_conflict.value.retryable is True


def test_workspace_delivery_lookup_missing_and_store_failure():
    with pytest.raises(WorkspaceResultPublicationError) as missing:
        publication._delivery_id_for_execution(
            _factory(_Session(_Result(first=None))),
            tenant_id="VO00",
            execution_id=SOURCE_ID,
        )
    assert missing.value.error_code == "ae.workspace_result_delivery_not_found"
    with pytest.raises(WorkspaceResultPublicationError) as unavailable:
        publication._delivery_id_for_execution(
            _FailingFactory(), tenant_id="VO00", execution_id=SOURCE_ID
        )
    assert unavailable.value.retryable is True


def test_workspace_projection_without_result_and_load_helpers():
    row = {
        "legacy_interaction_id": ASSIGNMENT_ID,
        "workspace_id": WORK_ID,
        "agent_execution_id": SOURCE_ID,
        "execution_state": "RUNNING",
        "execution_phase": "PLAN",
        "result_id": None,
        "updated_at": NOW,
        "completed_at": None,
    }
    projection = publication._interaction_result_projection(row)
    assert projection["result"] is None
    assert projection["terminal"] is False
    assert publication._load_activity(_Session(_Result(first=None)), "activity") is None
    assert publication._load_publication(
        _Session(_Result(first=None)), "VO00", DELIVERY_ID
    ) is None


def test_runtime_job_error_remains_typed():
    error = RuntimeJobError("ae.runtime_job_failed", "failed", True)
    assert error.retryable is True
