from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from nex_eos import (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_PROOF_TABLE,
    EOS_APPROVAL_STAGE_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_METADATA,
    ApprovalInstanceInput,
    ApprovalPolicyInput,
    ApprovalPolicyStageInput,
    ApprovalStageDecisionInput,
    EosApprovalInstanceError,
    EosApprovalTransitionError,
    EosBusinessApprovalTransitionService,
    NvtProjectInput,
    OrgUnitInput,
    ProjectInput,
    SqlAlchemyEosApprovalInstanceRepository,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosApprovalTransitionRepository,
    SqlAlchemyEosOrganizationRepository,
    SqlAlchemyEosProjectRepository,
    approval_transitions,
    deterministic_business_formal_work_item_id,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import load_migrations
from sqlalchemy import create_engine, func, select
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)
TENANT = "tenant-p8-s73"
INSTANCE_ID = "75000000-0000-4000-8000-000000000001"
POLICY_ID = "75000000-0000-4000-8000-000000000002"
OPERATION_ID = "75000000-0000-4000-8000-000000000003"
ORG_ID = "75000000-0000-4000-8000-000000000004"
NVT_ID = "75000000-0000-4000-8000-000000000005"
PROJECT_ID = "75000000-0000-4000-8000-000000000006"
PAYLOAD_HASH = semantic_sha256_hash_ref({"amount": "2500.00"})
INTENT_HASH = semantic_sha256_hash_ref({"write": "voucher-draft-p8-s73"})


def _runtime(*, positions=("TEAM_LEAD", "GROUP_LEAD"), clock=None):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    SqlAlchemyEosOrganizationRepository(sessions).create_org_unit(
        OrgUnitInput(
            TENANT,
            ORG_ID,
            "P8-S73-FINANCE",
            "P8 S73 Finance",
            "TEAM",
            NOW - timedelta(days=1),
        )
    )
    projects = SqlAlchemyEosProjectRepository(sessions)
    projects.create_nvt_project(
        NvtProjectInput(TENANT, NVT_ID, "P8-S73-NVT", "P8 S73 NVT")
    )
    projects.create_project(
        ProjectInput(
            TENANT,
            PROJECT_ID,
            "P8-S73-PROJECT",
            "P8 S73 Project",
            nvt_project_id=NVT_ID,
        )
    )
    SqlAlchemyEosApprovalPolicyRepository(sessions).create_policy(
        ApprovalPolicyInput(
            tenant_id=TENANT,
            approval_policy_id=POLICY_ID,
            policy_key="finance.voucher.p8-s73",
            name="P8 S73 policy",
            approval_domain="BUSINESS_FORMAL",
            effective_from=NOW - timedelta(days=1),
            stages=tuple(ApprovalPolicyStageInput(item) for item in positions),
        )
    )
    with sessions.begin() as session:
        session.execute(
            EOS_BUSINESS_OPERATION_TABLE.insert().values(
                tenant_id=TENANT,
                business_operation_id=OPERATION_ID,
                idempotency_key="p8-s73-operation",
                operation="CREATE_VOUCHER_DRAFT",
                payload_hash=PAYLOAD_HASH,
                commit_state="COMMITTED",
                result_json={"voucher_id": "voucher-p8-s73"},
                created_at=NOW - timedelta(minutes=1),
                committed_at=NOW - timedelta(seconds=30),
            )
        )
    instances = SqlAlchemyEosApprovalInstanceRepository(sessions, clock=lambda: NOW)
    instance, created = instances.create_or_get_instance(
        ApprovalInstanceInput(
            tenant_id=TENANT,
            approval_instance_id=INSTANCE_ID,
            idempotency_key="p8-s73-instance",
            approval_policy_id=POLICY_ID,
            business_operation_id=OPERATION_ID,
            protected_operation_ref="eos:business-operation:p8-s73",
            payload_hash=PAYLOAD_HASH,
            write_intent_hash=INTENT_HASH,
            requester_ref={"type": "oa.user", "id": "employee-requester"},
            org_unit_id=ORG_ID,
            project_id=PROJECT_ID,
            correlation_id="p8-s73-correlation",
            causation_id="p8-s73-causation",
            expires_at=NOW + timedelta(days=1),
        )
    )
    assert created is True
    transitions = SqlAlchemyEosApprovalTransitionRepository(
        sessions,
        clock=clock or (lambda: NOW + timedelta(minutes=2)),
    )
    service = EosBusinessApprovalTransitionService(
        approval_instances=instances,
        transitions=transitions,
    )
    return sessions, instances, transitions, service, instance


