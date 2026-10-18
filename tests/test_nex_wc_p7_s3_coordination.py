from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from nex_wc.coordination import (
    CoordinationError,
    InMemoryCoordinationRepository,
    RoutingPolicy,
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.work_items import InMemoryWorkItemRepository, WorkItemService
from nex_wc.coordination_api import register_coordination_routes
from nex_wc.coordination_clients import (
    HttpAgentCandidateSource,
    HttpAuthorizationSource,
    HttpSourceNotFound,
)
import nex_wc.coordination_clients as client_module


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 18, 4, 0, tzinfo=UTC)
PROFILE = "agent-profile://pa/project-budget-read/v1"


def _payload():
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "delegation-s3",
            "tenant_id": "tenant-s3",
            "parent_agent_execution_id": "parent-execution-s3",
            "parent_executable_plan_id": "parent-plan-s3",
            "parent_executable_step_id": "parent-step-s3",
            "delegation_revision": 1,
            "goal": "Check project budget",
            "work_class": "ANALYSIS",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": "project-s3"},
            "project_scope_ref": "project-s3",
            "result_contract_ref": "urn:nex:result:budget:1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "trace-s3",
            "causation_id": "cause-s3",
        },
        "requester": {"entity_type": "USER", "entity_id": "requester-s3"},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-s3"},
    }


def _candidate(**overrides):
    value = {
        "schema_version": "2.1",
        "tenant_id": "tenant-s3",
        "agent_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "agent_type": "PA",
        "profile_ref": PROFILE,
        "status": "ACTIVE",
        "project_id": "project-s3",
        "created_at": "2026-10-18T03:00:00Z",
        "version": 1,
    }
    value.update(overrides)
    return value


class _Agents:
    def __init__(self, candidates=None):
        self.candidates = list(candidates or [_candidate()])

    def list_agents(self, **kwargs):
        return list(self.candidates)

    def get_agent(self, *, tenant_id, agent_id):
        return next(
            (
                item
                for item in self.candidates
                if item["tenant_id"] == tenant_id and item["agent_id"] == agent_id
            ),
            None,
        )


class _Authorization:
    def __init__(self, **overrides):
        self.value = {
            "active": True,
            "scopes": ["work:claim"],
            "revision_hash": "a" * 64,
        }
        self.value.update(overrides)

    def effective_authorization(self, **kwargs):
        return dict(self.value)


def _runtime(*, candidates=None, authorization=None):
    work_repo = InMemoryWorkItemRepository()
    work_items = WorkItemService(
        work_repo,
        id_factory=lambda: "11111111-1111-4111-8111-111111111131",
        clock=lambda: NOW,
    )
    item = work_items.create(_payload())["work_item"]
    identifiers = iter(
        (
            "22222222-2222-4222-8222-222222222231",
            "33333333-3333-4333-8333-333333333331",
            "44444444-4444-4444-8444-444444444431",
            "55555555-5555-4555-8555-555555555531",
            "66666666-6666-4666-8666-666666666631",
            "77777777-7777-4777-8777-777777777731",
        )
    )
    service = WorkCoordinationService(
        InMemoryCoordinationRepository(work_repo),
        candidate_source=_Agents(candidates),
        authorization_source=authorization or _Authorization(),
        id_factory=lambda: next(identifiers),
        token_factory=lambda: "lease-token-s3",
        clock=lambda: NOW,
    )
    return service, item


def test_s3_deterministic_route_and_atomic_claim_are_contract_valid():
    service, item = _runtime()
    route = service.route(
        tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1
    )
    assert route["decision"] == "ROUTED"
    assert route["target_ref"] == _candidate()["agent_id"]
    assert route["candidate_set"][0]["eligible"] is True

    route_schema = json.loads(
        (ROOT / "docs/transition/P7/contracts/p7-routing-decision-v2.1.schema.json").read_text()
    )
    Draft202012Validator(route_schema, format_checker=FormatChecker()).validate(route)

    claimed = service.claim(
        tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=2
    )
    assert claimed["work_item"]["state"] == "ASSIGNED"
    assert claimed["claim"]["claim_generation"] == 1
    assert claimed["claim"]["lease_verifier"].startswith("sha256:")
    assert claimed["lease_token"] == "lease-token-s3"
    assert "lease-token-s3" not in json.dumps(claimed["claim"])

    handoff_schema = json.loads(
        (ROOT / "docs/transition/P7/contracts/p7-claim-execution-handoff-v2.1.schema.json").read_text()
    )
    Draft202012Validator(handoff_schema, format_checker=FormatChecker()).validate(
        claimed["handoff"]
    )


