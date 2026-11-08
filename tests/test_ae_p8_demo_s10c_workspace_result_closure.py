from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_ae_api import interaction_agent_result_api as api
from nex_ae_api.auth_guard import BrowserUserAuthContext
from nex_ae_api.interaction_agent_result_api import (
    register_interaction_agent_result_routes,
)
from nex_ae_api.plan_finalization import (
    SqlAlchemyP5PlanFinalizationService,
    build_plan_agent_result,
    verify_plan_completion,
)
from nex_ae_api.route_auth import AeFacadeRouteAuthContext
from nex_ae_api.step_results import build_step_result
from nex_ae_api.workspace_result_publication import (
    SqlAlchemyInstalledIaResultCloser,
    SqlAlchemyInteractionAgentResultSource,
    SqlAlchemyWorkspaceResultPublisher,
    WorkspaceResultPublicationError,
)
from sqlalchemy import text
from test_nex_ae_plan_finalization import (
    EXECUTION_ID,
    NOW,
    TENANT,
    WORKSPACE_ID,
    _factory,
    _step_results,
    _execution,
)
from test_nex_ae_executable_plans import _compiled

OWNER = "owner-p8-demo-s10c"
INTERACTION_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


@pytest.fixture
def store():
    factory = _factory()
    engine = factory.kw["bind"]
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE ae_agent_execution ADD COLUMN principal_id TEXT"))
        connection.execute(text("ALTER TABLE ae_agent_execution ADD COLUMN source_type TEXT"))
        connection.execute(
            text("ALTER TABLE ae_agent_execution ADD COLUMN legacy_interaction_id TEXT")
        )
        connection.execute(
            text(
                "UPDATE ae_agent_execution SET principal_id = :owner, "
                "source_type = 'PROMPT', legacy_interaction_id = :interaction_id"
            ),
            {"owner": OWNER, "interaction_id": INTERACTION_ID},
        )
        connection.execute(
            text(
                "CREATE TABLE ae_workspaces (workspace_id TEXT PRIMARY KEY, "
                "tenant_id TEXT NOT NULL, owner_user_id TEXT NOT NULL, "
                "activity_count INTEGER NOT NULL, last_activity_type TEXT, "
                "updated_at TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_workspace_activities ("
                "activity_schema_version TEXT NOT NULL, activity_id TEXT PRIMARY KEY, "
                "workspace_id TEXT NOT NULL, activity_type TEXT NOT NULL, "
                "trace_id TEXT NOT NULL, request_id TEXT NOT NULL, summary TEXT NOT NULL, "
                "metadata TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ae_workspaces VALUES "
                "(:workspace_id, :tenant_id, :owner, 0, NULL, :now)"
            ),
            {
                "workspace_id": WORKSPACE_ID,
                "tenant_id": TENANT,
                "owner": OWNER,
                "now": NOW,
            },
        )
    return factory


def test_result_verify_closes_to_owner_workspace_once_and_replays(store) -> None:
    aggregate = SqlAlchemyP5PlanFinalizationService(store).finalize(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        created_at=NOW,
    )
    publisher = SqlAlchemyWorkspaceResultPublisher(store)

    first = publisher.publish(
        tenant_id=TENANT,
        delivery_id=aggregate.delivery["delivery_id"],
        now="2026-10-26T09:00:00Z",
    )
    replayed = publisher.publish(
        tenant_id=TENANT,
        delivery_id=aggregate.delivery["delivery_id"],
        now="2026-10-26T10:00:00Z",
    )

    assert first["created"] is True
    assert first["replayed"] is False
    assert replayed["created"] is False
    assert replayed["replayed"] is True
    with store() as session:
        assert session.execute(text("SELECT count(*) FROM ae_agent_result")).scalar() == 1
        assert (
            session.execute(text("SELECT count(*) FROM ae_workspace_activities")).scalar()
            == 1
        )
        assert session.execute(text("SELECT activity_count FROM ae_workspaces")).scalar() == 1
        delivery = session.execute(
            text("SELECT state, attempt_no FROM ae_result_delivery")
        ).one()
        execution = session.execute(
            text("SELECT state, phase FROM ae_agent_execution")
        ).one()
    assert delivery == ("ACKNOWLEDGED", 1)
    assert execution == ("SUCCEEDED", "FINALIZE")