def _envelope(instance, stage, *, decision_value="APPROVE", suffix=1, **changes):
    decision_id = f"75000000-0000-4000-8001-{suffix:012d}"
    event_id = f"75000000-0000-4000-8002-{suffix:012d}"
    work_item_id = deterministic_business_formal_work_item_id(
        tenant_id=TENANT,
        approval_stage_id=stage["approval_stage_id"],
    )
    decided_at = NOW + timedelta(minutes=1)
    terminal_state = "APPROVED" if decision_value == "APPROVE" else "REJECTED"
    item = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": TENANT,
        "approval_work_item_id": work_item_id,
        "approval_domain": "BUSINESS_FORMAL",
        "source_ref": f"eos.approval-stage:{stage['approval_stage_id']}",
        "semantic_hash": semantic_sha256_hash_ref(
            {"stage": stage["approval_stage_id"], "suffix": suffix}
        ),
        "title": "Approve business operation: CREATE_VOUCHER_DRAFT",
        "display_safe_summary": "P8-S73 approval",
        "approval_provider_type": "EOS",
        "approval_target_ref": f"eos.approval-stage:{stage['approval_stage_id']}",
        "target_approver_ref": f"employee-approver-{stage['stage_order']}",
        "target_role_ref": stage["position_type"],
        "target_org_scope_ref": ORG_ID,
        "target_project_scope_ref": PROJECT_ID,
        "agent_execution_id": None,
        "executable_step_id": None,
        "nsl_execution_id": None,
        "business_operation_id": OPERATION_ID,
        "approval_request_id": None,
        "protected_request_ref": "eos:business-operation:p8-s73",
        "resume_target_ref": (
            f"eos.approval-instance:{INSTANCE_ID}:stage:{stage['stage_order']}"
        ),
        "state": terminal_state,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "version": 2,
    }
    decision_record = {
        "schema_version": "wc_approval_decision.v1",
        "tenant_id": TENANT,
        "decision_id": decision_id,
        "approval_work_item_id": work_item_id,
        "decision": decision_value,
        "decided_by": item["target_approver_ref"],
        "decision_comment": ("Approved" if decision_value == "APPROVE" else "Rejected"),
        "decision_version": 1,
        "authorized_by_oa": True,
        "oa_decision_ref": f"oa-authz:p8-s73-{suffix}",
        "authorization_revision_hash": semantic_sha256_hash_ref(
            {"oa-revision": suffix}
        ),
        "authorization_checked_at": decided_at.isoformat().replace("+00:00", "Z"),
        "decided_at": decided_at.isoformat().replace("+00:00", "Z"),
    }
    event = {
        "schema_version": "wc_approval_event.v1",
        "tenant_id": TENANT,
        "event_id": event_id,
        "event_type": "BUSINESS_FORMAL_APPROVAL_DECIDED",
        "approval_work_item_id": work_item_id,
        "decision_id": decision_id,
        "approval_domain": "BUSINESS_FORMAL",
        "decision": decision_value,
        "decided_by": decision_record["decided_by"],
        "oa_decision_ref": decision_record["oa_decision_ref"],
        "occurred_at": decision_record["decided_at"],
        "correlation_id": f"p8-s73-correlation-{suffix}",
        "causation_id": f"p8-s73-causation-{suffix}",
    }
    for target, values in changes.items():
        {"work_item": item, "decision": decision_record, "event": event}[target].update(
            values
        )
    return item, decision_record, event


