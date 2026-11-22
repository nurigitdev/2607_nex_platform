from __future__ import annotations

import io
import json
import os
import uuid
from datetime import UTC, date, datetime
from urllib.error import HTTPError, URLError

import pytest
import psycopg
from nex_oa.project_entitlements import (
    OaProjectAuthorizationDecisionService,
    SqlAlchemyOaProjectGrantRepository,
)
from nex_runtime import psycopg_database_url
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from nex_eos.authorization import (
    EosAuthorizationError,
    EosAuthorizationTarget,
    EosVoucherAuthorizationClient,
)
from nex_eos.business_transactions import EOS_METADATA
from nex_eos.project_operations import (
    PROJECT_CREATE_SCOPE,
    PROJECT_MEMBERSHIP_MANAGE_SCOPE,
    PROJECT_READ_SCOPE,
    EosGovernedProjectError,
    EosGovernedProjectService,
)
from nex_eos.project_authorization import (
    EosProjectAuthorizationContext,
    EosProjectAuthorizationError,
    EosProjectAuthorizationEvidence,
    EosProjectAuthorizationGate,
    HttpOaProjectAuthorizationDecisionSource,
    SqlAlchemyEosProjectAuthorizationContextSource,
)
from nex_eos.projects import EOS_NVT_PROJECT_TABLE, EOS_PROJECT_TABLE
from nex_eos.project_work_assignments import (
    PROJECT_WORK_ASSIGNMENT_MANAGE_SCOPE,
    PROJECT_WORK_ASSIGNMENT_PERFORM_SCOPE,
    PROJECT_WORK_ASSIGNMENT_READ_SCOPE,
    EosProjectWorkAssignmentError,
    EosProjectWorkAssignmentService,
)
from nex_eos.project_work_codes import (
    PROJECT_WORK_CODE_APPROVE_SCOPE,
    PROJECT_WORK_CODE_READ_SCOPE,
    EosProjectBusinessService,
    EosProjectWorkCodeError,
)
from nex_eos.scoped_approvals import (
    ACCOUNTING_APPROVAL_REQUEST_SCOPE,
    EosScopedApprovalError,
    EosScopedApprovalService,
)

TENANT = "VO00"
SUBJECT = "subject-finance"
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
NVT_PROJECT_ID = "22222222-2222-4222-8222-222222222222"
PROJECT_CODE = "VO00D260001"
ACTION = "finance:voucher-candidate:create"
CORRELATION = "corr-w40-s05"
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
EOS_DATABASE_URL = os.getenv(
    "NEX_EOS_TEST_DATABASE_URL",
    "postgresql+psycopg://nex_eos_user:nuri1004@127.0.0.1:5432/nex_eos_test",
)
OA_DATABASE_URL = os.getenv(
    "NEX_OA_TEST_DATABASE_URL",
    "postgresql+psycopg://nex_oa_user:nuri1004@127.0.0.1:5432/nex_oa_test",
)
POSTGRES_SMOKE = os.getenv("NEX_MYBEE_W40_CA01_S05_POSTGRES_SMOKE") == "1"


class ContextSource:
    def __init__(self, value=None, *, error: Exception | None = None) -> None:
        self.value = value if value is not None else _context()
        self.error = error

    def resolve(self, **kwargs):
        if self.error is not None:
            raise self.error
        return self.value


class DecisionSource:
    def __init__(self, value=None, *, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.requests = []

    def decide(self, payload):
        self.requests.append(dict(payload))
        if self.error is not None:
            raise self.error
        return self.value or _decision(payload)


class EffectiveAuthorizationSource:
    def __init__(self, revision: str = "b" * 64, scopes=None) -> None:
        self.revision = revision
        self.scopes = list(scopes or [ACTION])

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": self.scopes,
            "revision_hash": self.revision,
        }


class ProjectGate:
    def __init__(self, *, revision: str = HASH_B, error=None) -> None:
        self.revision = revision
        self.error = error
        self.requests = []

    def authorize(self, **kwargs):
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        return EosProjectAuthorizationEvidence(
            decision_ref=HASH_A,
            project_code=PROJECT_CODE,
            project_role="OWNER",
            project_status="ACTIVE",
            source_version=3,
            projection_event_hash=HASH_A,
            authorization_revision_hash=self.revision,
            decided_at="2026-11-12T09:00:00Z",
        )


