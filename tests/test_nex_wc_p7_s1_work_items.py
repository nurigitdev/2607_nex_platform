from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from nex_wc.work_item_api import register_work_item_routes
from nex_wc.work_items import (
    InMemoryWorkItemRepository,
    SqlAlchemyWorkItemRepository,
    WorkItemError,
    WorkItemService,
    delegation_identity,
    validate_delegation_spec,
)
from run_migrations import load_migrations, service_database_env
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]


class _Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate"],
            "revision_hash": "a" * 64,
        }


def _spec(**overrides):
    value = {
        "schema_version": "1.0",
        "delegation_id": "delegation-1",
        "tenant_id": "tenant-a",
        "parent_agent_execution_id": "execution-parent-1",
        "parent_executable_plan_id": "plan-parent-1",
        "parent_executable_step_id": "step-parent-1",
        "delegation_revision": 1,
        "goal": "Prepare the project margin report.",
        "work_class": "REPORTING",
        "required_agent_type": "PA",
        "required_capability": "project.margin.read",
        "project_ref": {"entity_type": "PROJECT", "entity_id": "project-1"},
        "project_scope_ref": "project-1",
        "result_contract_ref": "urn:nex:result:project-margin:1",
        "completion_policy": "OWNER_SUBMITS",
        "correlation_id": "trace-1",
        "causation_id": "cause-1",
    }
    value.update(overrides)
    return value


def _payload(**overrides):
    value = {
        "delegation_spec": _spec(),
        "requester": {"entity_type": "AGENT", "entity_id": "ia-1"},
        "accountable_owner": {"entity_type": "USER", "entity_id": "user-1"},
    }
    value.update(overrides)
    return value


def _service():
    return WorkItemService(
        InMemoryWorkItemRepository(),
        authorization_source=_Authorization(),
        id_factory=lambda: "11111111-1111-4111-8111-111111111111",
        clock=lambda: datetime(2026, 10, 18, 1, 2, 3, tzinfo=UTC),
    )


def test_s1_service_inventory_and_migration_profile_include_wc():
    spec = SERVICE_SPECS["nex-wc"]
    assert spec.database_env == "NEX_WC_DATABASE_URL"
    assert spec.default_port == 8106
    assert service_database_env("nex-wc", profile="test") == "NEX_WC_TEST_DATABASE_URL"
    assert [item.version for item in load_migrations("nex-wc")][:7] == [
        "0023_schema_migrations_baseline",
        "0083_service_job_queue_foundation",
        "0085_service_operational_events_foundation",
        "0112_service_worker_heartbeat_foundation",
        "0135_service_job_replay_lineage",
        "0137_service_log_entries_foundation",
        "1000_wc_work_item",
    ]


def test_s1_service_entrypoint_exposes_runtime_and_wc_repository():
    from nex_wc.main import app

    client = TestClient(app)
    assert client.get("/health").json()["service_id"] == "nex-wc"
    assert app.state.nex_persistence.service_id == "nex-wc"
    assert app.state.wc_work_items is not None


def test_s1_create_is_deterministic_idempotent_and_schema_valid():
    service = _service()
    first = service.create(_payload())
    second = service.create(_payload())

    assert first["created"] is True
    assert second["created"] is False
    assert second["work_item"] == first["work_item"]
    assert first["work_item"]["state"] == "CREATED"
    assert first["work_item"]["source"]["source_type"] == "AGENT_PLAN_STEP"

    schema = json.loads(
        (ROOT / "docs/transition/P7/contracts/p7-work-item-v2.1.schema.json").read_text()
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        first["work_item"]
    )


def test_s1_semantic_conflict_and_new_revision_behavior():
    service = _service()
    service.create(_payload())
    changed = _payload()
    changed["delegation_spec"] = _spec(goal="Different semantic goal")
    with pytest.raises(WorkItemError) as conflict:
        service.create(changed)
    assert conflict.value.error_code == "wc.work_item_idempotency_conflict"


def test_s1_tenant_scope_and_status_projection():
    service = _service()
    item = service.create(_payload())["work_item"]
    status = service.status(tenant_id="tenant-a", work_item_id=item["work_item_id"])
    assert status["state"] == "CREATED"
    with pytest.raises(WorkItemError) as missing:
        service.get(tenant_id="tenant-b", work_item_id=item["work_item_id"])
    assert missing.value.status_code == 404


@pytest.mark.parametrize(
    "mutator",
    (
        lambda value: value.update(schema_version="9.9"),
        lambda value: value.update(delegation_revision=0),
        lambda value: value.update(required_agent_type="IA"),
        lambda value: value.update(work_class="UNKNOWN"),
        lambda value: value.update(completion_policy="UNKNOWN"),
        lambda value: value.update(project_scope_ref="other-project"),
        lambda value: value.update(extra="blocked"),
    ),
)
def test_s1_rejects_invalid_delegation_specs(mutator):
    spec = _spec()
    mutator(spec)
    with pytest.raises(WorkItemError):
        validate_delegation_spec(spec)


def test_s1_identity_excludes_goal_but_includes_revision():
    first = validate_delegation_spec(_spec())
    changed_goal = validate_delegation_spec(_spec(goal="A different goal"))
    revision = validate_delegation_spec(_spec(delegation_revision=2))
    assert delegation_identity(first) == delegation_identity(changed_goal)
    assert delegation_identity(first) != delegation_identity(revision)