def _advance(service, envelope):
    work_item, decision, event = envelope
    return service.advance_from_wc_decision(
        tenant_id=TENANT,
        approval_instance_id=INSTANCE_ID,
        work_item=work_item,
        decision=decision,
        event=event,
    )


def _direct_input(stage, **overrides):
    values = {
        "tenant_id": TENANT,
        "approval_instance_id": INSTANCE_ID,
        "approval_stage_id": stage["approval_stage_id"],
        "wc_approval_work_item_id": deterministic_business_formal_work_item_id(
            tenant_id=TENANT, approval_stage_id=stage["approval_stage_id"]
        ),
        "wc_work_item_semantic_hash": semantic_sha256_hash_ref({"direct": 1}),
        "wc_decision_id": "75000000-0000-4000-8003-000000000001",
        "wc_event_id": "75000000-0000-4000-8004-000000000001",
        "decision": "APPROVE",
        "decision_version": 1,
        "decided_by_ref": {"type": "oa.user", "id": "employee-approver-1"},
        "decision_comment": "Approved",
        "authorized_by_oa": True,
        "oa_decision_ref": "oa-authz:p8-s73-direct",
        "authorization_revision_hash": semantic_sha256_hash_ref({"oa": 1}),
        "authorization_checked_at": NOW + timedelta(minutes=1),
        "decided_at": NOW + timedelta(minutes=1),
        "correlation_id": "p8-s73-direct-correlation",
        "causation_id": "p8-s73-direct-causation",
    }
    values.update(overrides)
    return ApprovalStageDecisionInput(**values)


def test_s73_migration_adds_immutable_proof_and_cancelled_stage_support() -> None:
    proof_migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2511_eos_approval_proof"
    )
    decision_fk_migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2512_eos_approval_proof_decision_fk"
    )
    compact = " ".join(proof_migration.sql.lower().split())
    fk_compact = " ".join(decision_fk_migration.sql.lower().split())
    assert "create table if not exists eos_approval_proof" in compact
    assert "unique (tenant_id, approval_instance_id)" in compact
    assert "state in ('waiting', 'cancelled')" in compact
    assert "approval_domain = 'business_formal'" in compact
    assert "foreign key (tenant_id, final_wc_decision_id)" in fk_compact
    assert "eos_approval_decision (tenant_id, wc_decision_id)" in fk_compact
    identifiers = [
        line.split()[-1]
        for migration in (proof_migration, decision_fk_migration)
        for line in migration.sql.splitlines()
        if "constraint " in line.lower() or "index if not exists " in line.lower()
    ]
    assert identifiers
    assert all(len(identifier) <= 63 for identifier in identifiers)


def test_two_stage_approval_advances_then_emits_immutable_exact_bound_proof() -> None:
    sessions, instances, _transitions, service, instance = _runtime()
    first = _advance(service, _envelope(instance, instance["stages"][0], suffix=1))
    assert first["created"] is True
    assert first["outcome"] == "NEXT_STAGE_ACTIVE"
    assert first["instance"]["state"] == "PENDING"
    assert first["next_active_stage"]["stage_order"] == 2
    assert first["approval_proof"] is None

    current = instances.get_instance(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)
    final_envelope = _envelope(current, current["stages"][1], suffix=2)
    final = _advance(service, final_envelope)
    assert final["outcome"] == "FINAL_APPROVED"
    assert final["instance"]["state"] == "APPROVED"
    assert final["next_active_stage"] is None
    proof = final["approval_proof"]
    assert proof["approval_domain"] == "BUSINESS_FORMAL"
    assert proof["business_operation_id"] == OPERATION_ID
    assert proof["payload_hash"] == PAYLOAD_HASH
    assert proof["write_intent_hash"] == INTENT_HASH
    assert proof["proof_hash"].startswith("sha256:")
    assert proof["decision_chain_hash"].startswith("sha256:")
    assert proof["approval_proof_ref"].startswith("eos.approval-proof:")

    replay = _advance(service, final_envelope)
    assert replay["created"] is False
    assert replay["outcome"] == "REPLAY"
    assert replay["approval_proof"] == proof
    restarted = SqlAlchemyEosApprovalTransitionRepository(sessions)
    assert (
        restarted.get_final_proof(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)
        == proof
    )
    assert (
        restarted.get_final_proof(
            tenant_id="other-tenant", approval_instance_id=INSTANCE_ID
        )
        is None
    )
    with sessions() as session:
        assert (
            session.execute(
                select(func.count()).select_from(EOS_APPROVAL_PROOF_TABLE)
            ).scalar_one()
            == 1
        )


