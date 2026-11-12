from __future__ import annotations

import os
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
    EOS_METADATA,
    EOS_OUTBOX_TABLE,
    EOS_PROJECT_APP_APPROVAL_TABLE,
    EOS_PROJECT_APP_DECISION_TABLE,
    EOS_PROJECT_APP_REVISION_TABLE,
    EOS_PROJECT_APPLICATION_TABLE,
    EOS_PROJECT_MEMBER_TABLE,
    EOS_PROJECT_TABLE,
    ApprovalPolicyInput,
    ApprovalPolicyStageInput,
    EosGovernedProjectError,
    EosGovernedProjectService,
    EosProjectApplicationApprovalError,
    EosProjectApplicationApprovalService,
    EosServiceCaller,
    NvtProjectInput,
    ProjectApplicationDraft,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosProjectApplicationRepository,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
    create_eos_app,
    is_project_application_approval_delivery,
)
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 11, 12, 5, 0, tzinfo=UTC)
TENANT = "VO00"
APPLICANT = "employee-1004"
TEAM_LEAD = "approver-team-lead"
CEO = "approver-ceo"
NVT_ID = "b4000000-0000-4000-8000-000000000001"
APPLICATION_ID = "b4000000-0000-4000-8000-000000000002"
POLICY_ID = "b4000000-0000-4000-8000-000000000003"
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_W30_S00B_POSTGRES_SMOKE") == "1"
PROJECT_AGENT_POLICY_REF = "policy://nex-platform/project-agent-lifecycle/v1"


class AuthorizationSource:
    def __init__(self) -> None:
        self.active = True
        self.unavailable = False
        self.roles = {TEAM_LEAD: ["TEAM_LEAD"], CEO: ["CEO"]}

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.unavailable:
            raise RuntimeError("OA unavailable")
        scopes = (
            [
                "project:application:create",
                "project:application:submit",
                "project:application:request-approval",
                "approval:decide",
            ]
            if subject_id == APPLICANT
            else ["approval:decide"]
        )
        return {
            "active": self.active,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": scopes,
            "roles": self.roles.get(subject_id, ["EMPLOYEE"]),
            "revision_hash": "sha256:" + "a" * 64,
            "decision_ref": f"oa-authz:{subject_id}",
        }


class WcClient:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.unavailable = False

    def create_or_get(self, value):
        if self.unavailable:
            raise RuntimeError("WC unavailable")
        item = dict(value)
        existing = self.items.setdefault(item["approval_work_item_id"], item)
        return {"work_item": dict(existing), "created": existing is item}


@pytest.fixture
def runtime():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    projects = SqlAlchemyEosProjectRepository(sessions)
    projects.create_nvt_project(
        NvtProjectInput(TENANT, NVT_ID, "NVT-W30", "W30 Portfolio")
    )
    SqlAlchemyEosApprovalPolicyRepository(sessions).create_policy(
        ApprovalPolicyInput(
            tenant_id=TENANT,
            approval_policy_id=POLICY_ID,
            policy_key="mybee.project-application.committee",
            name="MyBee Project Committee",
            approval_domain="BUSINESS_FORMAL",
            effective_from=NOW - timedelta(days=1),
            transaction_type="PROJECT_APPLICATION",
            stages=(
                ApprovalPolicyStageInput("TEAM_LEAD"),
                ApprovalPolicyStageInput("CEO"),
            ),
        )
    )
    applications = SqlAlchemyEosProjectApplicationRepository(sessions)
    created = applications.create_draft(
        ProjectApplicationDraft(
            tenant_id=TENANT,
            application_id=APPLICATION_ID,
            purpose_type="D",
            applicant_subject_id=APPLICANT,
            name="Project Committee Runtime",
            nvt_project_id=NVT_ID,
            currency="KRW",
        ),
        issued_at=NOW,
    )
    submitted = applications.submit(
        tenant_id=TENANT,
        project_request_code=created["project_request_code"],
        expected_version=1,
        actor_subject_id=APPLICANT,
    )
    auth = AuthorizationSource()
    wc = WcClient()
    service = EosProjectApplicationApprovalService(
        session_factory=sessions,
        authorization_source=auth,
        wc_client=wc,
        project_agent_profile_policy_ref=PROJECT_AGENT_POLICY_REF,
        clock=lambda: NOW,
    )
    yield sessions, submitted, auth, wc, service
    engine.dispose()


