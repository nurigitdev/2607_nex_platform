from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import nex_ae_api.project_delegation_planning as delegation_module
import pytest
from nex_ae_api.project_agent_lifecycle import (
    AE_PROJECT_AGENT_METADATA,
    AE_PROJECT_AGENT_SYNC_TABLE,
)
from nex_ae_api.project_delegation_planning import (
    M1_PROJECT_DELEGATION_ACTION,
    M1_PROJECT_DELEGATION_CAPABILITY_ID,
    HttpOaProjectDecisionSource,
    ProjectDelegationIntentActivator,
    ProjectDelegationPlanningError,
    ProjectDelegationPlanningProfile,
    SqlAlchemyActiveProjectAgentSource,
    build_http_project_delegation_activator,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

TENANT = "VO00"
SUBJECT = "employee-0001"
PROJECT_CODE = "VO00D260001"
PROJECT_ID = "d30c5668-48f7-4f4c-8d8f-1de6e4f0a50a"
AGENT_ID = "b4758c4a-c96f-450b-b282-c947cce80ab3"
EXECUTION_ID = "4192d8ca-4877-4813-87e9-a00ebf17267d"


class _Eos:
    def __init__(self, project: dict[str, object] | None = None) -> None:
        self.project = project or {
            "project_code": PROJECT_CODE,
            "status": "ACTIVE",
            "version": 3,
        }

    def resolve_active_project(self, **_kwargs: object) -> dict[str, object]:
        return dict(self.project)


class _Oa:
    def __init__(self, decision: dict[str, object] | None = None) -> None:
        self.decision = decision

    def decide(self, **kwargs: object) -> dict[str, object]:
        return dict(
            self.decision
            or {
                "decision_ref": "sha256:" + "1" * 64,
                "tenant_id": kwargs["tenant_id"],
                "subject_id": kwargs["subject_id"],
                "project_code": kwargs["project_code"],
                "action": kwargs["action"],
                "allowed": True,
                "reason_code": "ALLOW",
                "source_version": 3,
            }
        )


class _Agents:
    def __init__(self, agent: dict[str, object] | None = None) -> None:
        self.agent = agent or _agent_row()

    def resolve_active(self, **_kwargs: object) -> dict[str, object]:
        return dict(self.agent)


def _candidate(*, confidence: object = 0.98) -> dict[str, object]:
    return {
        "entity_selectors": [
            {
                "selector_id": "E1",
                "selector_type": "QUERY_TERM",
                "value": PROJECT_CODE,
                "confidence": confidence,
            }
        ]
    }


def _work_intent() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1.1",
        "work_intent_id": "252d1ef9-e197-40ef-916f-119d69bf9448",
        "intent_revision": 1,
        "execution_id": EXECUTION_ID,
        "intent_label": M1_PROJECT_DELEGATION_CAPABILITY_ID,
        "goal": "Answer the admitted user request.",
        "work_class": "QUERY",
        "required_capability_hints": ["AE.CHAT.COMPATIBILITY"],
        "entity_selectors": [],
        "constraints": [],
        "completion_criteria": [],
        "clarification": {"status": "NOT_REQUIRED", "reasons": []},
        "confidence": {"overall": 0.98, "intent": 0.98, "entities": None},
    }
    value["intent_hash"] = semantic_sha256_hash_ref(value)
    return value


def _agent_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "tenant_id": TENANT,
        "project_id": PROJECT_ID,
        "project_code": PROJECT_CODE,
        "project_state": "ACTIVE",
        "project_version": 3,
        "profile_policy_ref": "policy://project-agent/v1",
        "profile_policy_hash": "sha256:" + "2" * 64,
        "agent_id": AGENT_ID,
        "agent_status": "ACTIVE",
        "capability_mode": "ORDINARY",
        "last_event_id": str(uuid4()),
        "last_event_payload_hash": "sha256:" + "3" * 64,
        "created_at": datetime(2026, 11, 16, tzinfo=UTC),
        "updated_at": datetime(2026, 11, 16, tzinfo=UTC),
    }
    row.update(overrides)
    return row


def _activate(
    *,
    project: dict[str, object] | None = None,
    decision: dict[str, object] | None = None,
    agent: dict[str, object] | None = None,
    candidate: dict[str, object] | None = None,
    work_intent: dict[str, object] | None = None,
):
    return ProjectDelegationIntentActivator(
        eos=_Eos(project),
        oa=_Oa(decision),
        project_agents=_Agents(agent),
    ).activate(
        candidate=candidate or _candidate(),
        work_intent=work_intent or _work_intent(),
        tenant_id=TENANT,
        principal_id=SUBJECT,
        resolved_at="2026-11-16T01:00:00Z",
    )