def test_one_stage_approval_emits_proof_without_intermediate_stage() -> None:
    _, _, _, service, instance = _runtime(positions=("CEO",))
    result = _advance(service, _envelope(instance, instance["stages"][0]))
    assert result["outcome"] == "FINAL_APPROVED"
    assert result["instance"]["stages"][0]["state"] == "APPROVED"
    assert (
        result["approval_proof"]["final_decision_hash"]
        == result["decision"]["decision_hash"]
    )


def test_rejection_is_terminal_cancels_unopened_stages_and_emits_no_proof() -> None:
    _, instances, transitions, service, instance = _runtime(
        positions=("PART_LEAD", "TEAM_LEAD", "GROUP_LEAD")
    )
    result = _advance(
        service,
        _envelope(instance, instance["stages"][0], decision_value="REJECT"),
    )
    assert result["outcome"] == "REJECTED"
    assert result["instance"]["state"] == "REJECTED"
    assert [stage["state"] for stage in result["instance"]["stages"]] == [
        "REJECTED",
        "CANCELLED",
        "CANCELLED",
    ]
    assert result["approval_proof"] is None
    assert (
        transitions.get_final_proof(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)
        is None
    )
    assert (
        instances.list_decisions(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)[0][
            "decision"
        ]
        == "REJECT"
    )


@pytest.mark.parametrize(
    ("target", "change", "detail"),
    (
        ("work_item", {"approval_domain": "NSL_WRITE"}, "approval_domain"),
        ("work_item", {"approval_provider_type": "NSL"}, "approval_provider_type"),
        ("work_item", {"target_role_ref": "CEO"}, "target_role_ref"),
        ("work_item", {"target_org_scope_ref": "other-org"}, "target_org_scope_ref"),
        ("work_item", {"state": "PENDING"}, "terminal version"),
        ("decision", {"authorized_by_oa": False}, "authorized_by_oa"),
        ("decision", {"decision_version": 2}, "decision_version"),
        ("decision", {"decided_by": "other-approver"}, "principal"),
        ("event", {"event_type": "NSL_APPROVAL_DECIDED"}, "event_type"),
        ("event", {"decision": "REJECT"}, "decision binding"),
        ("event", {"oa_decision_ref": "oa-authz:other"}, "oa_decision_ref"),
    ),
)
def test_cross_domain_and_lineage_drift_fail_closed(target, change, detail) -> None:
    _, _, _, service, instance = _runtime()
    envelope = _envelope(instance, instance["stages"][0], **{target: change})
    with pytest.raises(EosApprovalTransitionError) as error:
        _advance(service, envelope)
    assert error.value.status_code in {409, 422}
    assert detail in error.value.detail


def test_same_wc_decision_replay_with_changed_event_binding_is_rejected() -> None:
    _, _, _, service, instance = _runtime()
    envelope = _envelope(instance, instance["stages"][0])
    _advance(service, envelope)
    drift = deepcopy(envelope)
    drift[2]["correlation_id"] = "changed-correlation"
    with pytest.raises(EosApprovalTransitionError) as error:
        _advance(service, drift)
    assert error.value.error_code == "EOS_APPROVAL_TRANSITION_CONFLICT"
    assert "replay" in error.value.detail.lower()