def _request(service, application):
    return service.request_approval(
        tenant_id=TENANT,
        project_request_code=application["project_request_code"],
        approval_policy_id=POLICY_ID,
        expected_version=application["version"],
        requester_subject_id=APPLICANT,
    )


def _delivery(item, *, principal: str, decision: str, suffix: str):
    terminal = {
        **item,
        "state": "APPROVED" if decision == "APPROVE" else "REJECTED",
        "version": item["version"] + 1,
    }
    decided_at = (NOW + timedelta(minutes=int(suffix))).isoformat()
    namespace = uuid.UUID(APPLICATION_ID)
    decision_id = str(uuid.uuid5(namespace, f"decision-{suffix}"))
    return {
        "schema_version": "wc_approval_delivery.v1",
        "outbox_id": str(uuid.uuid5(namespace, f"outbox-{suffix}")),
        "work_item": terminal,
        "decision": {
            "schema_version": "wc_approval_decision.v1",
            "tenant_id": TENANT,
            "decision_id": decision_id,
            "approval_work_item_id": item["approval_work_item_id"],
            "decision": decision,
            "decided_by": principal,
            "decision_comment": "committee decision",
            "decision_version": 1,
            "authorized_by_oa": True,
            "oa_decision_ref": "oa-wc:project-committee",
            "authorization_revision_hash": "sha256:" + "b" * 64,
            "authorization_checked_at": decided_at,
            "decided_at": decided_at,
        },
        "event": {
            "schema_version": "wc_approval_event.v1",
            "tenant_id": TENANT,
            "event_id": str(uuid.uuid5(namespace, f"event-{suffix}")),
            "event_type": "BUSINESS_FORMAL_APPROVAL_DECIDED",
            "approval_work_item_id": item["approval_work_item_id"],
            "decision_id": decision_id,
            "approval_domain": "BUSINESS_FORMAL",
            "decision": decision,
            "decided_by": principal,
            "oa_decision_ref": "oa-wc:project-committee",
            "occurred_at": decided_at,
            "correlation_id": f"project-committee-correlation-{suffix}",
            "causation_id": f"project-committee-causation-{suffix}",
        },
    }


def _replace(payload: dict, path: str, value) -> dict:
    changed = deepcopy(payload)
    target = changed
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    return changed


def test_two_stage_committee_finalizes_one_project_and_exact_replay(runtime) -> None:
    sessions, application, _auth, _wc, service = runtime
    requested = _request(service, application)
    assert requested["approval_state"] == "PENDING"
    assert requested["active_stage_order"] == 1
    first_item = requested["wc_publication"]["work_item"]
    assert is_project_application_approval_delivery(
        _delivery(first_item, principal=TEAM_LEAD, decision="APPROVE", suffix="1")
    )

    first = service.ingest_wc_delivery(
        _delivery(first_item, principal=TEAM_LEAD, decision="APPROVE", suffix="1")
    )
    assert first["approval_state"] == "PENDING"
    assert first["active_stage_order"] == 2
    second_item = first["wc_publication"]["work_item"]
    assert second_item["target_role_ref"] == "CEO"

    final_delivery = _delivery(
        second_item, principal=CEO, decision="APPROVE", suffix="2"
    )
    final = service.ingest_wc_delivery(final_delivery)
    replay = service.ingest_wc_delivery(final_delivery)
    assert final["application_state"] == "APPROVED"
    assert final["approval_state"] == "APPROVED"
    assert final["approved_project_code"] == "VO00D260001"
    assert replay == {**final, "created": False}

    with sessions() as session:
        project = session.execute(select(EOS_PROJECT_TABLE)).mappings().one()
        membership = session.execute(select(EOS_PROJECT_MEMBER_TABLE)).mappings().one()
        assert project["project_code"] == "VO00D260001"
        assert project["project_request_code"] == application["project_request_code"]
        assert project["origin"] == "APPROVED_APPLICATION"
        assert project["agent_sync_state"] == "PENDING"
        lifecycle = (
            session.execute(
                select(EOS_OUTBOX_TABLE).where(
                    EOS_OUTBOX_TABLE.c.event_type == "PROJECT_LIFECYCLE_CHANGED"
                )
            )
            .mappings()
            .one()
        )
        assert lifecycle["delivery_state"] == "PENDING"
        assert lifecycle["event_payload"]["profile_policy_ref"] == (
            PROJECT_AGENT_POLICY_REF
        )
        assert membership["subject_id"] == APPLICANT
        assert membership["member_role"] == "OWNER"
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_PROJECT_APP_DECISION_TABLE)
            )
            == 2
        )