@pytest.mark.parametrize(
    ("candidate", "reason"),
    (
        (_candidate(status="SUSPENDED"), "AGENT_INACTIVE"),
        (_candidate(agent_type="CA"), "AGENT_TYPE_MISMATCH"),
        (_candidate(project_id="other"), "PROJECT_SCOPE_MISMATCH"),
        (_candidate(profile_ref="other-profile"), "PROFILE_NOT_ADMITTED"),
    ),
)
def test_s3_unroutable_candidate_reason_codes(candidate, reason):
    service, item = _runtime(candidates=[candidate])
    route = service.route(
        tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1
    )
    assert route["decision"] == "UNROUTABLE"
    assert reason in route["candidate_set"][0]["reason_codes"]
    with pytest.raises(CoordinationError):
        service.claim(
            tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1
        )


def test_s3_missing_policy_is_unroutable_and_deterministic_order_wins():
    service, item = _runtime()
    service._policy = RoutingPolicy({})
    route = service.route(
        tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1
    )
    assert "CAPABILITY_POLICY_MISSING" in route["candidate_set"][0]["reason_codes"]

    second = _candidate(agent_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    first = _candidate(agent_id="00000000-0000-4000-8000-000000000001")
    service, item = _runtime(candidates=[second, first])
    route = service.route(
        tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1
    )
    assert route["target_ref"] == first["agent_id"]


@pytest.mark.parametrize(
    "authorization",
    (
        _Authorization(active=False),
        _Authorization(scopes=[]),
        _Authorization(revision_hash=""),
    ),
)
def test_s3_fresh_oa_authorization_fails_closed(authorization):
    service, item = _runtime(authorization=authorization)
    service.route(
        tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1
    )
    with pytest.raises(CoordinationError):
        service.claim(
            tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=2
        )


def test_s3_stale_versions_duplicate_claim_and_tenant_scope_fail_closed():
    service, item = _runtime()
    with pytest.raises(CoordinationError):
        service.route(
            tenant_id="other", work_item_id=item["work_item_id"], expected_version=1
        )
    service.route(
        tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1
    )
    with pytest.raises(CoordinationError):
        service.route(
            tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1
        )
    service.claim(
        tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=2
    )
    with pytest.raises(CoordinationError):
        service.claim(
            tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=2
        )


def test_s3_in_memory_repository_conflict_guards_are_explicit():
    work_repo = InMemoryWorkItemRepository()
    repository = InMemoryCoordinationRepository(work_repo)
    decision = {
        "routing_decision_id": "22222222-2222-4222-8222-222222222232",
        "decision": "ROUTED",
        "decided_at": "2026-10-18T04:00:00Z",
    }
    with pytest.raises(CoordinationError) as missing_route:
        repository.save_routing_decision(
            tenant_id="tenant-s3",
            work_item_id="missing",
            expected_version=1,
            decision=decision,
        )
    assert missing_route.value.error_code == "wc.work_item_not_found"

    item = WorkItemService(
        work_repo,
        id_factory=lambda: "11111111-1111-4111-8111-111111111132",
        clock=lambda: NOW,
    ).create(_payload())["work_item"]
    with pytest.raises(CoordinationError) as stale_route:
        repository.save_routing_decision(
            tenant_id=item["tenant_id"],
            work_item_id=item["work_item_id"],
            expected_version=2,
            decision=decision,
        )
    assert stale_route.value.error_code == "wc.work_item_route_conflict"

    claim_args = {
        "tenant_id": item["tenant_id"],
        "work_item_id": item["work_item_id"],
        "expected_version": 1,
        "selected_agent": _candidate(),
        "authorization": {
            "subject_id": "requester-s3",
            "revision_hash": "a" * 64,
        },
        "identifiers": {
            "assignment_id": "33333333-3333-4333-8333-333333333332",
            "claim_id": "44444444-4444-4444-8444-444444444432",
            "handoff_id": "55555555-5555-4555-8555-555555555532",
            "outbox_id": "66666666-6666-4666-8666-666666666632",
            "event_id": "77777777-7777-4777-8777-777777777732",
        },
        "lease_verifier": "sha256:" + "b" * 64,
        "lease_expires_at": "2026-10-18T04:05:00Z",
        "now": "2026-10-18T04:00:00Z",
    }
    with pytest.raises(CoordinationError) as missing_claim_source:
        repository.commit_claim(**claim_args)
    assert missing_claim_source.value.error_code == "wc.work_item_claim_conflict"

    repository.save_routing_decision(
        tenant_id=item["tenant_id"],
        work_item_id=item["work_item_id"],
        expected_version=1,
        decision=decision,
    )
    repository.commit_claim(**{**claim_args, "expected_version": 2})
    key = (item["tenant_id"], item["work_item_id"])
    work_repo._records[key]["state"] = "ROUTED"
    work_repo._records[key]["work_item"]["state"] = "ROUTED"
    with pytest.raises(CoordinationError) as duplicate:
        repository.commit_claim(**{**claim_args, "expected_version": 3})
    assert duplicate.value.error_code == "wc.active_claim_exists"


def test_s3_claim_rejects_non_routed_latest_decision():
    service, item = _runtime()
    service.route(
        tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1
    )
    key = (item["tenant_id"], item["work_item_id"])
    service._repository._routes[key][-1]["decision"] = "UNROUTABLE"
    with pytest.raises(CoordinationError) as error:
        service.claim(
            tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=2
        )
    assert error.value.error_code == "wc.routing_decision_not_claimable"


@pytest.mark.parametrize(
    "candidate",
    (
        None,
        _candidate(status="SUSPENDED"),
        _candidate(agent_type="CA"),
        _candidate(project_id="other"),
        _candidate(profile_ref="other"),
    ),
)
def test_s3_candidate_revalidation_blocks_changed_authority(candidate):
    agents = _Agents()
    service, item = _runtime()
    service._candidate_source = agents
    service.route(
        tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1
    )
    agents.candidates = [] if candidate is None else [candidate]
    with pytest.raises(CoordinationError) as error:
        service.claim(
            tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=2
        )
    assert error.value.error_code == "wc.claim_candidate_ineligible"


def test_s3_lease_policy_bounds_and_error_text():
    repository = InMemoryCoordinationRepository(InMemoryWorkItemRepository())
    with pytest.raises(CoordinationError):
        WorkCoordinationService(
            repository,
            candidate_source=_Agents(),
            authorization_source=_Authorization(),
            lease_seconds=1,
        )
    assert str(CoordinationError("code", "detail")) == "detail"


def test_s3_http_api_routes_and_claims_with_service_auth():
    service, item = _runtime()
    app = build_service_app(SERVICE_SPECS["nex-wc"])
    register_coordination_routes(app, service=service)
    client = TestClient(app)
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-wc")
    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "X-NeX-Tenant-Id": item["tenant_id"],
    }
    assert client.post(
        f"/api/v1/work-items/{item['work_item_id']}/route",
        headers={"X-NeX-Tenant-Id": item["tenant_id"]},
        json={"expected_version": 1},
    ).status_code == 401
    routed = client.post(
        f"/api/v1/work-items/{item['work_item_id']}/route",
        headers=headers,
        json={"expected_version": 1},
    )
    assert routed.status_code == 200
    conflict = client.post(
        f"/api/v1/work-items/{item['work_item_id']}/route",
        headers=headers,
        json={"expected_version": 1},
    )
    assert conflict.status_code == 409
    claimed = client.post(
        f"/api/v1/work-items/{item['work_item_id']}/claim",
        headers=headers,
        json={"expected_version": 2},
    )
    assert claimed.status_code == 200
    assert claimed.json()["handoff"]["claim_generation"] == 1
    duplicate = client.post(
        f"/api/v1/work-items/{item['work_item_id']}/claim",
        headers=headers,
        json={"expected_version": 2},
    )
    assert duplicate.status_code == 409
    assert client.post(
        f"/api/v1/work-items/{item['work_item_id']}/claim",
        headers={"X-NeX-Tenant-Id": item["tenant_id"]},
        json={"expected_version": 2},
    ).status_code == 401


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def test_s3_http_sources_parse_bounded_registry_and_authorization(monkeypatch):
    responses = iter(
        (
            _Response({"agents": [_candidate()]}),
            _Response(_candidate()),
            _Response({"authorization": {"scopes": ["work:claim"], "revision_hash": "a" * 64}}),
        )
    )
    monkeypatch.setattr(client_module, "urlopen", lambda *args, **kwargs: next(responses))
    agents = HttpAgentCandidateSource(
        base_url="http://ae", service_token="token"
    )
    assert len(
        agents.list_agents(tenant_id="tenant", agent_type="PA", project_id="project")
    ) == 1
    assert agents.get_agent(tenant_id="tenant", agent_id="agent")["agent_type"] == "PA"
    authorization = HttpAuthorizationSource(
        base_url="http://oa", service_token="token"
    ).effective_authorization(tenant_id="tenant", subject_id="subject")
    assert authorization["active"] is True