def test_future_and_stale_authorization_times_fail_closed() -> None:
    for changes in (
        {
            "decision": {
                "decided_at": (NOW + timedelta(minutes=3))
                .isoformat()
                .replace("+00:00", "Z"),
                "authorization_checked_at": (NOW + timedelta(minutes=3))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            "event": {
                "occurred_at": (NOW + timedelta(minutes=3))
                .isoformat()
                .replace("+00:00", "Z")
            },
        },
        {
            "decision": {
                "authorization_checked_at": (NOW - timedelta(minutes=10))
                .isoformat()
                .replace("+00:00", "Z")
            }
        },
    ):
        _, _, _, service, instance = _runtime()
        with pytest.raises(EosApprovalTransitionError) as error:
            _advance(service, _envelope(instance, instance["stages"][0], **changes))
        assert error.value.status_code == 409


def test_missing_instance_and_malformed_stage_source_are_not_admitted() -> None:
    _, _, transitions, _, instance = _runtime()

    class MissingSource:
        def get_instance(self, **_kwargs):
            return None

    missing = EosBusinessApprovalTransitionService(
        approval_instances=MissingSource(), transitions=transitions
    )
    envelope = _envelope(instance, instance["stages"][0])
    with pytest.raises(EosApprovalTransitionError) as not_found:
        _advance(missing, envelope)
    assert not_found.value.status_code == 404

    source = SqlAlchemyEosApprovalInstanceRepository(_runtime()[0])
    malformed = EosBusinessApprovalTransitionService(
        approval_instances=source, transitions=transitions
    )
    bad = deepcopy(envelope)
    bad[0]["source_ref"] = "not-an-eos-stage"
    with pytest.raises(EosApprovalTransitionError):
        _advance(malformed, bad)


@pytest.mark.parametrize(
    ("overrides", "detail"),
    (
        ({"decision": "ABSTAIN"}, "decision"),
        ({"decision_version": 2}, "decision_version"),
        ({"authorized_by_oa": False}, "authorized_by_oa"),
        ({"decision_comment": 7}, "decision_comment"),
        ({"decision_comment": "x" * 2001}, "decision_comment"),
        ({"decided_by_ref": "employee"}, "decided_by_ref"),
        (
            {"decided_by_ref": {"type": "oa.service", "id": "employee"}},
            "decided_by_ref.type",
        ),
        ({"tenant_id": "bad tenant"}, "tenant_id"),
        ({"approval_instance_id": "bad"}, "approval_instance_id"),
        ({"wc_work_item_semantic_hash": "bad"}, "semantic_hash"),
        ({"oa_decision_ref": "bad ref"}, "oa_decision_ref"),
        ({"authorization_checked_at": NOW.replace(tzinfo=None)}, "timezone-aware"),
    ),
)
def test_direct_transition_input_validation_is_fail_closed(overrides, detail) -> None:
    _, _, transitions, _, instance = _runtime()
    with pytest.raises(EosApprovalTransitionError) as error:
        transitions.apply_decision(_direct_input(instance["stages"][0], **overrides))
    assert error.value.status_code == 422
    assert detail in error.value.detail


@pytest.mark.parametrize(
    ("target", "change"),
    (
        ("work_item", {"created_at": 7}),
        ("work_item", {"created_at": "not-a-time"}),
        (
            "work_item",
            {
                "expires_at": NOW.isoformat().replace("+00:00", "Z"),
            },
        ),
        ("work_item", {"semantic_hash": "bad"}),
        ("work_item", {"target_approver_ref": "bad ref"}),
        ("decision", {"decision": "ABSTAIN"}),
        ("decision", {"decision": "REJECT"}),
        ("decision", {"decision_comment": 7}),
        ("decision", {"decision_comment": "x" * 2001}),
        (
            "decision",
            {
                "decided_at": (NOW - timedelta(minutes=1))
                .isoformat()
                .replace("+00:00", "Z"),
                "authorization_checked_at": (NOW - timedelta(minutes=1))
                .isoformat()
                .replace("+00:00", "Z"),
            },
        ),
        (
            "decision",
            {
                "decided_at": (NOW + timedelta(days=2))
                .isoformat()
                .replace("+00:00", "Z"),
                "authorization_checked_at": (NOW + timedelta(days=2))
                .isoformat()
                .replace("+00:00", "Z"),
            },
        ),
        ("event", {"event_id": "bad"}),
        ("event", {"correlation_id": "bad id"}),
    ),
)
def test_malformed_wc_envelope_is_rejected(target, change) -> None:
    _, _, _, service, instance = _runtime()
    envelope = _envelope(instance, instance["stages"][0], **{target: change})
    if target == "decision" and "decided_at" in change:
        envelope[2]["occurred_at"] = change["decided_at"]
    with pytest.raises(EosApprovalTransitionError) as error:
        _advance(service, envelope)
    assert error.value.status_code in {409, 422}


@pytest.mark.parametrize("value_index", (0, 1, 2))
def test_non_object_wc_envelope_is_rejected(value_index) -> None:
    _, _, _, service, instance = _runtime()
    envelope = list(_envelope(instance, instance["stages"][0]))
    envelope[value_index] = "not-an-object"
    with pytest.raises(EosApprovalTransitionError) as error:
        _advance(service, tuple(envelope))
    assert error.value.status_code in {409, 422}


def test_missing_expiry_is_supported_and_unknown_stage_is_rejected() -> None:
    _, _, _, service, instance = _runtime()
    no_expiry = _envelope(instance, instance["stages"][0])
    no_expiry[0]["expires_at"] = None
    assert _advance(service, no_expiry)["outcome"] == "NEXT_STAGE_ACTIVE"

    _, _, _, service, instance = _runtime()
    unknown = _envelope(instance, instance["stages"][0])
    unknown[0]["source_ref"] = "eos.approval-stage:75000000-0000-4000-8000-000000000099"
    with pytest.raises(EosApprovalTransitionError) as error:
        _advance(service, unknown)
    assert "does not reference" in error.value.detail


@pytest.mark.parametrize(
    ("table_name", "values", "detail"),
    (
        ("instance", {"approval_domain": "NSL_WRITE"}, "BUSINESS_FORMAL"),
        ("instance", {"state": "CANCELLED"}, "not pending"),
        (
            "instance",
            {"expires_at": NOW + timedelta(seconds=30)},
            "expired",
        ),
        ("stage", {"state": "WAITING"}, "active EOS stage"),
        ("instance", {"active_stage_order": 2}, "active EOS stage"),
    ),
)
def test_repository_rechecks_locked_instance_and_stage(
    table_name, values, detail
) -> None:
    sessions, _, transitions, _, instance = _runtime()
    table = (
        EOS_APPROVAL_INSTANCE_TABLE
        if table_name == "instance"
        else EOS_APPROVAL_STAGE_TABLE
    )
    with sessions.begin() as session:
        session.execute(
            sql_update(table).where(table.c.tenant_id == TENANT).values(**values)
        )
    with pytest.raises(EosApprovalTransitionError) as error:
        transitions.apply_decision(_direct_input(instance["stages"][0]))
    assert error.value.status_code == 409
    assert detail in error.value.detail


def test_repository_missing_stage_and_instance_fail_closed() -> None:
    sessions, _, transitions, _, instance = _runtime()
    with sessions.begin() as session:
        session.execute(
            EOS_APPROVAL_STAGE_TABLE.delete().where(
                EOS_APPROVAL_STAGE_TABLE.c.tenant_id == TENANT
            )
        )
    with pytest.raises(EosApprovalTransitionError) as missing_stage:
        transitions.apply_decision(_direct_input(instance["stages"][0]))
    assert "does not bind" in missing_stage.value.detail

    sessions, _, transitions, _, instance = _runtime()
    with sessions.begin() as session:
        session.execute(
            EOS_APPROVAL_INSTANCE_TABLE.delete().where(
                EOS_APPROVAL_INSTANCE_TABLE.c.tenant_id == TENANT
            )
        )
    with pytest.raises(EosApprovalTransitionError) as missing_instance:
        transitions.apply_decision(_direct_input(instance["stages"][0]))
    assert missing_instance.value.status_code == 404


def test_transition_persistence_failures_are_redacted() -> None:
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args, **_kwargs):
            raise SQLAlchemyError("private transition detail")

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    broken = SqlAlchemyEosApprovalTransitionRepository(
        lambda: BrokenSession(), clock=lambda: NOW + timedelta(minutes=2)
    )
    with pytest.raises(EosApprovalTransitionError) as proof_error:
        broken.get_final_proof(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)
    assert proof_error.value.status_code == 503
    assert "private transition detail" not in proof_error.value.detail

    _, _, _, _, instance = _runtime()
    with pytest.raises(EosApprovalTransitionError) as apply_error:
        broken.apply_decision(_direct_input(instance["stages"][0]))
    assert apply_error.value.status_code == 503
    assert "private transition detail" not in apply_error.value.detail