def test_committee_rejection_retains_application_without_project(runtime) -> None:
    sessions, application, _auth, _wc, service = runtime
    item = _request(service, application)["wc_publication"]["work_item"]
    rejected = service.ingest_wc_delivery(
        _delivery(item, principal=TEAM_LEAD, decision="REJECT", suffix="3")
    )
    assert rejected["application_state"] == "REJECTED"
    assert rejected["approval_state"] == "REJECTED"
    assert rejected["approved_project_code"] is None
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(EOS_PROJECT_TABLE)) == 0
        assert (
            session.scalar(select(func.count()).select_from(EOS_PROJECT_MEMBER_TABLE))
            == 0
        )


def test_request_and_delivery_fail_closed_on_drift_and_sod(runtime) -> None:
    _sessions, application, auth, _wc, service = runtime
    requested = _request(service, application)
    replay = _request(service, application)
    assert replay["created"] is False
    with pytest.raises(EosProjectApplicationApprovalError, match="version"):
        service.request_approval(
            tenant_id=TENANT,
            project_request_code=application["project_request_code"],
            approval_policy_id=POLICY_ID,
            expected_version=application["version"] + 1,
            requester_subject_id=APPLICANT,
        )

    item = requested["wc_publication"]["work_item"]
    auth.roles[APPLICANT] = ["TEAM_LEAD"]
    with pytest.raises(EosProjectApplicationApprovalError, match="applicant"):
        service.ingest_wc_delivery(
            _delivery(item, principal=APPLICANT, decision="APPROVE", suffix="4")
        )
    with pytest.raises(EosProjectApplicationApprovalError, match="role"):
        service.ingest_wc_delivery(
            _delivery(item, principal=CEO, decision="APPROVE", suffix="5")
        )


@pytest.mark.parametrize(
    ("mode", "detail"),
    (
        ("missing_application", "not found"),
        ("different_applicant", "applicant"),
        ("draft_application", "SUBMITTED"),
        ("replay_policy_drift", "immutable semantics"),
        ("missing_policy", "policy was not found"),
        ("wrong_policy_type", "unscoped PROJECT_APPLICATION"),
        ("inactive_policy", "not effective"),
        ("missing_stages", "stages are incomplete"),
        ("invalid_quorum", "requester-excluded"),
    ),
)
def test_request_boundary_rejects_missing_drifted_or_ineligible_state(
    runtime, mode: str, detail: str
) -> None:
    sessions, application, _auth, _wc, service = runtime
    request_code = application["project_request_code"]
    policy_id = POLICY_ID

    if mode == "missing_application":
        request_code = "VO00R269999"
    elif mode == "different_applicant":
        with sessions.begin() as session:
            session.execute(
                update(EOS_PROJECT_APPLICATION_TABLE)
                .where(EOS_PROJECT_APPLICATION_TABLE.c.application_id == APPLICATION_ID)
                .values(applicant_subject_id=TEAM_LEAD)
            )
    elif mode == "draft_application":
        with sessions.begin() as session:
            session.execute(
                update(EOS_PROJECT_APPLICATION_TABLE)
                .where(EOS_PROJECT_APPLICATION_TABLE.c.application_id == APPLICATION_ID)
                .values(state="DRAFT")
            )
    elif mode == "replay_policy_drift":
        _request(service, application)
        policy_id = "b4000000-0000-4000-8000-000000000099"
    elif mode == "missing_policy":
        policy_id = "b4000000-0000-4000-8000-000000000099"
    elif mode == "wrong_policy_type":
        with sessions.begin() as session:
            session.execute(
                update(EOS_APPROVAL_POLICY_TABLE)
                .where(EOS_APPROVAL_POLICY_TABLE.c.approval_policy_id == POLICY_ID)
                .values(transaction_type="VOUCHER")
            )
    elif mode == "inactive_policy":
        with sessions.begin() as session:
            session.execute(
                update(EOS_APPROVAL_POLICY_TABLE)
                .where(EOS_APPROVAL_POLICY_TABLE.c.approval_policy_id == POLICY_ID)
                .values(status="INACTIVE")
            )
    elif mode == "missing_stages":
        with sessions.begin() as session:
            session.execute(
                delete(EOS_APPROVAL_POLICY_STAGE_TABLE).where(
                    EOS_APPROVAL_POLICY_STAGE_TABLE.c.approval_policy_id == POLICY_ID
                )
            )
    elif mode == "invalid_quorum":
        with sessions.begin() as session:
            session.execute(
                update(EOS_APPROVAL_POLICY_STAGE_TABLE)
                .where(
                    EOS_APPROVAL_POLICY_STAGE_TABLE.c.approval_policy_id == POLICY_ID,
                    EOS_APPROVAL_POLICY_STAGE_TABLE.c.stage_order == 1,
                )
                .values(quorum_count=2)
            )

    with pytest.raises(EosProjectApplicationApprovalError, match=detail):
        service.request_approval(
            tenant_id=TENANT,
            project_request_code=request_code,
            approval_policy_id=policy_id,
            expected_version=application["version"],
            requester_subject_id=APPLICANT,
        )