def test_s5_identity_uses_stable_delegation_and_accepts_expected_work_item_id():
    service = _service()
    expected = "99999999-9999-4999-8999-999999999995"
    created = service.create({**_payload(), "work_item_id": expected})
    changed_runtime_lineage = validate_delegation_spec(
        _spec(
            parent_executable_plan_id="new-runtime-plan-id",
            parent_executable_step_id="new-runtime-step-id",
        )
    )

    assert created["work_item"]["work_item_id"] == expected
    assert delegation_identity(validate_delegation_spec(_spec())) == delegation_identity(
        changed_runtime_lineage
    )
    with pytest.raises(WorkItemError, match="UUID"):
        service.create({**_payload(), "work_item_id": "not-a-uuid"})


def test_s1_http_routes_are_protected_and_tenant_scoped():
    app = build_service_app(SERVICE_SPECS["nex-wc"])
    register_work_item_routes(app, service=_service())
    client = TestClient(app)
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-wc")
    headers = {"Authorization": f"Bearer {token.access_token}"}

    assert client.post("/api/v1/work-items", json=_payload()).status_code == 401
    created = client.post("/api/v1/work-items", json=_payload(), headers=headers)
    assert created.status_code == 201
    work_item_id = created.json()["work_item"]["work_item_id"]

    read = client.get(
        f"/api/v1/work-items/{work_item_id}",
        headers={**headers, "X-NeX-Tenant-Id": "tenant-a"},
    )
    assert read.status_code == 200
    assert read.json()["tenant_id"] == "tenant-a"
    denied = client.get(
        f"/api/v1/work-items/{work_item_id}",
        headers={**headers, "X-NeX-Tenant-Id": "tenant-b"},
    )
    assert denied.status_code == 404

    repeated = client.post("/api/v1/work-items", json=_payload(), headers=headers)
    assert repeated.status_code == 200
    status = client.get(
        f"/api/v1/work-items/{work_item_id}/status",
        headers={**headers, "X-NeX-Tenant-Id": "tenant-a"},
    )
    assert status.status_code == 200
    assert status.json()["state"] == "CREATED"
    assert client.get(
        f"/api/v1/work-items/{work_item_id}/status",
        headers={**headers, "X-NeX-Tenant-Id": "tenant-b"},
    ).status_code == 404
    assert client.get(
        f"/api/v1/work-items/{work_item_id}",
        headers={"X-NeX-Tenant-Id": "tenant-a"},
    ).status_code == 401
    assert client.get(
        f"/api/v1/work-items/{work_item_id}/status",
        headers={"X-NeX-Tenant-Id": "tenant-a"},
    ).status_code == 401

    invalid = _payload(priority="IMPOSSIBLE")
    assert client.post("/api/v1/work-items", json=invalid, headers=headers).status_code == 400


def test_s1_request_validation_rejects_unsupported_fields_and_values():
    service = _service()
    with pytest.raises(WorkItemError):
        service.create({**_payload(), "unexpected": True})
    with pytest.raises(WorkItemError):
        service.create({**_payload(), "priority": "IMPOSSIBLE"})
    with pytest.raises(WorkItemError):
        service.create({**_payload(), "title": ""})
    with pytest.raises(WorkItemError):
        service.create({**_payload(), "description": 3})
    with pytest.raises(WorkItemError):
        service.create({**_payload(), "closure_policy": {"authority_type": "BAD"}})


@pytest.mark.parametrize(
    "payload",
    (
        None,
        {"schema_version": "1.0"},
        _spec(project_ref={"entity_type": "ORG", "entity_id": "project-1"}),
        _spec(project_ref="project-1"),
        _spec(causation_id=""),
    ),
)
def test_s1_more_delegation_boundaries(payload):
    with pytest.raises(WorkItemError):
        validate_delegation_spec(payload)


@pytest.mark.parametrize(
    "changes",
    (
        {"requester": None},
        {"requester": {"entity_type": "AGENT", "entity_id": "ia", "extra": 1}},
        {"closure_policy": "requester"},
        {"closure_policy": {"authority_type": "REQUESTER", "extra": 1}},
        {"closure_policy": {"authority_type": "REQUESTER", "required_review": "yes"}},
        {"title": "x" * 301},
    ),
)
def test_s1_more_create_boundaries(changes):
    with pytest.raises(WorkItemError):
        _service().create({**_payload(), **changes})


def test_s1_default_factories_and_error_text_are_usable():
    service = WorkItemService(
        InMemoryWorkItemRepository(), authorization_source=_Authorization()
    )
    created = service.create(_payload())
    assert created["work_item"]["work_item_id"]
    assert str(WorkItemError("code", "detail")) == "detail"


class _BrokenSession:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *args, **kwargs):
        raise SQLAlchemyError("broken")


def test_s1_sql_repository_maps_database_failures():
    repository = SqlAlchemyWorkItemRepository(lambda: _BrokenSession())
    with pytest.raises(WorkItemError) as create_error:
        repository.create(
            {
                "tenant_id": "tenant",
                "work_item_id": "11111111-1111-4111-8111-111111111111",
                "idempotency_key": "sha256:" + "1" * 64,
                "delegation_semantic_hash": "sha256:" + "2" * 64,
                "delegation_spec": {},
                "work_item": {},
            }
        )
    assert create_error.value.status_code == 503
    with pytest.raises(WorkItemError) as get_error:
        repository.get(tenant_id="tenant", work_item_id="item")
    assert get_error.value.retryable is True