def test_repository_rejects_stale_authorization_without_service_prefilter() -> None:
    _, _, transitions, _, instance = _runtime()
    with pytest.raises(EosApprovalTransitionError) as error:
        transitions.apply_decision(
            _direct_input(
                instance["stages"][0],
                authorization_checked_at=NOW - timedelta(minutes=10),
            )
        )
    assert "not fresh" in error.value.detail


def test_final_proof_refuses_a_corrupted_non_approve_decision_chain() -> None:
    sessions, instances, _, service, instance = _runtime()
    _advance(service, _envelope(instance, instance["stages"][0]))
    with sessions.begin() as session:
        session.execute(
            sql_update(EOS_APPROVAL_DECISION_TABLE)
            .where(EOS_APPROVAL_DECISION_TABLE.c.tenant_id == TENANT)
            .values(decision="REJECT")
        )
    current = instances.get_instance(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)
    with pytest.raises(EosApprovalTransitionError) as error:
        _advance(service, _envelope(current, current["stages"][1], suffix=2))
    assert "every stage approval" in error.value.detail
    after = instances.get_instance(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)
    assert after["state"] == "PENDING"
    assert after["active_stage_order"] == 2


@pytest.mark.parametrize("mode", ("error", "missing"))
def test_post_commit_projection_failure_is_redacted(monkeypatch, mode) -> None:
    _, _, transitions, _, instance = _runtime(positions=("CEO",))
    if mode == "error":

        def fail(**_kwargs):
            raise EosApprovalInstanceError(
                "PRIVATE",
                "private instance detail",
                status_code=503,
            )

        monkeypatch.setattr(transitions._instances, "get_instance", fail)
    else:
        monkeypatch.setattr(
            transitions._instances,
            "get_instance",
            lambda **_kwargs: None,
        )
    with pytest.raises(EosApprovalTransitionError) as error:
        transitions.apply_decision(_direct_input(instance["stages"][0]))
    assert error.value.status_code == 503
    assert "private instance detail" not in error.value.detail