@pytest.mark.parametrize(
    ("mode", "detail"),
    (
        ("unavailable", "unavailable"),
        ("inactive", "denied"),
        ("malformed", "malformed"),
        ("missing_revision", "revision"),
        ("bad_revision", "revision"),
    ),
)
def test_request_fails_closed_on_oa_authorization_anomalies(
    runtime, monkeypatch, mode: str, detail: str
) -> None:
    _sessions, application, auth, _wc, service = runtime
    if mode == "unavailable":
        auth.unavailable = True
    elif mode == "inactive":
        auth.active = False
    elif mode == "malformed":
        monkeypatch.setattr(auth, "effective_authorization", lambda **_kwargs: [])
    elif mode in {"missing_revision", "bad_revision"}:
        original = auth.effective_authorization

        def invalid_revision(**kwargs):
            revision = None if mode == "missing_revision" else "not-a-hash"
            return {**original(**kwargs), "revision_hash": revision}

        monkeypatch.setattr(auth, "effective_authorization", invalid_revision)

    with pytest.raises(EosProjectApplicationApprovalError, match=detail):
        _request(service, application)


@pytest.mark.parametrize(
    ("path", "value", "detail"),
    (
        ("schema_version", "wc_approval_delivery.v0", "schema"),
        ("work_item.resume_target_ref", "eos.other:target", "does not target"),
        ("work_item.tenant_id", "NOPE", "lineage differs"),
        ("decision.decision", "DEFER", "decision is invalid"),
        ("work_item.state", "PENDING", "terminal state differs"),
        ("decision.schema_version", "wc_approval_decision.v0", "schema"),
        ("event.schema_version", "wc_approval_event.v0", "schema"),
        ("decision.authorized_by_oa", False, "lacks OA authorization"),
        ("event.decided_by", CEO, "principal differs"),
        ("human_principal", "agent:project-approver", "Human principal"),
        ("decision.decision_version", 2, "version is unsupported"),
        ("event.occurred_at", NOW.isoformat(), "timestamps differ"),
        ("decision.authorization_revision_hash", "bad", "sha256"),
    ),
)
def test_wc_delivery_contract_rejects_malformed_or_drifted_payloads(
    runtime, path: str, value, detail: str
) -> None:
    _sessions, application, _auth, _wc, service = runtime
    item = _request(service, application)["wc_publication"]["work_item"]
    delivery = _delivery(item, principal=TEAM_LEAD, decision="APPROVE", suffix="8")
    if path == "decision.decision":
        delivery["event"]["decision"] = value
    elif path == "human_principal":
        delivery["decision"]["decided_by"] = value
        delivery["event"]["decided_by"] = value
        path = "decision.decided_by"
    changed = _replace(delivery, path, value)
    with pytest.raises(EosProjectApplicationApprovalError, match=detail):
        service.ingest_wc_delivery(changed)


@pytest.mark.parametrize(
    ("mode", "detail"),
    (
        ("stage", "out of order"),
        ("semantic_hash", "semantic_hash differs"),
        ("version", "version is out of order"),
    ),
)
def test_wc_delivery_boundary_rejects_stale_or_drifted_work_item(
    runtime, mode: str, detail: str
) -> None:
    _sessions, application, _auth, _wc, service = runtime
    item = _request(service, application)["wc_publication"]["work_item"]
    delivery = _delivery(item, principal=TEAM_LEAD, decision="APPROVE", suffix="9")
    if mode == "stage":
        delivery["work_item"]["resume_target_ref"] = delivery["work_item"][
            "resume_target_ref"
        ].replace(":stage:1", ":stage:2")
    elif mode == "semantic_hash":
        delivery["work_item"]["semantic_hash"] = "sha256:" + "f" * 64
    elif mode == "version":
        delivery["work_item"]["version"] += 1

    with pytest.raises(EosProjectApplicationApprovalError, match=detail):
        service.ingest_wc_delivery(delivery)


