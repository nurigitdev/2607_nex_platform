from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from nex_wc import coordination, work_results
from nex_wc.coordination import (
    CoordinationError,
    InMemoryCoordinationRepository,
    SqlAlchemyCoordinationRepository,
)
from nex_wc.work_items import InMemoryWorkItemRepository
from nex_wc.work_results import SqlAlchemyWorkResultRepository, WorkResultError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

NOW = "2026-11-01T01:00:00Z"
WORK_ID = "11111111-1111-4111-8111-111111111111"
AGENT_ID = "22222222-2222-4222-8222-222222222222"
ASSIGNMENT_ID = "33333333-3333-4333-8333-333333333333"
CLAIM_ID = "44444444-4444-4444-8444-444444444444"


class _Result:
    def __init__(self, *, first=None, rows=(), scalar=1, rowcount=1):
        self._first = first
        self._rows = list(rows)
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return list(self._rows)

    def scalar_one(self):
        return self._scalar


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


def _factory(session):
    return lambda: session


def _work_record(*, state="ROUTED", version=2):
    item = {
        "tenant_id": "VO00",
        "work_item_id": WORK_ID,
        "state": state,
        "version": version,
        "goal": "Prepare durable result",
        "work_class": "ANALYSIS",
        "routing_target": {"required_capability": "FINANCE.REPORT.READ"},
        "project_ref": {"entity_type": "PROJECT", "entity_id": "NVT"},
        "artifact_refs": [],
        "completion_policy": "OWNER_SUBMITS",
        "trace": {"correlation_id": "trace-s20c", "causation_id": "cause-s20c"},
        "requester": {"entity_type": "USER", "entity_id": "E0001"},
    }
    return {
        "tenant_id": "VO00",
        "work_item_id": WORK_ID,
        "delegation_spec": {"result_contract_ref": "urn:nex:result:s20c:1"},
        "work_item": item,
        "state": state,
        "version": version,
    }


def _route():
    return {
        "routing_decision_id": "55555555-5555-4555-8555-555555555555",
        "policy_version": "policy-s20c",
        "decision": "ROUTED",
        "target_ref": AGENT_ID,
        "decided_at": NOW,
    }


def _selected_agent():
    return {
        "agent_id": AGENT_ID,
        "agent_type": "PA",
        "project_id": "NVT",
    }


def _identifiers():
    return {
        "assignment_id": ASSIGNMENT_ID,
        "claim_id": CLAIM_ID,
        "handoff_id": "66666666-6666-4666-8666-666666666666",
        "outbox_id": "77777777-7777-4777-8777-777777777777",
        "event_id": "88888888-8888-4888-8888-888888888888",
    }