def test_integrity_conflict_and_decision_reload_failure_are_redacted(
    monkeypatch,
) -> None:
    _, _, transitions, _, instance = _runtime()

    def integrity_failure(*_args, **_kwargs):
        raise IntegrityError("private statement", {}, RuntimeError("private detail"))

    monkeypatch.setattr(transitions, "_load_wc_decision", integrity_failure)
    with pytest.raises(EosApprovalTransitionError) as conflict:
        transitions.apply_decision(_direct_input(instance["stages"][0]))
    assert conflict.value.status_code == 409
    assert "private" not in conflict.value.detail

    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args, **_kwargs):
            raise SQLAlchemyError("private reload detail")

    reloader = SqlAlchemyEosApprovalTransitionRepository(lambda: BrokenSession())
    with pytest.raises(EosApprovalTransitionError) as unavailable:
        reloader._get_wc_decision_projection(
            tenant_id=TENANT,
            wc_decision_id="75000000-0000-4000-8003-000000000001",
        )
    assert unavailable.value.status_code == 503
    assert "private" not in unavailable.value.detail


def test_malformed_prefixed_stage_and_non_mapping_work_item_are_rejected() -> None:
    _, _, _, service, instance = _runtime()
    bad_stage = _envelope(instance, instance["stages"][0])
    bad_stage[0]["source_ref"] = "eos.approval-stage:not-a-uuid"
    with pytest.raises(EosApprovalTransitionError):
        _advance(service, bad_stage)

    with pytest.raises(EosApprovalTransitionError) as invalid:
        approval_transitions._admit_wc_work_item(
            instance=instance,
            stage=instance["stages"][0],
            value="not-an-object",  # type: ignore[arg-type]
        )
    assert invalid.value.status_code == 422


