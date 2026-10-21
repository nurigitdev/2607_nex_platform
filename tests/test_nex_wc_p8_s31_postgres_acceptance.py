from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from nex_wc.coordination import (
    CoordinationError,
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.work_items import SqlAlchemyWorkItemRepository, WorkItemError, WorkItemService
from run_migrations import load_migrations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_WC_P8_S31_POSTGRES_SMOKE") == "1"
NOW_DT = datetime(2026, 10, 21, 20, 0, tzinfo=UTC)
NOW = "2026-10-21T20:00:00Z"
PROJECT = "project-p8-s31"
IA_ID = "31100000-0000-4000-8000-000000000001"

DG_SCENARIOS = (
    "DG-01",
    "DG-02",
    "DG-03",
    "DG-04",
    "DG-05",
    "DG-06",
    "DG-07",
    "DG-08",
    "DG-09",
    "DG-10",
    "DG-11",
    "DG-12",
)

postgres_smoke = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S31 PostgreSQL acceptance is disabled",
)


class Authorization:
    def __init__(self, *, active: bool = True) -> None:
        self._active = active

    def effective_authorization(self, **_kwargs):
        return {
            "active": self._active,
            "scopes": ["work:delegate", "work:claim"] if self._active else [],
            "revision_hash": "b" * 64,
        }


class Agents:
    def __init__(self, agent_id: str):
        self._agent_id = agent_id

    def list_agents(self, **_kwargs):
        return [self.get_agent(tenant_id="unused", agent_id=self._agent_id)]

    def get_agent(self, **_kwargs):
        return {
            "agent_id": self._agent_id,
            "agent_type": "PA",
            "project_id": PROJECT,
            "profile_ref": "agent-profile://pa/project-budget-read/v1",
            "status": "ACTIVE",
        }


def _stable_uuid(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"nex-p8-s31:{label}"))


def _agent(label: str) -> str:
    return _stable_uuid(f"agent-{label}")


def _payload(
    tenant_id: str,
    label: str,
    parent: dict[str, object] | None = None,
) -> dict[str, object]:
    spec = {
        "schema_version": "1.0" if parent is None else "1.1",
        "delegation_id": f"delegation-p8-s31-{label}",
        "tenant_id": tenant_id,
        "parent_agent_execution_id": (
            f"ia-execution-{label}" if parent is None else parent["execution_id"]
        ),
        "parent_executable_plan_id": "plan-p8-s31",
        "parent_executable_step_id": f"step-p8-s31-{label}",
        "delegation_revision": 1,
        "goal": f"Exercise protected delegation scenario {label}.",
        "work_class": "ANALYSIS",
        "required_agent_type": "PA",
        "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
        "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
        "project_scope_ref": PROJECT,
        "result_contract_ref": "contract://nex/wc/p8-s31/v1",
        "completion_policy": "OWNER_SUBMITS",
        "correlation_id": f"correlation-p8-s31-{label}",
    }
    requester_id: object = IA_ID
    if parent is not None:
        spec.update(
            {
                "parent_work_item_id": parent["work_item_id"],
                "parent_claim_ref": parent["claim_id"],
                "parent_claim_generation": parent["claim_generation"],
                "delegating_agent_ref": {
                    "agent_id": parent["agent_id"],
                    "agent_type": "PA",
                },
            }
        )
        requester_id = parent["agent_id"]
    return {
        "delegation_spec": spec,
        "requester": {"entity_type": "AGENT", "entity_id": requester_id},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-p8"},
    }