def test_s3_http_sources_fail_closed_for_missing_or_invalid_data(monkeypatch):
    from urllib.error import HTTPError, URLError

    agents = HttpAgentCandidateSource(base_url="http://ae", service_token="token")
    monkeypatch.setattr(
        client_module,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HTTPError("http://ae", 404, "missing", {}, None)
        ),
    )
    assert agents.get_agent(tenant_id="tenant", agent_id="missing") is None
    with pytest.raises(HttpSourceNotFound):
        client_module._get_json(
            "http://ae/missing", service_token="token", timeout_seconds=1
        )
    monkeypatch.setattr(
        client_module,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HTTPError("http://ae", 503, "down", {}, None)
        ),
    )
    with pytest.raises(RuntimeError, match="HTTP 503"):
        client_module._get_json("http://ae", service_token="token", timeout_seconds=1)
    monkeypatch.setattr(
        client_module,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("down")),
    )
    with pytest.raises(RuntimeError, match="source request failed"):
        client_module._get_json("http://ae", service_token="token", timeout_seconds=1)
    with pytest.raises(RuntimeError):
        client_module._get_json(
            "http://ae", service_token="", timeout_seconds=1
        )

    monkeypatch.setattr(client_module, "urlopen", lambda *args, **kwargs: _Response([]))
    with pytest.raises(RuntimeError):
        client_module._get_json("http://ae", service_token="token", timeout_seconds=1)
    monkeypatch.setattr(client_module, "urlopen", lambda *args, **kwargs: _Response({"agents": {}}))
    with pytest.raises(RuntimeError):
        agents.list_agents(tenant_id="tenant", agent_type="PA", project_id="project")
    monkeypatch.setattr(client_module, "urlopen", lambda *args, **kwargs: _Response({}))
    with pytest.raises(RuntimeError):
        HttpAuthorizationSource(base_url="http://oa", service_token="token").effective_authorization(
            tenant_id="tenant", subject_id="subject"
        )