class _Result:
    def __init__(self, *, rowcount=1, row=None):
        self.rowcount = rowcount
        self._row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row


class _SequenceSession:
    def __init__(self, *results):
        self._results = iter(results)

    def execute(self, *_args, **_kwargs):
        return next(self._results)


def test_concurrent_rowcount_guards_fail_closed() -> None:
    stage = {
        "tenant_id": TENANT,
        "approval_stage_id": "75000000-0000-4000-8000-000000000011",
        "approval_instance_id": INSTANCE_ID,
        "stage_order": 1,
        "state": "ACTIVE",
        "version": 1,
    }
    instance = {
        "tenant_id": TENANT,
        "approval_instance_id": INSTANCE_ID,
        "state": "PENDING",
        "version": 1,
    }
    with pytest.raises(EosApprovalTransitionError):
        SqlAlchemyEosApprovalTransitionRepository._close_active_stage(
            _SequenceSession(_Result(rowcount=0)),  # type: ignore[arg-type]
            stage=stage,
            state="APPROVED",
            decided_at=NOW,
            recorded_at=NOW,
        )
    with pytest.raises(EosApprovalTransitionError):
        SqlAlchemyEosApprovalTransitionRepository._reject_instance(
            _SequenceSession(_Result(), _Result(rowcount=0)),  # type: ignore[arg-type]
            instance=instance,
            decided_at=NOW,
            recorded_at=NOW,
        )
    with pytest.raises(EosApprovalTransitionError):
        SqlAlchemyEosApprovalTransitionRepository._approve_instance(
            _SequenceSession(_Result(rowcount=0)),  # type: ignore[arg-type]
            instance=instance,
            recorded_at=NOW,
        )


def test_next_stage_missing_and_instance_race_fail_closed() -> None:
    instance = {
        "tenant_id": TENANT,
        "approval_instance_id": INSTANCE_ID,
        "state": "PENDING",
        "version": 1,
    }
    current = {"stage_order": 1}
    with pytest.raises(EosApprovalTransitionError) as missing:
        SqlAlchemyEosApprovalTransitionRepository._activate_next_stage(
            _SequenceSession(_Result(row=None)),  # type: ignore[arg-type]
            instance=instance,
            current_stage=current,
            activated_at=NOW,
            recorded_at=NOW,
        )
    assert "not waiting" in missing.value.detail

    waiting = {
        "approval_stage_id": "75000000-0000-4000-8000-000000000012",
        "state": "WAITING",
        "version": 1,
    }
    with pytest.raises(EosApprovalTransitionError) as raced:
        SqlAlchemyEosApprovalTransitionRepository._activate_next_stage(
            _SequenceSession(
                _Result(row=waiting),
                _Result(rowcount=1),
                _Result(rowcount=0),
            ),  # type: ignore[arg-type]
            instance=instance,
            current_stage=current,
            activated_at=NOW,
            recorded_at=NOW,
        )
    assert "changed concurrently" in raced.value.detail