def _context(**overrides) -> EosProjectAuthorizationContext:
    values = {
        "tenant_id": TENANT,
        "project_id": PROJECT_ID,
        "project_code": PROJECT_CODE,
        "project_status": "ACTIVE",
        "authorization_sync_state": "IN_SYNC",
        "authorization_version": 3,
    }
    values.update(overrides)
    return EosProjectAuthorizationContext(**values)


def _decision(request, **overrides):
    value = {
        "decision_schema_version": "oa_project_authorization_decision.v1",
        "decision_ref": HASH_A,
        "tenant_id": request["tenant_id"],
        "subject_id": request["subject_id"],
        "project_code": request["project_code"],
        "action": request["action"],
        "allowed": True,
        "reason_code": "ALLOW",
        "project_role": "OWNER",
        "project_status": "ACTIVE",
        "grant_status": "ACTIVE",
        "source_version": request["minimum_source_version"],
        "minimum_source_version": request["minimum_source_version"],
        "projection_event_hash": HASH_A,
        "applicable_global_scopes": [request["action"]],
        "authorization_revision_hash": HASH_B,
        "correlation_id": request["correlation_id"],
        "decided_at": "2026-11-12T09:00:00Z",
    }
    value.update(overrides)
    return value


def _gate(*, context=None, decision=None):
    source = DecisionSource(decision)
    return (
        EosProjectAuthorizationGate(
            context_source=ContextSource(context),
            decision_source=source,
        ),
        source,
    )


def _authorize(gate):
    return gate.authorize(
        tenant_id=TENANT,
        subject_id=SUBJECT,
        project_id=PROJECT_ID,
        expected_project_code=PROJECT_CODE,
        action=ACTION,
        correlation_id=CORRELATION,
    )


def test_gate_binds_exact_project_code_source_version_and_action() -> None:
    gate, source = _gate()

    evidence = _authorize(gate)

    assert evidence.project_code == PROJECT_CODE
    assert evidence.source_version == 3
    assert evidence.authorization_revision_hash == HASH_B
    assert source.requests == [
        {
            "tenant_id": TENANT,
            "subject_id": SUBJECT,
            "project_code": PROJECT_CODE,
            "action": ACTION,
            "correlation_id": CORRELATION,
            "minimum_source_version": 3,
        }
    ]


@pytest.mark.parametrize(
    ("context", "expected_reason"),
    [
        (None, "PROJECT_NOT_FOUND"),
        (_context(authorization_sync_state="PENDING"), "NOT_SYNCHRONIZED"),
        (_context(authorization_version=0), "NOT_SYNCHRONIZED"),
    ],
)
def test_gate_denies_missing_or_unsynchronized_project(context, expected_reason) -> None:
    source = ContextSource(context)
    if context is None:
        source.value = None
    gate = EosProjectAuthorizationGate(
        context_source=source,
        decision_source=DecisionSource(),
    )

    with pytest.raises(EosProjectAuthorizationError) as caught:
        _authorize(gate)

    assert caught.value.status_code == 403
    assert expected_reason in str(caught.value.reason_code)


def test_gate_denies_project_code_mismatch_without_calling_oa() -> None:
    decision = DecisionSource()
    gate = EosProjectAuthorizationGate(
        context_source=ContextSource(),
        decision_source=decision,
    )

    with pytest.raises(EosProjectAuthorizationError) as caught:
        gate.authorize(
            tenant_id=TENANT,
            subject_id=SUBJECT,
            project_id=PROJECT_ID,
            expected_project_code="VO00M260001",
            action=ACTION,
            correlation_id=CORRELATION,
        )

    assert caught.value.reason_code == "PROJECT_CODE_MISMATCH"
    assert decision.requests == []