def test_s3_sql_repository_maps_database_failures_to_retryable_error():
    engine = create_engine("sqlite:///:memory:")
    repository = SqlAlchemyCoordinationRepository(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
    with pytest.raises(CoordinationError) as get_error:
        repository.get_work_item(tenant_id="tenant", work_item_id="work")
    assert get_error.value.error_code == "wc.coordination_store_unavailable"
    assert get_error.value.retryable is True

    decision = {
        "routing_decision_id": "22222222-2222-4222-8222-222222222239",
        "decision": "ROUTED",
        "decided_at": "2026-10-18T04:00:00Z",
    }
    with pytest.raises(CoordinationError) as route_error:
        repository.save_routing_decision(
            tenant_id="tenant",
            work_item_id="work",
            expected_version=1,
            decision=decision,
        )
    assert route_error.value.retryable is True

    with pytest.raises(CoordinationError) as claim_error:
        repository.commit_claim(
            tenant_id="tenant",
            work_item_id="work",
            expected_version=2,
            selected_agent=_candidate(),
            authorization={"subject_id": "subject", "revision_hash": "a" * 64},
            identifiers={
                "assignment_id": "33333333-3333-4333-8333-333333333339",
                "claim_id": "44444444-4444-4444-8444-444444444439",
                "handoff_id": "55555555-5555-4555-8555-555555555539",
                "outbox_id": "66666666-6666-4666-8666-666666666639",
                "event_id": "77777777-7777-4777-8777-777777777739",
            },
            lease_verifier="sha256:" + "c" * 64,
            lease_expires_at="2026-10-18T04:05:00Z",
            now="2026-10-18T04:00:00Z",
        )
    assert claim_error.value.retryable is True
    engine.dispose()


class _BrokenSource:
    def list_agents(self, **kwargs):
        raise RuntimeError("down")

    def get_agent(self, **kwargs):
        raise RuntimeError("down")

    def effective_authorization(self, **kwargs):
        raise RuntimeError("down")


def test_s3_dependency_failures_are_retryable_and_scope_shape_fails_closed():
    service, item = _runtime()
    service._candidate_source = _BrokenSource()
    with pytest.raises(CoordinationError) as route_error:
        service.route(
            tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1
        )
    assert route_error.value.retryable is True

    service, item = _runtime()
    service.route(tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1)
    service._candidate_source = _BrokenSource()
    with pytest.raises(CoordinationError) as agent_error:
        service.claim(tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=2)
    assert agent_error.value.error_code == "wc.agent_registry_unavailable"

    service, item = _runtime()
    service.route(tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1)
    service._authorization_source = _BrokenSource()
    with pytest.raises(CoordinationError) as auth_error:
        service.claim(tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=2)
    assert auth_error.value.error_code == "wc.oa_authorization_unavailable"

    service, item = _runtime(authorization=_Authorization(scopes="work:claim"))
    service.route(tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1)
    with pytest.raises(CoordinationError):
        service.claim(tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=2)
