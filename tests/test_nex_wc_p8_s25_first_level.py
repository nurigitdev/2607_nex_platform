from __future__ import annotations

from datetime import UTC, datetime

import pytest
from nex_wc import work_items as work_item_module
from nex_wc.work_items import (
    InMemoryWorkItemRepository,
    SqlAlchemyWorkItemRepository,
    WorkItemError,
    WorkItemService,
)

WORK_ID = "26000000-0000-4000-8000-000000000001"
OTHER_WORK_ID = "26000000-0000-4000-8000-000000000002"
IA_ID = "27000000-0000-4000-8000-000000000001"
NOW = datetime(2026, 10, 21, 13, 0, tzinfo=UTC)


class Authorization:
    def __init__(self) -> None:
        self.active = True
        self.calls = 0

    def effective_authorization(self, **_kwargs):
        self.calls += 1
        return {
            "active": self.active,
            "scopes": ["work:delegate"],
            "revision_hash": "a" * 64,
        }


def _payload(*, requester_id: str = IA_ID) -> dict[str, object]:
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "delegation-p8-s25",
            "tenant_id": "tenant-p8",
            "parent_agent_execution_id": "execution-p8-s25",
            "parent_executable_plan_id": "plan-p8-s25",
            "parent_executable_step_id": "step-p8-s25",
            "delegation_revision": 1,
            "goal": "Prepare the first-level bounded analysis.",
            "work_class": "ANALYSIS",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_ANALYSIS",
            "project_ref": {"entity_type": "PROJECT", "entity_id": "project-p8"},
            "project_scope_ref": "project-p8",
            "result_contract_ref": "contract://nex/wc/project-analysis/v1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "correlation-p8-s25",
        },
        "requester": {"entity_type": "AGENT", "entity_id": requester_id},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-p8"},
    }


def _service(repository, authorization, ids):
    iterator = iter(ids)
    return WorkItemService(
        repository,
        authorization_source=authorization,
        id_factory=lambda: next(iterator),
        clock=lambda: NOW,
        delegation_guard_enabled=True,
    )


def test_s25_first_level_admission_persists_root_depth_and_policy():
    repository = InMemoryWorkItemRepository()
    authorization = Authorization()
    service = _service(repository, authorization, [WORK_ID])

    created = service.create(_payload())
    lineage = repository.get_lineage(tenant_id="tenant-p8", work_item_id=WORK_ID)

    assert created["created"] is True
    assert lineage is not None
    assert lineage["work_item_id"] == lineage["root_work_item_id"] == WORK_ID
    assert lineage["parent_work_item_id"] is None
    assert lineage["parent_claim_ref"] is None
    assert lineage["parent_claim_generation"] is None
    assert lineage["delegation_depth"] == 1
    assert lineage["delegating_agent_ref"] == {
        "agent_id": IA_ID,
        "agent_type": "IA",
    }
    assert lineage["policy_ref"] == "wc.delegation.guard.initial-v1"


def test_s25_idempotent_replay_preserves_original_work_item_and_lineage():
    repository = InMemoryWorkItemRepository()
    authorization = Authorization()
    service = _service(repository, authorization, [WORK_ID, OTHER_WORK_ID])

    first = service.create(_payload())
    before = repository.get_lineage(tenant_id="tenant-p8", work_item_id=WORK_ID)
    replay = service.create(_payload())
    after = repository.get_lineage(tenant_id="tenant-p8", work_item_id=WORK_ID)

    assert first["created"] is True
    assert replay["created"] is False
    assert replay["work_item"]["work_item_id"] == WORK_ID
    assert before == after
    assert repository.get_lineage(
        tenant_id="tenant-p8", work_item_id=OTHER_WORK_ID
    ) is None
    assert authorization.calls == 2


def test_s25_revoked_authorization_blocks_replay_without_lineage_mutation():
    repository = InMemoryWorkItemRepository()
    authorization = Authorization()
    service = _service(repository, authorization, [WORK_ID, OTHER_WORK_ID])
    service.create(_payload())
    before = repository.get_lineage(tenant_id="tenant-p8", work_item_id=WORK_ID)
    authorization.active = False

    with pytest.raises(WorkItemError) as denied:
        service.create(_payload())
    assert denied.value.error_code == "wc.work_item_authorization_denied"
    assert repository.get_lineage(
        tenant_id="tenant-p8", work_item_id=WORK_ID
    ) == before


def test_s25_invalid_first_level_agent_identity_creates_zero_state():
    repository = InMemoryWorkItemRepository()
    service = _service(repository, Authorization(), [WORK_ID])
    with pytest.raises(WorkItemError) as invalid:
        service.create(_payload(requester_id="not-a-uuid"))
    assert invalid.value.error_code == "wc.work_item_invalid"
    assert repository.get(tenant_id="tenant-p8", work_item_id=WORK_ID) is None
    assert repository.get_lineage(tenant_id="tenant-p8", work_item_id=WORK_ID) is None


def test_s25_p7_compatibility_mode_does_not_backfill_lineage():
    repository = InMemoryWorkItemRepository()
    service = WorkItemService(
        repository,
        authorization_source=Authorization(),
        id_factory=lambda: WORK_ID,
        clock=lambda: NOW,
    )
    assert service.create(_payload())["created"] is True
    assert repository.get_lineage(tenant_id="tenant-p8", work_item_id=WORK_ID) is None