@pytest.mark.parametrize(
    ("project", "agent", "work_intent"),
    (
        (
            {"project_code": "VO00D260002", "status": "ACTIVE", "version": 3},
            None,
            None,
        ),
        (
            {"project_code": PROJECT_CODE, "status": "INACTIVE", "version": 3},
            None,
            None,
        ),
        (
            {"project_code": PROJECT_CODE, "status": "ACTIVE", "version": 0},
            None,
            None,
        ),
        (None, _agent_row(project_code="VO00D260002"), None),
        (
            None,
            None,
            {
                **_work_intent(),
                "intent_label": "FINANCE.VOUCHER.READ",
            },
        ),
    ),
)
def test_activation_rejects_capability_and_authoritative_identity_mismatch(
    project: dict[str, object] | None,
    agent: dict[str, object] | None,
    work_intent: dict[str, object] | None,
) -> None:
    with pytest.raises(ProjectDelegationPlanningError) as rejected:
        _activate(project=project, agent=agent, work_intent=work_intent)

    assert rejected.value.error_code == "PROJECT_DELEGATION_INVALID"
    assert rejected.value.retryable is False


@pytest.mark.parametrize(
    "candidate",
    (
        {"entity_selectors": {}},
        _candidate(confidence=True),
        _candidate(confidence="0.98"),
    ),
)
def test_activation_rejects_malformed_selector_shapes(
    candidate: dict[str, object],
) -> None:
    with pytest.raises(ProjectDelegationPlanningError) as rejected:
        _activate(candidate=candidate)

    assert rejected.value.error_code == "PROJECT_DELEGATION_INVALID"


@pytest.mark.parametrize("mutation", ("schema", "hash"))
def test_activation_rejects_noncanonical_work_intent(mutation: str) -> None:
    intent = _work_intent()
    if mutation == "schema":
        intent["schema_version"] = "1.0"
        intent["intent_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in intent.items() if key != "intent_hash"}
        )
    else:
        intent["intent_hash"] = "sha256:" + "0" * 64

    with pytest.raises(ProjectDelegationPlanningError) as rejected:
        _activate(work_intent=intent)

    assert rejected.value.error_code == "PROJECT_DELEGATION_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("tenant_id", "OTHER"),
        ("subject_id", "employee-9999"),
        ("project_code", "VO00D260002"),
        ("action", "finance:voucher-candidate:read"),
        ("allowed", False),
        ("reason_code", "PROJECT_GRANT_NOT_FOUND"),
        ("decision_ref", None),
        ("source_version", 2),
    ),
)
def test_oa_decision_mismatch_is_denial_not_infrastructure_failure(
    field: str, value: object
) -> None:
    decision: dict[str, object] = {
        "decision_ref": "sha256:" + "1" * 64,
        "tenant_id": TENANT,
        "subject_id": SUBJECT,
        "project_code": PROJECT_CODE,
        "action": M1_PROJECT_DELEGATION_ACTION,
        "allowed": True,
        "reason_code": "ALLOW",
        "source_version": 3,
    }
    decision[field] = value

    with pytest.raises(ProjectDelegationPlanningError) as denied:
        _activate(decision=decision)

    assert denied.value.error_code == "PROJECT_AUTHORIZATION_DENIED"
    assert denied.value.retryable is False


def test_malformed_oa_source_version_is_invalid_not_denied() -> None:
    decision = {
        "decision_ref": "sha256:" + "1" * 64,
        "tenant_id": TENANT,
        "subject_id": SUBJECT,
        "project_code": PROJECT_CODE,
        "action": M1_PROJECT_DELEGATION_ACTION,
        "allowed": True,
        "reason_code": "ALLOW",
        "source_version": 0,
    }

    with pytest.raises(ProjectDelegationPlanningError) as malformed:
        _activate(decision=decision)

    assert malformed.value.error_code == "PROJECT_DELEGATION_INVALID"