def test_missing_current_revision_is_rejected_before_approval(runtime) -> None:
    sessions, application, _auth, _wc, service = runtime
    with sessions.begin() as session:
        session.execute(
            delete(EOS_PROJECT_APP_REVISION_TABLE).where(
                EOS_PROJECT_APP_REVISION_TABLE.c.application_id == APPLICATION_ID
            )
        )
    with pytest.raises(EosProjectApplicationApprovalError, match="revision"):
        _request(service, application)


def test_changed_decision_replay_and_terminal_redelivery_fail_closed(runtime) -> None:
    _sessions, application, _auth, _wc, service = runtime
    item = _request(service, application)["wc_publication"]["work_item"]
    rejected = _delivery(item, principal=TEAM_LEAD, decision="REJECT", suffix="10")
    service.ingest_wc_delivery(rejected)

    changed_replay = _replace(
        rejected, "decision.decision_comment", "changed immutable decision"
    )
    with pytest.raises(EosProjectApplicationApprovalError, match="immutable semantics"):
        service.ingest_wc_delivery(changed_replay)

    later = _delivery(item, principal=TEAM_LEAD, decision="REJECT", suffix="11")
    later_work_item_id = "b4000000-0000-4000-8000-000000000011"
    later["work_item"]["approval_work_item_id"] = later_work_item_id
    later["decision"]["approval_work_item_id"] = later_work_item_id
    later["event"]["approval_work_item_id"] = later_work_item_id
    with pytest.raises(EosProjectApplicationApprovalError, match="terminal"):
        service.ingest_wc_delivery(later)


@pytest.mark.parametrize("mode", ("malformed", "lineage"))
def test_wc_publication_response_fails_closed(runtime, monkeypatch, mode: str) -> None:
    _sessions, application, _auth, wc, service = runtime

    def invalid_publication(value):
        if mode == "malformed":
            return {}
        return {"work_item": {**value, "semantic_hash": "sha256:" + "f" * 64}}

    monkeypatch.setattr(wc, "create_or_get", invalid_publication)
    with pytest.raises(EosProjectApplicationApprovalError, match="publication"):
        _request(service, application)


def test_wc_unavailability_is_retryable_without_losing_approval(runtime) -> None:
    sessions, application, _auth, wc, service = runtime
    wc.unavailable = True
    with pytest.raises(EosProjectApplicationApprovalError) as unavailable:
        _request(service, application)
    assert unavailable.value.retryable is True
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_PROJECT_APP_APPROVAL_TABLE)
            )
            == 1
        )
    wc.unavailable = False
    assert _request(service, application)["created"] is False


def test_installed_runtime_retires_direct_project_creation(runtime) -> None:
    sessions, _application, auth, _wc, _service = runtime
    governed = EosGovernedProjectService(
        session_factory=sessions,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(sessions),
        authorization_source=auth,
        allow_legacy_project_create=False,
    )
    with pytest.raises(EosGovernedProjectError) as retired:
        governed.create_project(
            {},
            caller=EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",)),
        )
    assert retired.value.error_code == "EOS_PROJECT_DIRECT_CREATE_RETIRED"
    assert retired.value.status_code == 410