def test_s25_repository_rejects_lineage_for_a_different_work_item():
    source_repository = InMemoryWorkItemRepository()
    service = _service(source_repository, Authorization(), [WORK_ID])
    service.create(_payload())
    stored = source_repository.get(tenant_id="tenant-p8", work_item_id=WORK_ID)
    lineage = source_repository.get_lineage(
        tenant_id="tenant-p8", work_item_id=WORK_ID
    )
    assert stored is not None and lineage is not None
    lineage["work_item_id"] = OTHER_WORK_ID
    lineage["root_work_item_id"] = OTHER_WORK_ID
    repository = InMemoryWorkItemRepository()
    with pytest.raises(WorkItemError) as conflict:
        repository.create(stored, lineage=lineage)
    assert conflict.value.error_code == "wc.delegation_lineage_conflict"


def test_s25_repository_rejects_duplicate_work_item_identity():
    source = InMemoryWorkItemRepository()
    service = _service(source, Authorization(), [WORK_ID])
    service.create(_payload())
    stored = source.get(tenant_id="tenant-p8", work_item_id=WORK_ID)
    assert stored is not None
    duplicate = dict(stored)
    duplicate["idempotency_key"] = "sha256:" + "b" * 64
    repository = InMemoryWorkItemRepository()
    repository.create(stored)
    with pytest.raises(WorkItemError) as conflict:
        repository.create(duplicate)
    assert conflict.value.error_code == "wc.work_item_id_conflict"


def test_s25_guard_requires_an_agent_requester():
    payload = _payload()
    payload["requester"] = {"entity_type": "USER", "entity_id": IA_ID}
    service = _service(InMemoryWorkItemRepository(), Authorization(), [WORK_ID])
    with pytest.raises(WorkItemError) as invalid:
        service.create(payload)
    assert invalid.value.error_code == "wc.work_item_invalid"


def test_s25_sql_repository_admits_lineage_in_same_session(monkeypatch):
    source = InMemoryWorkItemRepository()
    _service(source, Authorization(), [WORK_ID]).create(_payload())
    record = source.get(tenant_id="tenant-p8", work_item_id=WORK_ID)
    lineage = source.get_lineage(tenant_id="tenant-p8", work_item_id=WORK_ID)
    assert record is not None and lineage is not None

    class Result:
        rowcount = 1

    class Session:
        committed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return Result()

        def commit(self):
            self.committed = True

    session = Session()
    lineage_calls = []
    monkeypatch.setattr(
        work_item_module,
        "_load_by_semantic_key",
        lambda *_args, **_kwargs: record,
    )
    monkeypatch.setattr(
        work_item_module,
        "create_delegation_lineage_in_session",
        lambda passed_session, passed_lineage: lineage_calls.append(
            (passed_session, passed_lineage)
        ) or (passed_lineage, True),
    )
    repository = SqlAlchemyWorkItemRepository(lambda: session)
    saved, created = repository.create(record, lineage=lineage)
    assert saved == record
    assert created is True
    assert lineage_calls == [(session, lineage)]
    assert session.committed is True


def test_s25_sql_repository_replay_and_lineage_read(monkeypatch):
    source = InMemoryWorkItemRepository()
    _service(source, Authorization(), [WORK_ID]).create(_payload())
    record = source.get(tenant_id="tenant-p8", work_item_id=WORK_ID)
    lineage = source.get_lineage(tenant_id="tenant-p8", work_item_id=WORK_ID)
    assert record is not None and lineage is not None

    class Result:
        rowcount = 0

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return Result()

        def commit(self):
            return None

    monkeypatch.setattr(
        work_item_module,
        "_load_by_semantic_key",
        lambda *_args, **_kwargs: record,
    )
    monkeypatch.setattr(
        work_item_module,
        "load_delegation_lineage_in_session",
        lambda *_args, **_kwargs: lineage,
    )
    repository = SqlAlchemyWorkItemRepository(lambda: Session())
    replayed, created = repository.create(record, lineage=lineage)
    assert replayed == record
    assert created is False
    assert repository.get_lineage(
        tenant_id="tenant-p8", work_item_id=WORK_ID
    ) == lineage


def test_s25_sql_repository_missing_reload_fails_before_lineage(monkeypatch):
    source = InMemoryWorkItemRepository()
    _service(source, Authorization(), [WORK_ID]).create(_payload())
    record = source.get(tenant_id="tenant-p8", work_item_id=WORK_ID)
    lineage = source.get_lineage(tenant_id="tenant-p8", work_item_id=WORK_ID)
    assert record is not None and lineage is not None

    class Result:
        rowcount = 1

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return Result()

    monkeypatch.setattr(
        work_item_module,
        "_load_by_semantic_key",
        lambda *_args, **_kwargs: None,
    )
    repository = SqlAlchemyWorkItemRepository(lambda: Session())
    with pytest.raises(WorkItemError) as conflict:
        repository.create(record, lineage=lineage)
    assert conflict.value.error_code == "wc.work_item_write_conflict"
    assert conflict.value.retryable is True