def test_restart_closer_resumes_result_publish_and_owner_read_model(store) -> None:
    SqlAlchemyP5PlanFinalizationService(store).finalize(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        created_at=NOW,
    )

    recovered = SqlAlchemyInstalledIaResultCloser(store).close_ready(
        now="2026-10-26T09:10:00Z"
    )
    restarted = SqlAlchemyInstalledIaResultCloser(store).close_ready(
        now="2026-10-26T09:11:00Z"
    )
    source = SqlAlchemyInteractionAgentResultSource(store)
    own = source.get_owner_result(
        tenant_id=TENANT,
        owner_user_id=OWNER,
        interaction_id=INTERACTION_ID,
    )

    assert recovered == {
        "candidate_count": 1,
        "finalized_count": 0,
        "published_count": 1,
        "replayed_count": 0,
        "failed_count": 0,
        "failures": [],
    }
    assert restarted["candidate_count"] == 0
    assert own is not None
    assert own["execution_state"] == "SUCCEEDED"
    assert own["execution_phase"] == "FINALIZE"
    assert own["result"]["delivery"]["state"] == "ACKNOWLEDGED"
    assert own["metadata"] == {
        "owner_scope_authority": "claim",
        "raw_result_included": False,
        "prompt_included": False,
    }
    assert (
        source.get_owner_result(
            tenant_id=TENANT,
            owner_user_id="another-owner",
            interaction_id=INTERACTION_ID,
        )
        is None
    )


def test_closer_finalizes_result_verify_in_same_cycle(store) -> None:
    closure = SqlAlchemyInstalledIaResultCloser(store).close_ready(
        now="2026-10-26T09:20:00Z"
    )

    assert closure["candidate_count"] == 1
    assert closure["finalized_count"] == 1
    assert closure["published_count"] == 1
    assert closure["failed_count"] == 0


def test_workspace_lineage_and_replay_conflicts_fail_closed(store) -> None:
    aggregate = SqlAlchemyP5PlanFinalizationService(store).finalize(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        created_at=NOW,
    )
    with store.begin() as session:
        session.execute(
            text("UPDATE ae_workspaces SET owner_user_id = 'other-owner'")
        )
    publisher = SqlAlchemyWorkspaceResultPublisher(store)
    with pytest.raises(WorkspaceResultPublicationError) as lineage:
        publisher.publish(
            tenant_id=TENANT,
            delivery_id=aggregate.delivery["delivery_id"],
        )
    assert lineage.value.error_code == "ae.workspace_result_lineage_invalid"


def test_missing_invalid_state_and_tampered_replay_fail_closed(store) -> None:
    publisher = SqlAlchemyWorkspaceResultPublisher(store)
    with pytest.raises(WorkspaceResultPublicationError) as missing:
        publisher.publish(
            tenant_id=TENANT,
            delivery_id="ffffffff-ffff-4fff-8fff-ffffffffffff",
        )
    assert missing.value.error_code == "ae.workspace_result_delivery_not_found"
    with pytest.raises(WorkspaceResultPublicationError, match="timezone"):
        publisher.publish(
            tenant_id=TENANT,
            delivery_id="ffffffff-ffff-4fff-8fff-ffffffffffff",
            now="2026-10-26T09:00:00",
        )

    aggregate = SqlAlchemyP5PlanFinalizationService(store).finalize(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        created_at=NOW,
    )
    with store.begin() as session:
        session.execute(text("UPDATE ae_result_delivery SET state = 'FAILED'"))
    with pytest.raises(WorkspaceResultPublicationError) as state:
        publisher.publish(
            tenant_id=TENANT,
            delivery_id=aggregate.delivery["delivery_id"],
        )
    assert state.value.error_code == "ae.workspace_result_delivery_state_invalid"


def test_acknowledged_activity_tampering_is_detected(store) -> None:
    aggregate = SqlAlchemyP5PlanFinalizationService(store).finalize(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        created_at=NOW,
    )
    publisher = SqlAlchemyWorkspaceResultPublisher(store)
    publisher.publish(
        tenant_id=TENANT,
        delivery_id=aggregate.delivery["delivery_id"],
        now="2026-10-26T09:00:00Z",
    )
    with store.begin() as session:
        session.execute(
            text("UPDATE ae_workspace_activities SET summary = 'tampered'")
        )
    with pytest.raises(WorkspaceResultPublicationError) as conflict:
        publisher.publish(
            tenant_id=TENANT,
            delivery_id=aggregate.delivery["delivery_id"],
        )
    assert conflict.value.error_code == "ae.workspace_result_activity_conflict"


def test_closer_reports_retryable_or_lineage_failure_without_crashing(store) -> None:
    with store.begin() as session:
        session.execute(text("UPDATE ae_workspaces SET owner_user_id = 'other-owner'"))

    result = SqlAlchemyInstalledIaResultCloser(store).close_ready(now=NOW)

    assert result["candidate_count"] == 1
    assert result["finalized_count"] == 1
    assert result["published_count"] == 0
    assert result["failed_count"] == 1
    assert result["failures"][0]["error_code"] == "ae.workspace_result_lineage_invalid"