def test_signed_api_requests_approval_and_routes_wc_delivery(runtime) -> None:
    _sessions, application, _auth, _wc, service = runtime
    app = create_eos_app(environ={})
    app.state.eos_project_application_approval_service = service
    client = TestClient(app)
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "X-NeX-Tenant-Id": TENANT,
        "X-NeX-Subject-Id": APPLICANT,
    }
    requested = client.post(
        f"/internal/v2/project-applications/{application['project_request_code']}"
        ":request-approval",
        headers=headers,
        json={
            "approval_policy_id": POLICY_ID,
            "expected_version": application["version"],
        },
    )
    assert requested.status_code == 200
    item = requested.json()["wc_publication"]["work_item"]
    delivered = client.post(
        "/internal/v1/approval-decision-events",
        headers={"Authorization": f"Bearer {token.access_token}"},
        json=_delivery(
            item,
            principal=TEAM_LEAD,
            decision="APPROVE",
            suffix="6",
        ),
    )
    assert delivered.status_code == 200
    assert delivered.json()["active_stage_order"] == 2

    invalid = client.post(
        f"/internal/v2/project-applications/{application['project_request_code']}"
        ":request-approval",
        headers=headers,
        json={"approval_policy_id": POLICY_ID, "expected_version": "bad"},
    )
    assert invalid.status_code == 422

    app.state.eos_project_application_approval_service = None
    unavailable = client.post(
        f"/internal/v2/project-applications/{application['project_request_code']}"
        ":request-approval",
        headers=headers,
        json={
            "approval_policy_id": POLICY_ID,
            "expected_version": application["version"],
        },
    )
    assert unavailable.status_code == 503


def test_project_approval_migration_and_operation_contract_are_admitted() -> None:
    migration = Path(
        "database/nex-eos/migrations/2532_eos_project_application_approval.sql"
    )
    sql = migration.read_text(encoding="utf-8")
    assert "eos_project_app_approval" in sql
    assert "eos_project_app_decision" in sql
    assert "eos_guard_project_app_decision_immutable" in sql
    assert is_project_application_approval_delivery({}) is False


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W30-S00B EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_project_committee_finalization_and_zero_residue() -> None:
    schema_name = f"mybee_w30s00b_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_eos_test", "nex_eos_user")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    try:
        migrated = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2532_eos_project_application_approval" in migrated.applied
        database = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        projects = SqlAlchemyEosProjectRepository(database.session_factory)
        projects.create_nvt_project(
            NvtProjectInput(TENANT, NVT_ID, "NVT-W30-PG", "W30 PG Portfolio")
        )
        SqlAlchemyEosApprovalPolicyRepository(database.session_factory).create_policy(
            ApprovalPolicyInput(
                tenant_id=TENANT,
                approval_policy_id=POLICY_ID,
                policy_key="mybee.project-application.postgres",
                name="MyBee Project Committee PostgreSQL",
                approval_domain="BUSINESS_FORMAL",
                effective_from=NOW - timedelta(days=1),
                transaction_type="PROJECT_APPLICATION",
                stages=(ApprovalPolicyStageInput("TEAM_LEAD"),),
            )
        )
        applications = SqlAlchemyEosProjectApplicationRepository(
            database.session_factory
        )
        created = applications.create_draft(
            ProjectApplicationDraft(
                tenant_id=TENANT,
                application_id=APPLICATION_ID,
                purpose_type="D",
                applicant_subject_id=APPLICANT,
                name="PostgreSQL Project Committee",
                nvt_project_id=NVT_ID,
            ),
            issued_at=NOW,
        )
        submitted = applications.submit(
            tenant_id=TENANT,
            project_request_code=created["project_request_code"],
            expected_version=1,
            actor_subject_id=APPLICANT,
        )
        service = EosProjectApplicationApprovalService(
            session_factory=database.session_factory,
            authorization_source=AuthorizationSource(),
            wc_client=WcClient(),
            project_agent_profile_policy_ref=PROJECT_AGENT_POLICY_REF,
            clock=lambda: NOW,
        )
        item = service.request_approval(
            tenant_id=TENANT,
            project_request_code=submitted["project_request_code"],
            approval_policy_id=POLICY_ID,
            expected_version=submitted["version"],
            requester_subject_id=APPLICANT,
        )["wc_publication"]["work_item"]
        delivery = _delivery(item, principal=TEAM_LEAD, decision="APPROVE", suffix="7")
        receipt = service.ingest_wc_delivery(delivery)
        replay = service.ingest_wc_delivery(delivery)
        assert receipt["approved_project_code"] == "VO00D260001"
        assert replay["created"] is False
        with database.session_factory() as session:
            assert (
                session.scalar(select(func.count()).select_from(EOS_PROJECT_TABLE)) == 1
            )
            assert (
                session.scalar(
                    select(func.count()).select_from(EOS_PROJECT_APP_DECISION_TABLE)
                )
                == 1
            )
        database.engine.dispose()
    finally:
        with (
            psycopg.connect(psycopg_url, autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            cursor.execute("SELECT to_regnamespace(%s)", (schema_name,))
            assert cursor.fetchone() == (None,)