def test_gate_preserves_explicit_oa_denial_reason() -> None:
    request = {
        "tenant_id": TENANT,
        "subject_id": SUBJECT,
        "project_code": PROJECT_CODE,
        "action": ACTION,
        "correlation_id": CORRELATION,
        "minimum_source_version": 3,
    }
    denied = _decision(
        request,
        allowed=False,
        reason_code="PROJECT_ROLE_INSUFFICIENT",
        project_role="VIEWER",
        applicable_global_scopes=[ACTION],
    )
    gate, _ = _gate(decision=denied)

    with pytest.raises(EosProjectAuthorizationError) as caught:
        _authorize(gate)

    assert caught.value.status_code == 403
    assert caught.value.reason_code == "PROJECT_ROLE_INSUFFICIENT"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("decision_ref"),
        lambda value: value.update(tenant_id="OTHER"),
        lambda value: value.update(decision_ref="invalid"),
        lambda value: value.update(authorization_revision_hash="invalid"),
        lambda value: value.update(applicable_global_scopes=None),
        lambda value: value.update(project_status="CLOSING"),
        lambda value: value.update(source_version=2),
        lambda value: value.update(projection_event_hash="invalid"),
    ],
)
def test_gate_fails_closed_on_malformed_or_stale_allow_evidence(mutation) -> None:
    request = {
        "tenant_id": TENANT,
        "subject_id": SUBJECT,
        "project_code": PROJECT_CODE,
        "action": ACTION,
        "correlation_id": CORRELATION,
        "minimum_source_version": 3,
    }
    decision = _decision(request)
    mutation(decision)
    gate, _ = _gate(decision=decision)

    with pytest.raises(EosProjectAuthorizationError) as caught:
        _authorize(gate)

    assert caught.value.status_code == 503
    assert caught.value.retryable is True


def test_gate_maps_provider_and_context_failures_to_unavailable() -> None:
    gate = EosProjectAuthorizationGate(
        context_source=ContextSource(error=RuntimeError("db down")),
        decision_source=DecisionSource(),
    )
    with pytest.raises(EosProjectAuthorizationError) as context_error:
        _authorize(gate)
    assert context_error.value.status_code == 503

    gate = EosProjectAuthorizationGate(
        context_source=ContextSource(),
        decision_source=DecisionSource(error=RuntimeError("oa down")),
    )
    with pytest.raises(EosProjectAuthorizationError) as caught:
        _authorize(gate)
    assert caught.value.error_code == "EOS_PROJECT_AUTHORIZATION_UNAVAILABLE"