def test_plan_result_exposes_business_operation_as_reference() -> None:
    plan = _compiled()
    results = _step_results(plan=plan)
    terminal = plan["steps"][1]
    results[1] = build_step_result(
        step_result_id=results[1]["step_result_id"],
        execution_id=EXECUTION_ID,
        executable_plan_id=plan["executable_plan_id"],
        executable_step_id=terminal["executable_step_id"],
        compiled_step_key=terminal["compiled_step_key"],
        logical_step_ref=terminal["logical_step_ref"],
        attempt_no=1,
        status="SUCCEEDED",
        result_contract_ref=terminal["output_contract_ref"],
        result_payload={"commit_state": "COMMITTED"},
        external_refs=("EOS:VOUCHER:voucher-1",),
        executor_kind="LOCAL_SKILL",
        business_operation_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        started_at=NOW,
        completed_at=NOW,
    )
    verification = verify_plan_completion(executable_plan=plan, step_results=results)

    result = build_plan_agent_result(
        execution=_execution(),
        executable_plan=plan,
        step_results=results,
        verification=verification,
        result_id="ffffffff-ffff-4fff-8fff-ffffffffffff",
        created_at=NOW,
    )

    assert result["business_refs"] == [
        "EOS:BUSINESS_OPERATION:aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    ]


def test_interaction_result_route_is_browser_owner_scoped(monkeypatch, store) -> None:
    SqlAlchemyInstalledIaResultCloser(store).close_ready(now="2026-10-26T09:30:00Z")
    projection = SqlAlchemyInteractionAgentResultSource(store).get_owner_result(
        tenant_id=TENANT,
        owner_user_id=OWNER,
        interaction_id=INTERACTION_ID,
    )
    app = FastAPI()
    register_interaction_agent_result_routes(
        app,
        source=SimpleNamespace(get_owner_result=lambda **_values: projection),
    )
    browser = BrowserUserAuthContext(
        tenant_id=TENANT,
        user_id=OWNER,
        scopes=("workspace:use",),
        roles=("employee",),
    )
    monkeypatch.setattr(
        api,
        "authorize_ae_facade_route_request",
        lambda *_args, **_kwargs: AeFacadeRouteAuthContext(
            auth_mode="browser_user",
            browser_context=browser,
        ),
    )

    response = TestClient(app).get(
        f"/api/v1/chat/interactions/{INTERACTION_ID}/agent-result"
    )

    assert response.status_code == 200
    assert response.json()["result"]["delivery"]["state"] == "ACKNOWLEDGED"


def test_interaction_result_route_rejects_service_and_unavailable_source(monkeypatch) -> None:
    app = FastAPI()
    register_interaction_agent_result_routes(app, source=None)
    monkeypatch.setattr(
        api,
        "authorize_ae_facade_route_request",
        lambda *_args, **_kwargs: AeFacadeRouteAuthContext(
            auth_mode="service",
            service_claims=SimpleNamespace(service_id="nex-ag"),
        ),
    )
    response = TestClient(app).get(
        f"/api/v1/chat/interactions/{INTERACTION_ID}/agent-result"
    )
    assert response.status_code == 403


def test_interaction_result_route_handles_missing_unavailable_and_invalid(monkeypatch) -> None:
    browser = BrowserUserAuthContext(
        tenant_id=TENANT,
        user_id=OWNER,
        scopes=("workspace:use",),
        roles=("employee",),
    )
    monkeypatch.setattr(
        api,
        "authorize_ae_facade_route_request",
        lambda *_args, **_kwargs: AeFacadeRouteAuthContext(
            auth_mode="browser_user",
            browser_context=browser,
        ),
    )

    unavailable_app = FastAPI()
    register_interaction_agent_result_routes(unavailable_app, source=None)
    unavailable = TestClient(unavailable_app).get(
        f"/api/v1/chat/interactions/{INTERACTION_ID}/agent-result"
    )
    assert unavailable.status_code == 503

    missing_app = FastAPI()
    register_interaction_agent_result_routes(
        missing_app,
        source=SimpleNamespace(get_owner_result=lambda **_values: None),
    )
    missing = TestClient(missing_app).get(
        f"/api/v1/chat/interactions/{INTERACTION_ID}/agent-result"
    )
    assert missing.status_code == 404

    failed_app = FastAPI()
    register_interaction_agent_result_routes(
        failed_app,
        source=SimpleNamespace(
            get_owner_result=lambda **_values: (_ for _ in ()).throw(
                WorkspaceResultPublicationError(
                    "ae.interaction_agent_result_store_unavailable",
                    "bounded failure",
                    True,
                )
            )
        ),
    )
    failed = TestClient(failed_app).get(
        f"/api/v1/chat/interactions/{INTERACTION_ID}/agent-result"
    )
    assert failed.status_code == 503