def test_http_oa_failure_distinguishes_retryable_timeout_from_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        delegation_module,
        "resolve_ae_outbound_service_token",
        lambda _token, *, audience: audience,
    )

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("offline", request=request)

    retryable_client = httpx.Client(transport=httpx.MockTransport(timeout))
    with pytest.raises(ProjectDelegationPlanningError) as unavailable:
        HttpOaProjectDecisionSource(
            "https://oa.test", "token", retryable_client
        ).decide(
            tenant_id=TENANT,
            subject_id=SUBJECT,
            project_code=PROJECT_CODE,
            action=M1_PROJECT_DELEGATION_ACTION,
            correlation_id=EXECUTION_ID,
            minimum_source_version=3,
        )
    assert unavailable.value.error_code == "PROJECT_AUTHORIZATION_UNAVAILABLE"
    assert unavailable.value.retryable is True

    denied_client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(403))
    )
    with pytest.raises(ProjectDelegationPlanningError) as denied:
        HttpOaProjectDecisionSource("https://oa.test", "token", denied_client).decide(
            tenant_id=TENANT,
            subject_id=SUBJECT,
            project_code=PROJECT_CODE,
            action=M1_PROJECT_DELEGATION_ACTION,
            correlation_id=EXECUTION_ID,
            minimum_source_version=3,
        )
    assert denied.value.error_code == "PROJECT_AUTHORIZATION_UNAVAILABLE"
    assert denied.value.retryable is False


def test_http_activator_configuration_is_disabled_complete_or_fail_closed(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'ae.db'}")
    factory = sessionmaker(engine, expire_on_commit=False)

    assert build_http_project_delegation_activator({}, session_factory=factory) is None
    with pytest.raises(ProjectDelegationPlanningError) as incomplete:
        build_http_project_delegation_activator(
            {"NEX_EOS_BASE_URL": "https://eos.test"},
            session_factory=factory,
        )
    assert incomplete.value.error_code == "PROJECT_DELEGATION_CONFIGURATION_INCOMPLETE"

    activated = build_http_project_delegation_activator(
        {
            "NEX_EOS_BASE_URL": "https://eos.test",
            "NEX_OA_BASE_URL": "https://oa.test",
            "NEX_AE_TO_EOS_SERVICE_TOKEN": "eos-token",
            "NEX_AE_TO_OA_SERVICE_TOKEN": "oa-token",
        },
        session_factory=factory,
    )
    assert isinstance(activated, ProjectDelegationIntentActivator)
    assert activated.eos.base_url == "https://eos.test"
    assert activated.oa.base_url == "https://oa.test"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("project_state", "CLOSING"),
        ("agent_status", "SUSPENDED"),
        ("capability_mode", "CLOSURE"),
    ),
)
def test_project_agent_projection_rejects_each_nonordinary_state(
    tmp_path: Path, field: str, value: str
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / field}.db")
    AE_PROJECT_AGENT_METADATA.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.execute(
            AE_PROJECT_AGENT_SYNC_TABLE.insert().values(
                **_agent_row(**{field: value})
            )
        )

    with pytest.raises(ProjectDelegationPlanningError) as inactive:
        SqlAlchemyActiveProjectAgentSource(factory).resolve_active(
            tenant_id=TENANT, project_code=PROJECT_CODE
        )

    assert inactive.value.error_code == "PROJECT_AGENT_NOT_ACTIVE"
    assert inactive.value.retryable is False


def test_project_agent_projection_rejects_multiple_rows(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'duplicate.db'}")
    AE_PROJECT_AGENT_METADATA.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.execute(AE_PROJECT_AGENT_SYNC_TABLE.insert().values(**_agent_row()))
        session.execute(
            AE_PROJECT_AGENT_SYNC_TABLE.insert().values(
                **_agent_row(project_id=str(uuid4()), agent_id=str(uuid4()))
            )
        )

    with pytest.raises(ProjectDelegationPlanningError) as ambiguous:
        SqlAlchemyActiveProjectAgentSource(factory).resolve_active(
            tenant_id=TENANT, project_code=PROJECT_CODE
        )

    assert ambiguous.value.error_code == "PROJECT_AGENT_NOT_UNIQUE"


def test_project_agent_projection_database_failure_is_retryable() -> None:
    def unavailable():
        raise SQLAlchemyError("database unavailable")

    with pytest.raises(ProjectDelegationPlanningError) as failure:
        SqlAlchemyActiveProjectAgentSource(unavailable).resolve_active(  # type: ignore[arg-type]
            tenant_id=TENANT, project_code=PROJECT_CODE
        )

    assert failure.value.error_code == "PROJECT_AGENT_SOURCE_UNAVAILABLE"
    assert failure.value.retryable is True


def test_profile_identity_and_error_text_are_deterministic() -> None:
    profile = ProjectDelegationPlanningProfile()
    error = ProjectDelegationPlanningError("TEST", "stable detail")

    assert profile.source_identity == ProjectDelegationPlanningProfile().source_identity
    assert profile.source_identity.startswith("nex-ae:project-delegation:sha256:")
    assert str(error) == "stable detail"