def _outbox_row(*, payload=None, as_datetime=False):
    timestamp = datetime(2026, 11, 1, 1, 0, tzinfo=UTC) if as_datetime else NOW
    return {
        "tenant_id": "VO00",
        "outbox_id": "77777777-7777-4777-8777-777777777777",
        "event_id": "88888888-8888-4888-8888-888888888888",
        "work_item_id": WORK_ID,
        "event_type": "WORK_RESULT_SUBMITTED",
        "event_payload": payload or {"result_id": "result-s20c"},
        "delivery_state": "PENDING",
        "enqueued_job_id": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _result_row(*, payload=None):
    return {
        "tenant_id": "VO00",
        "result_id": "result-s20c",
        "work_item_id": WORK_ID,
        "revision_no": 1,
        "result_hash": "sha256:" + "a" * 64,
        "result_payload": payload or {"summary": "ready"},
        "source_execution_ref": "execution-s20c",
        "claim_id": CLAIM_ID,
        "claim_generation": 1,
        "assignment_id": ASSIGNMENT_ID,
        "submitted_agent_id": AGENT_ID,
        "submitted_at": NOW,
    }


def _work_result():
    return {
        "tenant_id": "VO00",
        "result_id": "result-s20c",
        "work_item_id": WORK_ID,
        "revision_no": 1,
        "result_type": "REPORT",
        "schema_ref": "urn:nex:result:s20c:1",
        "technical_outcome": "SUCCEEDED",
        "business_outcome": "VERIFIED",
        "source_execution_ref": "execution-s20c",
        "claim_ref": CLAIM_ID,
        "claim_generation": 1,
        "assignment_ref": ASSIGNMENT_ID,
        "submitted_by": {"entity_type": "AGENT", "entity_id": AGENT_ID},
        "submitted_at": NOW,
        "trace": {"correlation_id": "trace-s20c"},
    }


def _commit_values():
    return {
        "work_result": _work_result(),
        "result_hash": "sha256:" + "a" * 64,
        "expected_version": 2,
        "authorization": {"revision_hash": "sha256:" + "b" * 64, "checked_at": NOW},
        "outbox_id": "77777777-7777-4777-8777-777777777777",
        "event_id": "88888888-8888-4888-8888-888888888888",
        "now": NOW,
    }


def test_coordination_sql_route_success_and_conflicts(monkeypatch):
    session = _Session(_Result(scalar=4), _Result(), _Result())
    repository = SqlAlchemyCoordinationRepository(_factory(session))
    record = _work_record(state="CREATED", version=1)
    monkeypatch.setattr(coordination, "_lock_work_item", lambda *_a: record)

    saved = repository.save_routing_decision(
        tenant_id="VO00", work_item_id=WORK_ID, expected_version=1, decision=_route()
    )
    assert saved["decision"] == "ROUTED"
    assert record["state"] == "ROUTED"
    assert session.commits == 1

    monkeypatch.setattr(coordination, "_lock_work_item", lambda *_a: None)
    with pytest.raises(CoordinationError) as missing:
        repository.save_routing_decision(
            tenant_id="VO00", work_item_id=WORK_ID, expected_version=1, decision=_route()
        )
    assert missing.value.error_code == "wc.work_item_not_found"

    monkeypatch.setattr(
        coordination, "_lock_work_item", lambda *_a: _work_record(state="ROUTED", version=2)
    )
    with pytest.raises(CoordinationError) as stale:
        repository.save_routing_decision(
            tenant_id="VO00", work_item_id=WORK_ID, expected_version=1, decision=_route()
        )
    assert stale.value.error_code == "wc.work_item_route_conflict"


def test_coordination_sql_claim_success_and_recovery_conflicts(monkeypatch):
    monkeypatch.setattr(coordination, "_lock_work_item", lambda *_a: _work_record())
    monkeypatch.setattr(coordination, "_load_latest_route", lambda *_a, **_k: _route())
    monkeypatch.setattr(
        coordination, "load_delegation_ancestor_agents_in_session", lambda *_a, **_k: []
    )
    session = _Session(_Result(scalar=1), _Result(), _Result(), _Result(), _Result())
    repository = SqlAlchemyCoordinationRepository(_factory(session))
    accepted = repository.commit_claim(
        tenant_id="VO00",
        work_item_id=WORK_ID,
        expected_version=2,
        selected_agent=_selected_agent(),
        authorization={"revision_hash": "r", "subject_id": "E0001", "checked_at": NOW},
        identifiers=_identifiers(),
        lease_verifier="sha256:" + "c" * 64,
        lease_expires_at="2026-11-01T01:05:00Z",
        now=NOW,
    )
    assert accepted["claim"]["claim_generation"] == 1
    assert accepted["work_item"]["state"] == "ASSIGNED"
    assert session.commits == 1

    monkeypatch.setattr(
        coordination, "_lock_work_item", lambda *_a: _work_record(state="ASSIGNED", version=3)
    )
    no_expired = _Session(_Result(first=None))
    repository = SqlAlchemyCoordinationRepository(_factory(no_expired))
    with pytest.raises(CoordinationError) as active:
        repository.commit_claim(
            tenant_id="VO00",
            work_item_id=WORK_ID,
            expected_version=3,
            selected_agent=_selected_agent(),
            authorization={"revision_hash": "r", "subject_id": "E0001", "checked_at": NOW},
            identifiers=_identifiers(),
            lease_verifier="v",
            lease_expires_at=NOW,
            now=NOW,
        )
    assert active.value.error_code == "wc.active_claim_exists"

    recovery_race = _Session(
        _Result(first={"claim_id": CLAIM_ID, "assignment_id": ASSIGNMENT_ID}),
        _Result(rowcount=0),
    )
    repository = SqlAlchemyCoordinationRepository(_factory(recovery_race))
    with pytest.raises(CoordinationError) as conflict:
        repository.commit_claim(
            tenant_id="VO00",
            work_item_id=WORK_ID,
            expected_version=3,
            selected_agent=_selected_agent(),
            authorization={"revision_hash": "r", "subject_id": "E0001", "checked_at": NOW},
            identifiers=_identifiers(),
            lease_verifier="v",
            lease_expires_at=NOW,
            now=NOW,
        )
    assert conflict.value.error_code == "wc.claim_recovery_conflict"
    assert conflict.value.retryable is True


def test_coordination_sql_mapping_helpers_and_handoff_transition():
    empty = _Session(_Result(first=None))
    with pytest.raises(CoordinationError, match="state changed"):
        coordination._transition_handoff_outbox_in_session(
            empty,
            outbox_id="outbox",
            event_id="event",
            job_id="job",
            source_states=("PENDING", "ENQUEUED"),
            target_state="ENQUEUED",
            updated_at=NOW,
        )

    row = _outbox_row(as_datetime=True)
    mapped = coordination._transition_handoff_outbox_in_session(
        _Session(_Result(first=row)),
        outbox_id="outbox",
        event_id="event",
        job_id="job",
        source_states=("PENDING", "ENQUEUED"),
        target_state="ENQUEUED",
        updated_at=NOW,
    )
    assert mapped["created_at"] == NOW

    work_row = {
        "tenant_id": "VO00",
        "work_item_id": WORK_ID,
        "delegation_spec": {"result_contract_ref": "contract"},
        "work_item": _work_record()["work_item"],
        "state": "ROUTED",
        "version": 2,
    }
    assert coordination._load_work_item(_Session(_Result(first=None)), "VO00", WORK_ID) is None
    loaded = coordination._load_work_item(
        _Session(_Result(first=work_row), _Result(first=None)), "VO00", WORK_ID
    )
    assert loaded["latest_routing_decision"] is None
    assert coordination._lock_work_item(_Session(_Result(first=None)), "VO00", WORK_ID) is None
    assert coordination._lock_work_item(
        _Session(_Result(first=work_row)), "VO00", WORK_ID
    )["work_item_id"] == WORK_ID
    assert coordination._load_latest_route(
        _Session(_Result(first=None)), "VO00", WORK_ID, lock=True
    ) is None
    route = coordination._load_latest_route(
        _Session(
            _Result(
                first={
                    "routing_decision_id": _route()["routing_decision_id"],
                    "decision": {"decision": "ROUTED"},
                }
            )
        ),
        "VO00",
        WORK_ID,
    )
    assert route["routing_decision_id"] == _route()["routing_decision_id"]


@pytest.mark.parametrize("value", (None, "", "not-a-time", "2026-11-01T01:00:00"))
def test_coordination_rejects_malformed_stored_timestamps(value):
    with pytest.raises(CoordinationError) as caught:
        coordination._parse_time(value)
    assert caught.value.error_code == "wc.coordination_store_invalid"


def test_coordination_parent_authority_distinguishes_tenant_and_missing_assignment():
    repository = InMemoryCoordinationRepository(InMemoryWorkItemRepository())
    repository._claims[("OTHER", WORK_ID)] = [{"claim_id": CLAIM_ID}]
    repository._claims[("VO00", WORK_ID)] = [
        {
            "claim_id": CLAIM_ID,
            "work_item_id": WORK_ID,
            "assignment_id": ASSIGNMENT_ID,
            "claim_generation": 1,
            "state": "ACTIVE",
            "lease_expires_at": NOW,
        }
    ]
    assert repository.get_parent_claim_authority(tenant_id="MISSING", claim_id=CLAIM_ID) is None
    assert repository.get_parent_claim_authority(tenant_id="VO00", claim_id=CLAIM_ID) is None
    repository._assignments[("VO00", WORK_ID)] = {
        "assignment_id": ASSIGNMENT_ID,
        "claim_generation": 1,
        "status": "ACTIVE",
        "agent_id": AGENT_ID,
        "agent_type": "PA",
    }
    authority = repository.get_parent_claim_authority(tenant_id="VO00", claim_id=CLAIM_ID)
    assert authority["agent_id"] == AGENT_ID


def test_coordination_in_memory_expired_claim_is_recovered(monkeypatch):
    work_items = InMemoryWorkItemRepository()
    repository = InMemoryCoordinationRepository(work_items)
    key = ("VO00", WORK_ID)
    record = _work_record(state="ASSIGNED", version=3)
    work_items._records[key] = record
    monkeypatch.setattr(work_items._lineages, "ancestor_agent_refs", lambda **_k: [])
    repository._routes[key] = [_route()]
    repository._claims[key] = [
        {
            "claim_id": CLAIM_ID,
            "work_item_id": WORK_ID,
            "assignment_id": ASSIGNMENT_ID,
            "claim_generation": 1,
            "state": "ACTIVE",
            "lease_expires_at": "2026-11-01T00:59:00Z",
        }
    ]
    repository._assignments[key] = {
        "assignment_id": ASSIGNMENT_ID,
        "claim_generation": 1,
        "status": "ACTIVE",
    }
    repository._outbox[("VO00", "old-outbox")] = {
        **_outbox_row(payload={"claim_ref": CLAIM_ID}),
        "outbox_id": "old-outbox",
        "work_item_id": WORK_ID,
        "event_type": "CLAIM_EXECUTION_HANDOFF",
        "delivery_state": "ENQUEUED",
    }

    accepted = repository.commit_claim(
        tenant_id="VO00",
        work_item_id=WORK_ID,
        expected_version=3,
        selected_agent=_selected_agent(),
        authorization={"revision_hash": "r"},
        identifiers=_identifiers(),
        lease_verifier="new-verifier",
        lease_expires_at="2026-11-01T01:05:00Z",
        now=NOW,
    )
    assert accepted["claim"]["claim_generation"] == 2
    assert repository._claims[key][0]["state"] == "EXPIRED"
    assert repository._outbox[("VO00", "old-outbox")]["delivery_state"] == "FAILED"

    record["state"] = "ASSIGNED"
    record["version"] = 5
    repository._claims[key][-1]["lease_expires_at"] = "2026-11-01T01:06:00Z"
    with pytest.raises(CoordinationError) as active:
        repository.commit_claim(
            tenant_id="VO00",
            work_item_id=WORK_ID,
            expected_version=5,
            selected_agent=_selected_agent(),
            authorization={"revision_hash": "r"},
            identifiers=_identifiers(),
            lease_verifier="v",
            lease_expires_at="2026-11-01T01:10:00Z",
            now=NOW,
        )
    assert active.value.error_code == "wc.active_claim_exists"

    record["state"] = "ROUTED"
    record["version"] = 6
    with pytest.raises(CoordinationError) as stale:
        repository.commit_claim(
            tenant_id="VO00",
            work_item_id=WORK_ID,
            expected_version=5,
            selected_agent=_selected_agent(),
            authorization={"revision_hash": "r"},
            identifiers=_identifiers(),
            lease_verifier="v",
            lease_expires_at="2026-11-01T01:10:00Z",
            now=NOW,
        )
    assert stale.value.error_code == "wc.work_item_claim_conflict"


def test_coordination_sql_handoff_read_and_delivery_paths():
    event_payload = {
        "claim_ref": CLAIM_ID,
        "assignment_ref": ASSIGNMENT_ID,
    }
    row = {
        **_outbox_row(payload=event_payload),
        "delegation_spec": {"result_contract_ref": "urn:nex:result:s20c:1"},
        "work_item": _work_record()["work_item"],
        "claim_state": "ACTIVE",
        "claim_generation": 1,
        "lease_expires_at": datetime(2026, 11, 1, 1, 5, tzinfo=UTC),
        "assignment_status": "ACTIVE",
        "active_claim_id": CLAIM_ID,
        "requester_ref": "E0001",
    }

    repository = SqlAlchemyCoordinationRepository(_factory(_Session(_Result(rows=[row]))))
    assert repository.list_pending_handoffs(limit=10)[0]["event_payload"] == event_payload

    repository = SqlAlchemyCoordinationRepository(_factory(_Session(_Result(first=row))))
    loaded = repository.load_handoff_event(outbox_id="outbox", event_id="event")
    assert loaded["claim_generation"] == 1
    assert loaded["requester_ref"] == "E0001"

    missing = SqlAlchemyCoordinationRepository(_factory(_Session(_Result(first=None))))
    with pytest.raises(CoordinationError) as not_found:
        missing.load_handoff_event(outbox_id="outbox", event_id="event")
    assert not_found.value.status_code == 404

    enqueued_session = _Session(_Result(first=row))
    enqueued = SqlAlchemyCoordinationRepository(_factory(enqueued_session))
    assert enqueued.mark_handoff_enqueued(
        outbox_id="outbox", event_id="event", job_id="job", updated_at=NOW
    )["outbox_id"] == row["outbox_id"]
    assert enqueued_session.commits == 1

    delivered_session = _Session(_Result(first=row), _Result(rowcount=1))
    delivered = SqlAlchemyCoordinationRepository(_factory(delivered_session))
    assert delivered.mark_handoff_delivered(
        outbox_id="outbox",
        event_id="event",
        job_id="job",
        updated_at=NOW,
        agent_execution_id="execution-s20c",
    )["event_payload"]["assignment_ref"] == ASSIGNMENT_ID
    assert delivered_session.commits == 1

    conflict = SqlAlchemyCoordinationRepository(
        _factory(_Session(_Result(first=row), _Result(rowcount=0)))
    )
    with pytest.raises(CoordinationError) as execution_conflict:
        conflict.mark_handoff_delivered(
            outbox_id="outbox",
            event_id="event",
            job_id="job",
            updated_at=NOW,
            agent_execution_id="different-execution",
        )
    assert execution_conflict.value.error_code == "wc.handoff_execution_conflict"


def test_coordination_required_and_valid_time_helpers():
    with pytest.raises(CoordinationError) as invalid:
        coordination._required("tenant_id", " ")
    assert invalid.value.status_code == 400
    assert coordination._parse_time(NOW) == datetime(2026, 11, 1, 1, 0, tzinfo=UTC)


def test_work_result_sql_reads_and_outbox_transitions():
    source = _result_row(payload=json.dumps({"summary": "ready"}))
    pending = _outbox_row(payload=json.dumps({"result_id": "result-s20c"}))

    repository = SqlAlchemyWorkResultRepository(_factory(_Session(_Result(first=source))))
    assert repository.get_result_source(tenant_id="VO00", result_id="result-s20c")[
        "work_result"
    ] == {"summary": "ready"}

    repository = SqlAlchemyWorkResultRepository(
        _factory(_Session(_Result(rows=[source, {**source, "result_id": "result-2"}])))
    )
    assert len(
        repository.list_result_sources_by_execution(
            tenant_id="VO00", source_execution_ref="execution-s20c", limit=10
        )
    ) == 2

    repository = SqlAlchemyWorkResultRepository(_factory(_Session(_Result(rows=[pending]))))
    assert repository.list_pending_result_events(limit=10)[0]["event_payload"]["result_id"] == "result-s20c"

    missing = SqlAlchemyWorkResultRepository(_factory(_Session(_Result(first=None))))
    with pytest.raises(WorkResultError) as not_found:
        missing.load_result_event(outbox_id="outbox", event_id="event")
    assert not_found.value.error_code == "wc.work_result_event_not_found"

    session = _Session(_Result(first=pending))
    repository = SqlAlchemyWorkResultRepository(_factory(session))
    assert repository.mark_result_event_enqueued(
        outbox_id="outbox", event_id="event", job_id="job", updated_at=NOW
    )["delivery_state"] == "PENDING"
    assert session.commits == 1

    conflict = SqlAlchemyWorkResultRepository(_factory(_Session(_Result(first=None))))
    with pytest.raises(WorkResultError) as update_conflict:
        conflict.mark_result_event_delivered(
            outbox_id="outbox", event_id="event", job_id="job", updated_at=NOW
        )
    assert update_conflict.value.retryable is True

    loaded = SqlAlchemyWorkResultRepository(_factory(_Session(_Result(first=pending))))
    assert loaded.load_result_event(outbox_id="outbox", event_id="event")[
        "event_type"
    ] == "WORK_RESULT_SUBMITTED"


def test_work_result_sql_submission_mapping_none_and_authority():
    assert work_results._load_submission_context(
        _Session(_Result(first=None)), tenant_id="VO00", work_item_id=WORK_ID, lock=True
    ) is None
    row = {
        "work_item": _work_record(state="ASSIGNED", version=2)["work_item"],
        "delegation_spec": {"result_contract_ref": "urn:nex:result:s20c:1"},
        "work_state": "ASSIGNED",
        "work_version": 2,
        "claim_id": CLAIM_ID,
        "claim_generation": 1,
        "claim_state": "ACTIVE",
        "assignment_id": ASSIGNMENT_ID,
        "agent_id": AGENT_ID,
        "assignment_status": "ACTIVE",
    }
    postgres_session = _Session(_Result(first=row))
    context = work_results._load_submission_context(
        postgres_session, tenant_id="VO00", work_item_id=WORK_ID, lock=True
    )
    assert context["claim"]["claim_id"] == CLAIM_ID
    assert "FOR UPDATE OF work" in postgres_session.executed[0][0]

    no_authority = {**row, "claim_id": None, "assignment_id": None}
    context = work_results._load_submission_context(
        _Session(_Result(first=no_authority), dialect="sqlite"),
        tenant_id="VO00",
        work_item_id=WORK_ID,
        lock=True,
    )
    assert context["claim"] is None and context["assignment"] is None


def test_work_result_sql_identity_mapping_and_commit_replay(monkeypatch):
    identity = {
        "result_id": "result-s20c",
        "work_item_id": WORK_ID,
        "result_hash": "sha256:" + "a" * 64,
        "submitted_at": NOW,
        "outbox_id": "77777777-7777-4777-8777-777777777777",
        "event_id": "88888888-8888-4888-8888-888888888888",
        "work_item_version": 3,
    }
    assert work_results._load_result_by_identity(
        _Session(_Result(first=None)),
        tenant_id="VO00",
        result_id="result-s20c",
        work_item_id=WORK_ID,
        revision_no=1,
    ) is None
    assert work_results._load_result_by_identity(
        _Session(_Result(first=identity)),
        tenant_id="VO00",
        result_id="result-s20c",
        work_item_id=WORK_ID,
        revision_no=1,
    )["accepted_at"] == NOW

    replay_identity = {
        **identity,
        "tenant_id": "VO00",
        "accepted_at": NOW,
    }
    repository = SqlAlchemyWorkResultRepository(_factory(_Session()))
    monkeypatch.setattr(
        work_results, "_load_result_by_identity", lambda *_a, **_k: replay_identity
    )
    replay = repository.commit_result(**_commit_values())
    assert replay["created"] is False

    drift = dict(replay_identity, result_hash="sha256:" + "f" * 64)
    monkeypatch.setattr(work_results, "_load_result_by_identity", lambda *_a, **_k: drift)
    with pytest.raises(WorkResultError) as conflict:
        repository.commit_result(**_commit_values())
    assert conflict.value.error_code == "wc.work_result_idempotency_conflict"


def test_work_result_sql_commit_race_success_and_version_conflict(monkeypatch):
    values = _commit_values()
    context = {
        "work_item": _work_record(state="ASSIGNED", version=2)["work_item"],
        "delegation_spec": {"result_contract_ref": "urn:nex:result:s20c:1"},
        "claim": {"claim_id": CLAIM_ID, "claim_generation": 1, "state": "ACTIVE"},
        "assignment": {
            "assignment_id": ASSIGNMENT_ID,
            "agent_id": AGENT_ID,
            "status": "ACTIVE",
        },
    }

    identities = iter((None, None))
    monkeypatch.setattr(
        work_results, "_load_result_by_identity", lambda *_a, **_k: next(identities)
    )
    monkeypatch.setattr(work_results, "_load_submission_context", lambda *_a, **_k: context)
    session = _Session(_Result(), _Result(rowcount=1), _Result())
    accepted = SqlAlchemyWorkResultRepository(_factory(session)).commit_result(**values)
    assert accepted["created"] is True
    assert accepted["work_item_version"] == 3
    assert session.commits == 1

    identities = iter((None, None))
    monkeypatch.setattr(
        work_results, "_load_result_by_identity", lambda *_a, **_k: next(identities)
    )
    session = _Session(_Result(), _Result(rowcount=0))
    with pytest.raises(WorkResultError) as conflict:
        SqlAlchemyWorkResultRepository(_factory(session)).commit_result(**values)
    assert conflict.value.error_code == "wc.work_result_version_conflict"
    assert conflict.value.retryable is True

    replay = {
        "tenant_id": "VO00",
        "result_id": "result-s20c",
        "work_item_id": WORK_ID,
        "result_hash": values["result_hash"],
        "work_item_version": 3,
        "outbox_id": values["outbox_id"],
        "event_id": values["event_id"],
        "accepted_at": NOW,
    }
    identities = iter((None, replay))
    monkeypatch.setattr(
        work_results, "_load_result_by_identity", lambda *_a, **_k: next(identities)
    )
    replay_session = _Session()
    accepted = SqlAlchemyWorkResultRepository(_factory(replay_session)).commit_result(**values)
    assert accepted["created"] is False
    assert replay_session.commits == 1


def test_in_memory_work_result_revision_replay_and_missing_work_item():
    coordination_repository = InMemoryCoordinationRepository(InMemoryWorkItemRepository())
    repository = work_results.InMemoryWorkResultRepository(coordination_repository)
    result = _work_result()
    repository._results[("VO00", "original")] = {
        "work_result": {**result, "result_id": "original"},
        "result_hash": "sha256:" + "a" * 64,
        "work_item_version": 3,
        "outbox_id": "outbox",
        "event_id": "event",
        "accepted_at": NOW,
    }
    repository._work_revisions[("VO00", WORK_ID, 1)] = ("VO00", "original")
    replay = repository.commit_result(**_commit_values())
    assert replay["created"] is False

    empty = work_results.InMemoryWorkResultRepository(coordination_repository)
    with pytest.raises(WorkResultError) as missing:
        empty.commit_result(**_commit_values())
    assert missing.value.error_code == "wc.work_item_not_found"

    assert repository.get_result_source(tenant_id="VO00", result_id="original")[
        "result_hash"
    ] == "sha256:" + "a" * 64
    assert repository.get_result_source(tenant_id="VO00", result_id="missing") is None
    assert len(
        repository.list_result_sources_by_execution(
            tenant_id="VO00", source_execution_ref="execution-s20c", limit=1
        )
    ) == 1


def test_work_result_missing_context_is_not_found():
    with pytest.raises(WorkResultError) as missing:
        work_results._require_commit_authority(None, _work_result(), 2)
    assert missing.value.status_code == 404


class _FailingFactory:
    def __call__(self):
        raise SQLAlchemyError("database unavailable")


@pytest.mark.parametrize(
    "operation",
    (
        lambda repository: repository.get_submission_context(
            tenant_id="VO00", work_item_id=WORK_ID
        ),
        lambda repository: repository.get_result_source(
            tenant_id="VO00", result_id="result-s20c"
        ),
        lambda repository: repository.list_result_sources_by_execution(
            tenant_id="VO00", source_execution_ref="execution-s20c", limit=10
        ),
        lambda repository: repository.list_pending_result_events(limit=10),
        lambda repository: repository.load_result_event(
            outbox_id="outbox", event_id="event"
        ),
        lambda repository: repository.mark_result_event_enqueued(
            outbox_id="outbox", event_id="event", job_id="job", updated_at=NOW
        ),
    ),
)
def test_work_result_sql_read_failures_are_retryable(operation):
    with pytest.raises(WorkResultError) as unavailable:
        operation(SqlAlchemyWorkResultRepository(_FailingFactory()))
    assert unavailable.value.error_code == "wc.work_result_store_unavailable"
    assert unavailable.value.retryable is True


def test_work_result_sql_commit_maps_integrity_and_storage_failures(monkeypatch):
    repository = SqlAlchemyWorkResultRepository(_factory(_Session()))
    monkeypatch.setattr(
        work_results,
        "_load_result_by_identity",
        lambda *_a, **_k: (_ for _ in ()).throw(
            IntegrityError("insert", {}, RuntimeError("duplicate"))
        ),
    )
    with pytest.raises(WorkResultError) as conflict:
        repository.commit_result(**_commit_values())
    assert conflict.value.error_code == "wc.work_result_identity_conflict"

    monkeypatch.setattr(
        work_results,
        "_load_result_by_identity",
        lambda *_a, **_k: (_ for _ in ()).throw(SQLAlchemyError("offline")),
    )
    with pytest.raises(WorkResultError) as unavailable:
        repository.commit_result(**_commit_values())
    assert unavailable.value.error_code == "wc.work_result_store_unavailable"
    assert unavailable.value.retryable is True