class Harness:
    def __init__(self, sessions, tenant_id: str) -> None:
        self.sessions = sessions
        self.tenant_id = tenant_id
        self.work_items = SqlAlchemyWorkItemRepository(sessions)
        self.coordination = SqlAlchemyCoordinationRepository(sessions)

    def create(
        self,
        label: str,
        parent: dict[str, object] | None = None,
        *,
        at: datetime = NOW_DT,
        authorization: Authorization | None = None,
    ) -> str:
        work_item_id = _stable_uuid(f"{self.tenant_id}-work-{label}")
        WorkItemService(
            self.work_items,
            authorization_source=authorization or Authorization(),
            id_factory=lambda: work_item_id,
            clock=lambda: at,
            delegation_guard_enabled=True,
        ).create(_payload(self.tenant_id, label, parent))
        return work_item_id

    def claim_and_ack(
        self,
        work_item_id: str,
        agent_id: str,
        label: str,
        *,
        at: datetime = NOW_DT,
    ) -> dict[str, object]:
        service = WorkCoordinationService(
            self.coordination,
            candidate_source=Agents(agent_id),
            authorization_source=Authorization(),
            id_factory=lambda: str(uuid4()),
            token_factory=lambda: _stable_uuid(
                f"{self.tenant_id}-lease-{label}"
            ),
            clock=lambda: at,
        )
        service.route(
            tenant_id=self.tenant_id,
            work_item_id=work_item_id,
            expected_version=1,
        )
        claimed = service.claim(
            tenant_id=self.tenant_id,
            work_item_id=work_item_id,
            expected_version=2,
        )
        execution_id = _stable_uuid(f"{self.tenant_id}-execution-{label}")
        self.coordination.mark_handoff_enqueued(
            outbox_id=claimed["outbox_id"],
            event_id=claimed["event_id"],
            job_id=f"job-{label}",
            updated_at=at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        )
        self.coordination.mark_handoff_delivered(
            outbox_id=claimed["outbox_id"],
            event_id=claimed["event_id"],
            job_id=f"job-{label}",
            updated_at=at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            agent_execution_id=execution_id,
        )
        return {
            "work_item_id": work_item_id,
            "claim_id": claimed["claim"]["claim_id"],
            "claim_generation": claimed["claim"]["claim_generation"],
            "execution_id": execution_id,
            "agent_id": agent_id,
        }

    def route_for(self, work_item_id: str, agent_id: str) -> WorkCoordinationService:
        service = WorkCoordinationService(
            self.coordination,
            candidate_source=Agents(agent_id),
            authorization_source=Authorization(),
            id_factory=lambda: str(uuid4()),
            token_factory=lambda: _stable_uuid(
                f"{self.tenant_id}-cycle-lease"
            ),
            clock=lambda: NOW_DT,
        )
        service.route(
            tenant_id=self.tenant_id,
            work_item_id=work_item_id,
            expected_version=1,
        )
        return service


_TABLES = (
    "wc_work_result",
    "wc_delegation_lineage",
    "wc_event_outbox",
    "wc_claim",
    "wc_assignment",
    "wc_routing_decision",
    "wc_work_item",
)


def _cleanup(connection, tenant_id: str) -> None:
    for table in _TABLES:
        connection.execute(
            text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )


def _tenant_counts(connection, tenant_id: str) -> dict[str, int]:
    return {
        table: int(
            connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
        for table in _TABLES
    }


def _assert_database_identity_and_migrations(engine) -> None:
    target = make_url(DATABASE_URL)
    assert target.username == "nex_wc_user"
    assert target.database == "nex_wc_test"
    expected = [migration.version for migration in load_migrations("nex-wc")]
    with engine.connect() as connection:
        assert tuple(
            connection.execute(text("SELECT current_database(), current_user")).one()
        ) == ("nex_wc_test", "nex_wc_user")
        applied = set(
            connection.execute(text("SELECT version FROM schema_migrations")).scalars()
        )
    assert set(expected) <= applied
    assert expected[-1] == "1005_wc_assignment_execution"


def test_s31_delegation_guard_acceptance_inventory_is_complete() -> None:
    assert DG_SCENARIOS == tuple(f"DG-{index:02d}" for index in range(1, 13))
    plan = (
        ROOT
        / "docs/transition/P8/P8_CA01_Controlled_WRITE_Approval_Delegation_EOS_Contract_Closure_v1.0.md"
    ).read_text(encoding="utf-8")
    assert all(scenario in plan for scenario in DG_SCENARIOS)


@postgres_smoke
def test_s31_actual_postgres_depth_authority_revocation_and_zero_residue() -> None:
    tenant_id = "tenant-p8-s31-depth"
    engine = create_engine(DATABASE_URL, pool_size=8, max_overflow=2)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    _assert_database_identity_and_migrations(engine)
    with engine.begin() as connection:
        _cleanup(connection, tenant_id)

    denied_work_ids: list[str] = []
    try:
        harness = Harness(sessions, tenant_id)
        root_id = harness.create("depth-1")
        before_claim = harness.work_items.get_lineage(
            tenant_id=tenant_id, work_item_id=root_id
        )
        assert before_claim["delegation_depth"] == 1
        parent = harness.claim_and_ack(root_id, _agent("depth-1"), "depth-1")
        assert harness.work_items.get_lineage(
            tenant_id=tenant_id, work_item_id=root_id
        ) == before_claim

        for depth in range(2, 11):
            child_id = harness.create(f"depth-{depth}", parent)
            assert harness.work_items.get_lineage(
                tenant_id=tenant_id, work_item_id=child_id
            )["delegation_depth"] == depth
            parent = harness.claim_and_ack(
                child_id,
                _agent(f"depth-{depth}"),
                f"depth-{depth}",
            )

        hop_denied_id = _stable_uuid(f"{tenant_id}-work-depth-11")
        with pytest.raises(WorkItemError) as hop_denied:
            harness.create("depth-11", parent)
        assert hop_denied.value.error_code == "wc.delegation_hop_limit_exceeded"
        denied_work_ids.append(hop_denied_id)

        stale_root_id = harness.create("stale-root")
        stale_parent = harness.claim_and_ack(
            stale_root_id, _agent("stale-parent"), "stale-parent"
        )
        stale_payload = _payload(tenant_id, "stale-child", stale_parent)
        stale_payload["delegation_spec"]["parent_claim_generation"] = 2
        stale_id = _stable_uuid(f"{tenant_id}-work-stale-child")
        with pytest.raises(WorkItemError) as stale_denied:
            WorkItemService(
                harness.work_items,
                authorization_source=Authorization(),
                id_factory=lambda: stale_id,
                clock=lambda: NOW_DT,
                delegation_guard_enabled=True,
            ).create(stale_payload)
        assert stale_denied.value.error_code == "wc.delegation_parent_authority_stale"
        denied_work_ids.append(stale_id)

        expired_root_id = harness.create("expired-root")
        expired_parent = harness.claim_and_ack(
            expired_root_id, _agent("expired-parent"), "expired-parent"
        )
        expired_id = _stable_uuid(f"{tenant_id}-work-expired-child")
        with pytest.raises(WorkItemError) as expired_denied:
            harness.create(
                "expired-child",
                expired_parent,
                at=NOW_DT + timedelta(seconds=301),
            )
        assert expired_denied.value.error_code == "wc.delegation_parent_authority_stale"
        denied_work_ids.append(expired_id)

        revoked_root_id = harness.create("revoked-root")
        revoked_parent = harness.claim_and_ack(
            revoked_root_id, _agent("revoked-parent"), "revoked-parent"
        )
        revoked_id = _stable_uuid(f"{tenant_id}-work-revoked-child")
        with pytest.raises(WorkItemError) as revoked_denied:
            harness.create(
                "revoked-child",
                revoked_parent,
                authorization=Authorization(active=False),
            )
        assert revoked_denied.value.error_code == "wc.work_item_authorization_denied"
        denied_work_ids.append(revoked_id)

        with engine.connect() as connection:
            for work_item_id in denied_work_ids:
                assert connection.execute(
                    text(
                        "SELECT count(*) FROM wc_work_item "
                        "WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id"
                    ),
                    {"tenant_id": tenant_id, "work_item_id": work_item_id},
                ).scalar_one() == 0
                assert connection.execute(
                    text(
                        "SELECT count(*) FROM wc_assignment "
                        "WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id"
                    ),
                    {"tenant_id": tenant_id, "work_item_id": work_item_id},
                ).scalar_one() == 0
    finally:
        with engine.begin() as connection:
            _cleanup(connection, tenant_id)
            residue = _tenant_counts(connection, tenant_id)
        engine.dispose()
    assert all(count == 0 for count in residue.values()), residue


@postgres_smoke
def test_s31_actual_postgres_cycle_denial_creates_zero_claim_authority() -> None:
    tenant_id = "tenant-p8-s31-cycle"
    engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=1)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    _assert_database_identity_and_migrations(engine)
    with engine.begin() as connection:
        _cleanup(connection, tenant_id)

    try:
        harness = Harness(sessions, tenant_id)
        agent_a = _agent("cycle-a")
        agent_b = _agent("cycle-b")
        root_id = harness.create("cycle-root")
        root = harness.claim_and_ack(root_id, agent_a, "cycle-a")
        child_id = harness.create("cycle-child", root)
        child = harness.claim_and_ack(child_id, agent_b, "cycle-b")
        grandchild_id = harness.create("cycle-grandchild", child)
        service = harness.route_for(grandchild_id, agent_a)

        with pytest.raises(CoordinationError) as cycle_denied:
            service.claim(
                tenant_id=tenant_id,
                work_item_id=grandchild_id,
                expected_version=2,
            )
        assert cycle_denied.value.error_code == "wc.delegation_cycle_detected"

        with engine.connect() as connection:
            work_state = connection.execute(
                text(
                    "SELECT state, version FROM wc_work_item "
                    "WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id"
                ),
                {"tenant_id": tenant_id, "work_item_id": grandchild_id},
            ).one()
            assert tuple(work_state) == ("ROUTED", 2)
            assert connection.execute(
                text(
                    "SELECT count(*) FROM wc_claim "
                    "WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id"
                ),
                {"tenant_id": tenant_id, "work_item_id": grandchild_id},
            ).scalar_one() == 0
            assert connection.execute(
                text(
                    "SELECT count(*) FROM wc_assignment "
                    "WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id"
                ),
                {"tenant_id": tenant_id, "work_item_id": grandchild_id},
            ).scalar_one() == 0
            assert connection.execute(
                text(
                    "SELECT count(*) FROM wc_event_outbox "
                    "WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id"
                ),
                {"tenant_id": tenant_id, "work_item_id": grandchild_id},
            ).scalar_one() == 0
    finally:
        with engine.begin() as connection:
            _cleanup(connection, tenant_id)
            residue = _tenant_counts(connection, tenant_id)
        engine.dispose()
    assert all(count == 0 for count in residue.values()), residue