def test_sqlalchemy_context_source_reads_exact_project_identity() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.execute(
            EOS_NVT_PROJECT_TABLE.insert().values(
                tenant_id=TENANT,
                nvt_project_id=NVT_PROJECT_ID,
                nvt_project_code="NVT-VO00",
                name="NVT",
                status="ACTIVE",
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_PROJECT_TABLE.insert().values(
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                project_code=PROJECT_CODE,
                project_request_code="VO00R260001",
                purpose_type="D",
                origin="APPROVED_APPLICATION",
                project_owner_subject_id=SUBJECT,
                project_manager_subject_id=SUBJECT,
                agent_sync_state="IN_SYNC",
                authorization_sync_state="IN_SYNC",
                authorization_version=3,
                name="Authorization Project",
                nvt_project_id=NVT_PROJECT_ID,
                parent_project_id=None,
                hierarchy_depth=1,
                status="ACTIVE",
                start_date=date(2026, 1, 1),
                end_date=None,
                currency="KRW",
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    source = SqlAlchemyEosProjectAuthorizationContextSource(sessions)

    assert source.resolve(tenant_id=TENANT, project_id=PROJECT_ID) == _context()
    assert source.resolve(tenant_id=TENANT, project_id=str(uuid.uuid4())) is None
    engine.dispose()
    with pytest.raises(EosProjectAuthorizationError) as caught:
        source.resolve(tenant_id=TENANT, project_id=PROJECT_ID)
    assert caught.value.status_code == 503


class Response:
    def __init__(self, value) -> None:
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8")


def test_http_decision_source_posts_no_cache_service_request(monkeypatch) -> None:
    captured = {}

    def open_request(request, timeout):
        captured.update(request=request, timeout=timeout)
        return Response({"decision": {"allowed": True}})

    monkeypatch.setattr("nex_eos.project_authorization.urlopen", open_request)
    source = HttpOaProjectAuthorizationDecisionSource(
        base_url="http://oa.local/",
        service_token="signed-token",
        timeout_seconds=7.5,
    )

    assert source.decide({"tenant_id": TENANT}) == {"allowed": True}
    request = captured["request"]
    assert request.full_url == "http://oa.local/internal/v1/auth/project-decisions"
    assert request.get_header("Authorization") == "Bearer signed-token"
    assert request.get_header("Cache-control") == "no-store, max-age=0"
    assert captured["timeout"] == 7.5


def test_http_decision_source_rejects_missing_token_and_malformed_document(
    monkeypatch,
) -> None:
    source = HttpOaProjectAuthorizationDecisionSource(
        base_url="http://oa.local", service_token=" "
    )
    with pytest.raises(RuntimeError, match="not configured"):
        source.decide({"tenant_id": TENANT})

    monkeypatch.setattr(
        "nex_eos.project_authorization.urlopen",
        lambda *args, **kwargs: Response({"decision": None}),
    )
    configured = HttpOaProjectAuthorizationDecisionSource(
        base_url="http://oa.local", service_token="signed-token"
    )
    with pytest.raises(RuntimeError, match="malformed"):
        configured.decide({"tenant_id": TENANT})


@pytest.mark.parametrize(
    "failure",
    [
        HTTPError("http://oa", 503, "down", {}, io.BytesIO(b"{}")),
        URLError("down"),
        TimeoutError(),
    ],
)
def test_http_decision_source_rejects_transport_failures(monkeypatch, failure) -> None:
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr("nex_eos.project_authorization.urlopen", fail)
    source = HttpOaProjectAuthorizationDecisionSource(
        base_url="http://oa.local", service_token="signed-token"
    )

    with pytest.raises(RuntimeError, match="request failed"):
        source.decide({"tenant_id": TENANT})


def test_voucher_authorizer_requires_exact_project_gate_and_revision_stability() -> None:
    project_gate = ProjectGate()
    authorizer = EosVoucherAuthorizationClient(
        EffectiveAuthorizationSource(),
        required_scope=ACTION,
        project_authorizer=project_gate,
        clock=lambda: NOW,
    )
    target = EosAuthorizationTarget(
        tenant_id=TENANT,
        subject_id=SUBJECT,
        service_subject="nex-ae-api",
        service_audience="nex-eos",
        service_scopes=("service:call",),
        project_id=PROJECT_ID,
        project_code=PROJECT_CODE,
        resource_type="voucher_candidate",
        resource_id="33333333-3333-4333-8333-333333333333",
        correlation_id=CORRELATION,
    )

    evidence = authorizer.authorize_create(target)

    assert evidence.project_decision_ref == HASH_A
    assert evidence.project_code == PROJECT_CODE
    assert evidence.project_source_version == 3
    assert project_gate.requests[0]["action"] == ACTION

    changed = EosVoucherAuthorizationClient(
        EffectiveAuthorizationSource(),
        required_scope=ACTION,
        project_authorizer=ProjectGate(revision="c" * 64),
    )
    with pytest.raises(EosAuthorizationError) as caught:
        changed.authorize_create(target)
    assert caught.value.status_code == 503


def test_voucher_authorizer_maps_project_denial_without_mutation_boundary() -> None:
    denied = EosProjectAuthorizationError(
        "EOS_PROJECT_AUTHORIZATION_DENIED",
        "denied",
        status_code=403,
        reason_code="PROJECT_GRANT_NOT_FOUND",
    )
    authorizer = EosVoucherAuthorizationClient(
        EffectiveAuthorizationSource(),
        required_scope=ACTION,
        project_authorizer=ProjectGate(error=denied),
    )

    with pytest.raises(EosAuthorizationError) as caught:
        authorizer.authorize_create(
            EosAuthorizationTarget(
                tenant_id=TENANT,
                subject_id=SUBJECT,
                service_subject="nex-ae-api",
                service_audience="nex-eos",
                service_scopes=("service:call",),
                project_id=PROJECT_ID,
                project_code=PROJECT_CODE,
                resource_type="voucher_candidate",
                resource_id="33333333-3333-4333-8333-333333333333",
            )
        )

    assert caught.value.status_code == 403
    assert caught.value.error_code == "EOS_PROJECT_AUTHORIZATION_DENIED"


def test_gate_validates_request_fields_and_accepts_resolved_code() -> None:
    gate, source = _gate()
    evidence = gate.authorize(
        tenant_id=TENANT,
        subject_id=SUBJECT,
        project_id=PROJECT_ID,
        action=ACTION,
        correlation_id=CORRELATION,
    )
    assert evidence.project_code == PROJECT_CODE
    assert source.requests[0]["project_code"] == PROJECT_CODE

    for overrides in (
        {"tenant_id": "bad tenant"},
        {"action": "BAD_ACTION"},
        {"expected_project_code": "bad-code"},
    ):
        request = {
            "tenant_id": TENANT,
            "subject_id": SUBJECT,
            "project_id": PROJECT_ID,
            "action": ACTION,
            "correlation_id": CORRELATION,
            **overrides,
        }
        with pytest.raises(EosProjectAuthorizationError) as caught:
            gate.authorize(**request)
        assert caught.value.status_code == 422


def test_gate_preserves_typed_context_and_decision_errors() -> None:
    typed = EosProjectAuthorizationError(
        "EOS_PROJECT_AUTHORIZATION_UNAVAILABLE",
        "typed failure",
        status_code=503,
        retryable=True,
    )
    context_gate = EosProjectAuthorizationGate(
        context_source=ContextSource(error=typed),
        decision_source=DecisionSource(),
    )
    with pytest.raises(EosProjectAuthorizationError) as context_error:
        _authorize(context_gate)
    assert context_error.value is typed

    decision_gate = EosProjectAuthorizationGate(
        context_source=ContextSource(),
        decision_source=DecisionSource(error=typed),
    )
    with pytest.raises(EosProjectAuthorizationError) as decision_error:
        _authorize(decision_gate)
    assert decision_error.value is typed


@pytest.mark.parametrize(
    ("service_factory", "scope"),
    [
        (
            lambda source, gate: EosGovernedProjectService(
                session_factory=sessionmaker(),
                coordinator=object(),
                authorization_source=source,
                project_authorizer=gate,
            ),
            PROJECT_MEMBERSHIP_MANAGE_SCOPE,
        ),
        (
            lambda source, gate: EosProjectBusinessService(
                session_factory=sessionmaker(),
                coordinator=object(),
                authorization_source=source,
                project_authorizer=gate,
            ),
            PROJECT_WORK_CODE_APPROVE_SCOPE,
        ),
        (
            lambda source, gate: EosProjectWorkAssignmentService(
                session_factory=sessionmaker(),
                coordinator=object(),
                authorization_source=source,
                project_authorizer=gate,
            ),
            PROJECT_WORK_ASSIGNMENT_MANAGE_SCOPE,
        ),
    ],
)
def test_project_write_consumers_require_explicit_project_decision(
    service_factory, scope
) -> None:
    gate = ProjectGate()
    service = service_factory(EffectiveAuthorizationSource(scopes=[scope]), gate)

    admitted = service._authorize(
        tenant_id=TENANT,
        subject_id=SUBJECT,
        required_scope=scope,
        project_id=PROJECT_ID,
    )

    assert admitted["revision_hash"] == "b" * 64
    assert gate.requests[0]["project_id"] == PROJECT_ID
    assert gate.requests[0]["action"] == scope


@pytest.mark.parametrize(
    ("service_factory", "scope", "error_type"),
    [
        (
            lambda source, gate: EosGovernedProjectService(
                session_factory=sessionmaker(),
                coordinator=object(),
                authorization_source=source,
                project_authorizer=gate,
            ),
            PROJECT_MEMBERSHIP_MANAGE_SCOPE,
            EosGovernedProjectError,
        ),
        (
            lambda source, gate: EosProjectBusinessService(
                session_factory=sessionmaker(),
                coordinator=object(),
                authorization_source=source,
                project_authorizer=gate,
            ),
            PROJECT_WORK_CODE_APPROVE_SCOPE,
            EosProjectWorkCodeError,
        ),
        (
            lambda source, gate: EosProjectWorkAssignmentService(
                session_factory=sessionmaker(),
                coordinator=object(),
                authorization_source=source,
                project_authorizer=gate,
            ),
            PROJECT_WORK_ASSIGNMENT_MANAGE_SCOPE,
            EosProjectWorkAssignmentError,
        ),
    ],
)
def test_project_write_consumers_map_explicit_project_denials(
    service_factory, scope, error_type
) -> None:
    denied = EosProjectAuthorizationError(
        "EOS_PROJECT_AUTHORIZATION_DENIED",
        "denied",
        status_code=403,
        reason_code="PROJECT_ROLE_INSUFFICIENT",
    )
    service = service_factory(
        EffectiveAuthorizationSource(scopes=[scope]),
        ProjectGate(error=denied),
    )

    with pytest.raises(error_type) as caught:
        service._authorize(
            tenant_id=TENANT,
            subject_id=SUBJECT,
            required_scope=scope,
            project_id=PROJECT_ID,
        )

    assert caught.value.status_code == 403
    assert caught.value.error_code == "EOS_PROJECT_AUTHORIZATION_DENIED"


@pytest.mark.parametrize(
    ("service_factory", "scope", "project_id"),
    [
        (
            lambda source, gate: EosGovernedProjectService(
                session_factory=sessionmaker(),
                coordinator=object(),
                authorization_source=source,
                project_authorizer=gate,
            ),
            PROJECT_READ_SCOPE,
            PROJECT_ID,
        ),
        (
            lambda source, gate: EosGovernedProjectService(
                session_factory=sessionmaker(),
                coordinator=object(),
                authorization_source=source,
                project_authorizer=gate,
            ),
            PROJECT_CREATE_SCOPE,
            None,
        ),
        (
            lambda source, gate: EosProjectBusinessService(
                session_factory=sessionmaker(),
                coordinator=object(),
                authorization_source=source,
                project_authorizer=gate,
            ),
            PROJECT_WORK_CODE_READ_SCOPE,
            PROJECT_ID,
        ),
        (
            lambda source, gate: EosProjectWorkAssignmentService(
                session_factory=sessionmaker(),
                coordinator=object(),
                authorization_source=source,
                project_authorizer=gate,
            ),
            PROJECT_WORK_ASSIGNMENT_READ_SCOPE,
            PROJECT_ID,
        ),
    ],
)
def test_historical_read_and_non_project_paths_preserve_compatibility(
    service_factory, scope, project_id
) -> None:
    gate = ProjectGate()
    service = service_factory(EffectiveAuthorizationSource(scopes=[scope]), gate)

    service._authorize(
        tenant_id=TENANT,
        subject_id=SUBJECT,
        required_scope=scope,
        project_id=project_id,
    )

    assert gate.requests == []


def test_assignment_perform_scope_uses_exact_project_decision() -> None:
    gate = ProjectGate()
    service = EosProjectWorkAssignmentService(
        session_factory=sessionmaker(),
        coordinator=object(),
        authorization_source=EffectiveAuthorizationSource(
            scopes=[PROJECT_WORK_ASSIGNMENT_PERFORM_SCOPE]
        ),
        project_authorizer=gate,
    )

    service._authorize(
        tenant_id=TENANT,
        subject_id=SUBJECT,
        required_scope=PROJECT_WORK_ASSIGNMENT_PERFORM_SCOPE,
        project_id=PROJECT_ID,
    )

    assert gate.requests[0]["action"] == PROJECT_WORK_ASSIGNMENT_PERFORM_SCOPE


def test_scoped_approval_requires_a_decision_for_every_project() -> None:
    second_project = "44444444-4444-4444-8444-444444444444"
    gate = ProjectGate()
    service = EosScopedApprovalService(
        repository=object(),
        coordinator=object(),
        authorization_source=EffectiveAuthorizationSource(
            scopes=[ACCOUNTING_APPROVAL_REQUEST_SCOPE]
        ),
        wc_client=object(),
        project_authorizer=gate,
    )

    evidence = service._authorize(
        tenant_id=TENANT,
        subject_id=SUBJECT,
        company_id="55555555-5555-4555-8555-555555555555",
        project_ids=(PROJECT_ID, second_project),
        correlation_id=CORRELATION,
    )

    assert evidence["revision_hash"] == HASH_B
    assert [item["project_id"] for item in gate.requests] == [
        PROJECT_ID,
        second_project,
    ]
    assert all(
        item["action"] == ACCOUNTING_APPROVAL_REQUEST_SCOPE
        for item in gate.requests
    )


def test_scoped_approval_maps_project_denial_and_allows_company_scope() -> None:
    denied = EosProjectAuthorizationError(
        "EOS_PROJECT_AUTHORIZATION_UNAVAILABLE",
        "unavailable",
        status_code=503,
        retryable=True,
    )
    gate = ProjectGate(error=denied)
    service = EosScopedApprovalService(
        repository=object(),
        coordinator=object(),
        authorization_source=EffectiveAuthorizationSource(
            scopes=[ACCOUNTING_APPROVAL_REQUEST_SCOPE]
        ),
        wc_client=object(),
        project_authorizer=gate,
    )
    kwargs = {
        "tenant_id": TENANT,
        "subject_id": SUBJECT,
        "company_id": "55555555-5555-4555-8555-555555555555",
        "correlation_id": CORRELATION,
    }

    with pytest.raises(EosScopedApprovalError) as caught:
        service._authorize(project_ids=(PROJECT_ID,), **kwargs)
    assert caught.value.status_code == 503
    assert caught.value.retryable is True

    gate.error = None
    gate.requests.clear()
    service._authorize(project_ids=(), **kwargs)
    assert gate.requests == []


@pytest.mark.skipif(
    not POSTGRES_SMOKE,
    reason="Protected W40-CA01-S05 EOS/OA PostgreSQL smoke is disabled",
)
def test_actual_postgres_pending_allow_revoke_and_zero_residue() -> None:
    eos_schema = f"mybee_w40ca01s05_eos_{uuid.uuid4().hex}"
    oa_schema = f"mybee_w40ca01s05_oa_{uuid.uuid4().hex}"
    eos_psycopg = psycopg_database_url(EOS_DATABASE_URL)
    oa_psycopg = psycopg_database_url(OA_DATABASE_URL)
    for url, expected, schema_name in (
        (eos_psycopg, ("nex_eos_test", "nex_eos_user"), eos_schema),
        (oa_psycopg, ("nex_oa_test", "nex_oa_user"), oa_schema),
    ):
        with psycopg.connect(
            url, autocommit=True
        ) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            assert cursor.fetchone() == expected
            cursor.execute(f'CREATE SCHEMA "{schema_name}"')
    eos_url = (
        make_url(EOS_DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={eos_schema}"})
        .render_as_string(hide_password=False)
    )
    oa_url = (
        make_url(OA_DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={oa_schema}"})
        .render_as_string(hide_password=False)
    )
    try:
        assert (
            "2538_eos_project_authorization_sync"
            in run_service_migrations(
                "nex-eos", database_url=eos_url, profile="test"
            ).applied
        )
        assert (
            "2518_oa_project_grant"
            in run_service_migrations(
                "nex-oa", database_url=oa_url, profile="test"
            ).applied
        )
        eos_engine = create_engine(eos_url, pool_pre_ping=True)
        oa_engine = create_engine(oa_url, pool_pre_ping=True)
        eos_sessions = sessionmaker(bind=eos_engine, expire_on_commit=False)
        oa_sessions = sessionmaker(bind=oa_engine, expire_on_commit=False)
        with oa_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO oa_tenants (tenant_id, display_name) "
                    "VALUES (:tenant_id, 'W40 S05')"
                ),
                {"tenant_id": TENANT},
            )
        with eos_engine.begin() as connection:
            connection.execute(
                EOS_NVT_PROJECT_TABLE.insert().values(
                    tenant_id=TENANT,
                    nvt_project_id=NVT_PROJECT_ID,
                    nvt_project_code="NVT-W40-S05",
                    name="W40 S05 NVT",
                    status="ACTIVE",
                    version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            connection.execute(
                EOS_PROJECT_TABLE.insert().values(
                    tenant_id=TENANT,
                    project_id=PROJECT_ID,
                    project_code=PROJECT_CODE,
                    project_request_code="VO00R260001",
                    purpose_type="D",
                    origin="APPROVED_APPLICATION",
                    approval_evidence_ref="wc-approval:w40-s05",
                    approval_evidence_hash=HASH_A,
                    project_owner_subject_id=SUBJECT,
                    project_manager_subject_id=SUBJECT,
                    agent_sync_state="IN_SYNC",
                    authorization_sync_state="PENDING",
                    authorization_version=1,
                    name="W40 S05 Project",
                    nvt_project_id=NVT_PROJECT_ID,
                    parent_project_id=None,
                    hierarchy_depth=1,
                    status="ACTIVE",
                    start_date=date(2026, 1, 1),
                    end_date=None,
                    currency="KRW",
                    version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        grants = SqlAlchemyOaProjectGrantRepository(oa_sessions)
        grants.apply_grant(
            {
                "tenant_id": TENANT,
                "project_code": PROJECT_CODE,
                "subject_id": SUBJECT,
                "project_role": "OWNER",
                "grant_status": "ACTIVE",
                "project_status": "ACTIVE",
                "source_project_id": PROJECT_ID,
                "source_version": 1,
                "source_event_id": "66666666-6666-4666-8666-666666666666",
                "source_event_hash": HASH_A,
                "occurred_at": NOW,
            }
        )
        oa_decisions = OaProjectAuthorizationDecisionService(
            grants,
            EffectiveAuthorizationSource(scopes=[ACTION]),
            clock=lambda: NOW,
        )

        class DirectDecisionSource:
            @staticmethod
            def decide(payload):
                return oa_decisions.decide(payload)

        gate = EosProjectAuthorizationGate(
            context_source=SqlAlchemyEosProjectAuthorizationContextSource(
                eos_sessions
            ),
            decision_source=DirectDecisionSource(),
        )
        with pytest.raises(EosProjectAuthorizationError) as pending:
            _authorize(gate)
        assert pending.value.reason_code == "PROJECT_AUTHORIZATION_NOT_SYNCHRONIZED"

        with eos_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE eos_project SET authorization_sync_state = 'IN_SYNC' "
                    "WHERE tenant_id = :tenant_id AND project_id = :project_id"
                ),
                {"tenant_id": TENANT, "project_id": PROJECT_ID},
            )
        assert _authorize(gate).project_role == "OWNER"

        grants.apply_grant(
            {
                "tenant_id": TENANT,
                "project_code": PROJECT_CODE,
                "subject_id": SUBJECT,
                "project_role": "OWNER",
                "grant_status": "REVOKED",
                "project_status": "ACTIVE",
                "source_project_id": PROJECT_ID,
                "source_version": 2,
                "source_event_id": "77777777-7777-4777-8777-777777777777",
                "source_event_hash": HASH_B,
                "occurred_at": NOW,
            }
        )
        with eos_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE eos_project SET authorization_version = 2 "
                    "WHERE tenant_id = :tenant_id AND project_id = :project_id"
                ),
                {"tenant_id": TENANT, "project_id": PROJECT_ID},
            )
        with pytest.raises(EosProjectAuthorizationError) as revoked:
            _authorize(gate)
        assert revoked.value.reason_code == "PROJECT_GRANT_REVOKED"
        with eos_engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM eos_voucher_candidate "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": TENANT},
            ).scalar_one() == 0
        eos_engine.dispose()
        oa_engine.dispose()
    finally:
        for url, schema_name in (
            (eos_psycopg, eos_schema),
            (oa_psycopg, oa_schema),
        ):
            with psycopg.connect(
                url, autocommit=True
            ) as connection, connection.cursor() as cursor:
                cursor.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
                cursor.execute("SELECT to_regnamespace(%s)", (schema_name,))
                assert cursor.fetchone() == (None,)
