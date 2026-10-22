from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from nex_ae_api.nsl_controlled_write_integration import (
    NslControlledWriteIntegration,
    NslControlledWriteRequest,
)
from nex_ae_api.nsl_eos_post_write_verification import (
    HttpEosPostWriteVerificationAdapter,
)
from nex_ae_api.nsl_eos_write_execution import HttpEosWriteExecutionPort
from nex_ae_api.nsl_idempotency import SqlAlchemyNslIdempotencyEvidencePort
from nex_ae_api.nsl_runtime_policy import PlatformRuntimePolicyAdapter
from nex_ae_api.nsl_v02_public_api import load_nsl_v02_public_api
from nex_ae_api.nsl_write_evidence import SqlAlchemyNslWriteEvidencePort
from nex_eos import (
    EOS_ACCOUNT_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_PROJECT_TABLE,
    EOS_VOUCHER_ATTACHMENT_TABLE,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    AccountInput,
    EosCreateVoucherDraftService,
    EosVoucherAuthorizationClient,
    NvtProjectInput,
    ProjectInput,
    create_eos_app,
)
from nex_runtime import issue_mock_service_token
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
AE_DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL", "")
EOS_DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_P8_S62_ACTUAL_WHEEL_POSTGRES_GATE") == "1"

pytestmark = pytest.mark.skipif(
    not AE_DATABASE_URL or not EOS_DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S62 actual-wheel PostgreSQL gate is disabled",
)

_EOS_TENANT_TABLES = (
    EOS_VOUCHER_ATTACHMENT_TABLE,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_ACCOUNT_TABLE,
    EOS_PROJECT_TABLE,
    EOS_NVT_PROJECT_TABLE,
)


class EosAuthorizationSource:
    def __init__(self) -> None:
        self.active = True
        self.calls = 0

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        self.calls += 1
        return {
            "active": self.active,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": ["finance:voucher-draft:create"],
            "revision_hash": "a" * 64,
        }


class GovernedWriteSource:
    def __init__(self, evaluated_at: datetime) -> None:
        self._evaluated_at = evaluated_at
        self.calls = 0

    def resolve(self, request: Any) -> dict[str, Any]:
        self.calls += 1
        fingerprint = "sha256:" + "c" * 64
        return {
            "tenant_id": request.tenant_id,
            "business_operation_id": str(request.business_operation_id),
            "oa_decision_ref": f"oa-authz:{request.business_operation_id}",
            "oa_allowed": True,
            "protected_operation": {
                "tenant_id": request.tenant_id,
                "agent_execution_id": "agent-execution-p8-s62",
                "executable_step_id": request.write_node_id,
                "business_operation_id": str(request.business_operation_id),
                "actor_ref": request.subject_id,
                "agent_ref": "ia-p8-s62",
                "org_scope_refs": ["org:finance"],
                "project_ref": "project:p8-s62",
                "resource_refs": ["voucher:draft"],
                "capability": "WRITE",
                "operation_class": "CREATE",
                "data_classification": "CONFIDENTIAL",
                "typed_parameters": {"voucher_type": "GENERAL"},
                "business_object_type": "VOUCHER_DRAFT",
                "operation_fingerprint": fingerprint,
            },
            "operation_trust_decision": {
                "decision": "ALLOW",
                "decision_mode": "RULE_EVALUATED",
                "assurance_level": "HIGH",
                "operation_fingerprint": fingerprint,
                "rule_set_ref": "policy:finance-write",
                "rule_set_version": "8",
                "facts_hash": "sha256:" + "d" * 64,
                "proof_ref": "trust-proof:p8-s62",
                "reason_code": None,
                "decision_hash": "sha256:" + "e" * 64,
                "evaluated_at": self._evaluated_at.isoformat(),
                "expires_at": (
                    self._evaluated_at + timedelta(minutes=10)
                ).isoformat(),
            },
            "required_assurance_level": "HIGH",
        }


def _payload(
    *,
    tenant_id: str,
    project_id: str,
    debit_id: str,
    credit_id: str,
    description: str,
) -> dict[str, object]:
    return {
        "schema_version": "eos_create_voucher_draft_command.v1",
        "tenant_id": tenant_id,
        "requester_ref": {"type": "oa.user", "id": "employee-p8-s62"},
        "project_ref": {"type": "eos.project", "id": project_id},
        "voucher_type": "GENERAL",
        "transaction_date": "2026-10-22",
        "currency": "KRW",
        "description": description,
        "lines": [
            {
                "line_no": 1,
                "account_ref": {"type": "eos.account", "id": debit_id},
                "signed_amount": "62000.00",
                "economic_category": "TRAVEL",
                "description": "P8-S62 protected debit",
                "evidence_refs": ["approval-evidence-p8-s62"],
            },
            {
                "line_no": 2,
                "account_ref": {"type": "eos.account", "id": credit_id},
                "signed_amount": "-62000.00",
                "economic_category": "CASH",
                "description": "P8-S62 protected credit",
                "evidence_refs": ["approval-evidence-p8-s62"],
            },
        ],
        "nsl_approval_request_id": f"approval-{tenant_id}",
        "nsl_approval_evidence_ref": "approval-evidence-p8-s62",
        "business_approval_proof_ref": None,
        "attachments": [],
    }


def _skill_and_contract():
    from nsl.core import (
        STRING,
        DataClassification,
        RiskLevel,
        ToolCapability,
        record_type,
    )
    from nsl.ir import (
        BuildMetadata,
        RequiredTool,
        ResourceLimits,
        SkillObject,
        StaticAnalysis,
    )
    from nsl.tools import (
        Atomicity,
        CommitConfirmation,
        CommitSemantics,
        IdempotencySemantics,
        OperationKind,
        PostWriteVerification,
        ToolContract,
        WriteSemantics,
    )

    result_type = record_type("VoucherDraft", voucher_no=STRING)
    fields = tuple(_payload(
        tenant_id="t",
        project_id="p",
        debit_id="d",
        credit_id="c",
        description="x",
    ))
    contract = ToolContract(
        tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
        version="1.0.0",
        capability=ToolCapability.WRITE,
        input_types=tuple((name, STRING) for name in fields),
        output_type=result_type,
        required_scope="finance:voucher:write",
        output_classification=DataClassification.CONFIDENTIAL,
        operation_kind=OperationKind.CREATE_DRAFT,
        risk_level=RiskLevel.R3,
        write_semantics=WriteSemantics(
            side_effect=True,
            atomicity=Atomicity.ATOMIC,
            idempotency=IdempotencySemantics(
                required=True,
                scope="TOOL_AND_TENANT",
                retention="PROVIDER_DEFINED",
                duplicate_behavior="RETURN_ORIGINAL_RESULT",
                payload_conflict_behavior="IDEMPOTENCY_CONFLICT",
            ),
            commit=CommitSemantics(CommitConfirmation.EXPLICIT),
            approval_required=True,
            preconditions_supported=True,
            verification=PostWriteVerification(
                tool_id="FINANCE.GET_VOUCHER_DRAFT",
                reference_schema=result_type,
                consistency_hint="READ_AFTER_WRITE_STRONG",
            ),
        ),
    )
    required = RequiredTool(
        tool_ref="urn:nex:tool:finance-create-voucher-draft:v1",
        tool_id=contract.tool_id,
        version=contract.version,
        capability=contract.capability,
        contract_hash=contract.contract_hash,
        required_scope=contract.required_scope,
        output_classification=contract.output_classification,
        risk_level=contract.risk_level,
    )
    skill = SkillObject(
        ir_version="nsl-ir/0.2",
        language_version="0.2",
        skill_id="P8.S62.CONTROLLED_WRITE",
        skill_version="1.0.0",
        risk="WRITE",
        semantics_profile="NSL_0_2",
        semantic_hash="sha256:" + "0" * 64,
        features=frozenset({"APPROVAL", "WRITE"}),
        symbols=(),
        required_tools=(required,),
        limits=ResourceLimits(
            tool_calls=2,
            loop_iterations=1,
            emitted_rows=1,
            collection_size=1,
            duration_ms=30_000,
        ),
        inputs=(),
        contexts=(),
        outputs=(),
        body=(),
        analysis=StaticAnalysis(
            max_tool_calls=1,
            max_loop_iterations=0,
            max_emit_records=0,
            bounded=True,
        ),
        build=BuildMetadata(
            source_bundle_sha256="sha256:" + "f" * 64,
            root_source="p8-s62-protected-gate.ns",
            sources=(),
        ),
    ).with_computed_hash()
    return skill, contract, result_type


def _context(skill: Any, *, tenant_id: str, operation_id: str, suffix: str):
    from nsl.core import BusinessOperationId
    from nsl.runtime_models import ExecutionContext, ExecutionRequest
    from nsl.security import ExecutionPrincipal, PrincipalVerification

    principal = ExecutionPrincipal(
        tenant_id=tenant_id,
        subject_id="employee-p8-s62",
        actor_type="USER",
        roles=frozenset({"FINANCE_APPROVER"}),
        scopes=frozenset(
            {
                "nsl:skill:execute",
                "finance:voucher:write",
                "finance:voucher:verify",
            }
        ),
        auth_context_ref=f"auth-p8-s62-{suffix}",
        verification=PrincipalVerification.VERIFIED,
    )
    request = ExecutionRequest(
        execution_id=f"execution-p8-s62-{suffix}",
        inputs={},
        runtime_context={},
        principal=principal,
        business_operation_id=BusinessOperationId(operation_id),
    )
    return ExecutionContext(skill, request)


def _controlled_request(
    *,
    public_api: Any,
    skill: Any,
    contract: Any,
    context: Any,
    payload: dict[str, object],
    now: datetime,
    suffix: str,
) -> NslControlledWriteRequest:
    from nsl.approval import ApprovalEvidence
    from nsl.core import (
        STRING,
        ApprovalDecision,
        ApprovalRequestId,
        ApprovalStatus,
        RiskLevel,
        ValueEnvelope,
    )
    from nsl.runtime_models import ValidationSummary
    from nsl.validation import (
        BusinessPreconditionEvidence,
        BusinessPreconditionMechanism,
        PreWriteEvidence,
        WriteContractEvidence,
    )
    from nsl.write_intent import (
        WriteIntent,
        compute_payload_hash,
        compute_write_intent_hash,
    )

    arguments = {
        name: ValueEnvelope.complete(value, STRING) for name, value in payload.items()
    }
    payload_hash = compute_payload_hash(arguments)
    intent_hash = compute_write_intent_hash(
        skill_semantic_hash=skill.semantic_hash,
        write_node_id="write-voucher-draft",
        tool_id=contract.tool_id,
        payload_hash=payload_hash,
    )
    intent = WriteIntent(
        tenant_id=context.tenant_id,
        business_operation_id=context.identity.business_operation_id,
        node_id="write-voucher-draft",
        tool_ref="urn:nex:tool:finance-create-voucher-draft:v1",
        tool_id=contract.tool_id,
        approval_id="APPROVE_VOUCHER_DRAFT",
        skill_semantic_hash=skill.semantic_hash,
        canonical_arguments=arguments,
        payload_hash=payload_hash,
        write_intent_hash=intent_hash,
    )
    approval_request_id = ApprovalRequestId(payload["nsl_approval_request_id"])
    approval = ApprovalEvidence(
        tenant_id=context.tenant_id,
        execution_id=context.identity.execution_id,
        business_operation_id=context.identity.business_operation_id,
        approval_id=intent.approval_id,
        approval_request_id=approval_request_id,
        skill_semantic_hash=skill.semantic_hash,
        decision=ApprovalDecision.APPROVED,
        approver_id="finance-manager-p8-s62",
        decided_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=10),
        payload_hash=payload_hash,
        write_intent_hash=intent_hash,
        evidence_integrity=f"approval-signature:{suffix}",
    )
    contract_evidence = WriteContractEvidence(
        tool_id=contract.tool_id,
        contract_hash=contract.contract_hash,
        capability=contract.capability,
        risk_level=RiskLevel.R3,
        preconditions_supported=True,
    )
    precondition = BusinessPreconditionEvidence(
        evidence_id=f"precondition-{suffix}",
        tenant_id=context.tenant_id,
        business_operation_id=context.identity.business_operation_id,
        write_node_id=intent.node_id,
        tool_id=intent.tool_id,
        contract_hash=contract.contract_hash,
        payload_hash=payload_hash,
        write_intent_hash=intent_hash,
        mechanism=BusinessPreconditionMechanism.ETAG,
        evidence_ref=f"etag:opaque:{suffix}",
        observed_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=10),
        provider_atomic_enforcement=True,
    )
    execution_evidence = PreWriteEvidence(
        validation=ValidationSummary.from_checks(tuple(context.checks)),
        approval_status=ApprovalStatus.APPROVED,
        approval_evidence_valid=True,
        runtime_preflight_passed=True,
        current_policy_allowed=False,
        tool_preconditions_passed=False,
        business_preconditions_passed=False,
        intent_binding_valid=True,
        idempotency_ready=True,
        durability_ready=True,
        trust_valid=True,
        replay_live_write_allowed=True,
    )
    provider_evidence = public_api.provider_idempotency_evidence(
        tool_id=contract.tool_id,
        contract_hash=contract.contract_hash,
        retention_policy="PROVIDER_DEFINED",
        provider_guarantee_ref="eos:idempotency:p8-s62",
        verified_at=now - timedelta(seconds=1),
        guaranteed_until=now + timedelta(days=30),
        durable_duplicate_guarantee=True,
    )
    return NslControlledWriteRequest(
        intent=intent,
        context=context,
        contract=contract,
        contract_evidence=contract_evidence,
        execution_evidence=execution_evidence,
        business_preconditions=precondition,
        approval_evidence=approval,
        approval_request_id=approval_request_id,
        provider_idempotency_evidence=provider_evidence,
        invocation_id=f"invocation-p8-s62-{suffix}",
        trace_refs=(
            f"trace_id:trace-{suffix}",
            f"correlation_id:correlation-{suffix}",
            f"causation_id:write-{suffix}",
        ),
        evaluated_at=now,
        required_until=now + timedelta(days=7),
        requested_at=now,
    )


def _eos_counts(runtime: Any, tenant_id: str) -> dict[str, int]:
    with runtime.engine.connect() as connection:
        return {
            table.name: connection.execute(
                select(func.count())
                .select_from(table)
                .where(table.c.tenant_id == tenant_id)
            ).scalar_one()
            for table in _EOS_TENANT_TABLES
        }


def _cleanup_eos(runtime: Any, tenant_id: str) -> None:
    with runtime.engine.begin() as connection:
        for table in _EOS_TENANT_TABLES:
            connection.execute(table.delete().where(table.c.tenant_id == tenant_id))


def _cleanup_ae(engine: Any, tenant_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM ae_nsl_write_evidence WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        connection.execute(
            text("DELETE FROM ae_nsl_idem_evidence WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )


def test_controlled_write_actual_wheel_postgres_gate() -> None:
    from nsl.core import DataClassification, VerificationStatus
    from nsl.idempotency import IdempotencyConflictError
    from nsl.write_intent import WriteIntent, WriteIntentError

    assert importlib.metadata.version("nex-skill-language") == "0.2.0"
    assert make_url(AE_DATABASE_URL).database == "nex_ae_test"
    assert make_url(EOS_DATABASE_URL).database == "nex_eos_test"
    readiness = json.loads(
        (ROOT / "reports/deployment/p8-s04-nsl-v0.2-readiness.json").read_text(
            encoding="utf-8"
        )
    )["readiness"]
    public_api = load_nsl_v02_public_api(readiness)
    skill, contract, result_type = _skill_and_contract()
    suffix = uuid4().hex[:16]
    tenant_id = f"p8-s62-{suffix}"
    nvt_id = str(uuid4())
    project_id = str(uuid4())
    debit_id = str(uuid4())
    credit_id = str(uuid4())
    operation_id = str(uuid4())
    voucher_id = str(uuid4())
    now = datetime.now(UTC)

    ae_engine = create_engine(AE_DATABASE_URL, poolclass=NullPool)
    ae_factory = sessionmaker(bind=ae_engine, expire_on_commit=False)
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "2.1.0-p8-s62",
            "NEX_BUILD_SHA": "p8s62protected",
            "NEX_EOS_DATABASE_URL": EOS_DATABASE_URL,
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    eos_runtime = app.state.eos_database_runtime
    assert eos_runtime is not None
    eos_authorization = EosAuthorizationSource()
    app.state.eos_voucher_command_service = EosCreateVoucherDraftService(
        coordinator=app.state.eos_business_transactions,
        vouchers=app.state.eos_vouchers,
        authorizer=EosVoucherAuthorizationClient(
            eos_authorization,
            clock=lambda: now,
        ),
        id_factory=lambda: voucher_id,
        clock=lambda: now,
    )
    _cleanup_ae(ae_engine, tenant_id)
    _cleanup_eos(eos_runtime, tenant_id)
    try:
        with ae_engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            ) == ("nex_ae_test", "nex_ae_user")
            ae_migrations = set(
                connection.execute(
                    text("SELECT version FROM schema_migrations")
                ).scalars()
            )
        with eos_runtime.engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            ) == ("nex_eos_test", "nex_eos_user")
            eos_migrations = set(
                connection.execute(
                    text("SELECT version FROM schema_migrations")
                ).scalars()
            )
        assert "2506_ae_nsl_idempotency_evidence" in ae_migrations
        assert "2507_ae_nsl_write_evidence" in ae_migrations
        assert "2508_eos_operation_name_compatibility" in eos_migrations

        app.state.eos_projects.create_nvt_project(
            NvtProjectInput(tenant_id, nvt_id, f"NVT-{suffix}", "P8 S62 NVT")
        )
        app.state.eos_projects.create_project(
            ProjectInput(
                tenant_id,
                project_id,
                f"PROJECT-{suffix}",
                "P8 S62 Project",
                nvt_project_id=nvt_id,
            )
        )
        for account_id, code, category in (
            (debit_id, f"TRAVEL-{suffix}", "EXPENSE"),
            (credit_id, f"CASH-{suffix}", "ASSET"),
        ):
            app.state.eos_accounts.create_account(
                AccountInput(
                    tenant_id,
                    account_id,
                    code,
                    code,
                    category,
                    "GENERAL",
                    date(2026, 1, 1),
                )
            )
        baseline = _eos_counts(eos_runtime, tenant_id)

        token = issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-eos",
        ).access_token
        transport = httpx.ASGITransport(app=app)
        policy_source = GovernedWriteSource(now)
        integration = NslControlledWriteIntegration(
            public_api=public_api,
            policy_port=PlatformRuntimePolicyAdapter(
                authorization_source=policy_source,
                public_api=public_api,
            ),
            idempotency_port=SqlAlchemyNslIdempotencyEvidencePort(
                ae_factory,
                public_api=public_api,
                clock=lambda: now,
            ),
            write_evidence_port=SqlAlchemyNslWriteEvidencePort(
                ae_factory,
                public_api=public_api,
                clock=lambda: now,
            ),
            write_port=HttpEosWriteExecutionPort(
                public_api=public_api,
                base_url="http://nex-eos.test",
                service_token=token,
                transport=transport,
                result_type=result_type,
                result_classification=DataClassification.CONFIDENTIAL,
            ),
            verification_port=HttpEosPostWriteVerificationAdapter(
                public_api=public_api,
                base_url="http://nex-eos.test",
                service_token=token,
                transport=transport,
            ),
        )
        context = _context(
            skill,
            tenant_id=tenant_id,
            operation_id=operation_id,
            suffix=suffix,
        )
        payload = _payload(
            tenant_id=tenant_id,
            project_id=project_id,
            debit_id=debit_id,
            credit_id=credit_id,
            description="P8-S62 controlled WRITE integration gate",
        )
        request = _controlled_request(
            public_api=public_api,
            skill=skill,
            contract=contract,
            context=context,
            payload=payload,
            now=now,
            suffix=suffix,
        )

        first = asyncio.run(integration.execute(request))
        replay = asyncio.run(integration.execute(request))

        assert isinstance(first.outcome, public_api.write_committed)
        assert isinstance(replay.outcome, public_api.write_committed)
        assert first.outcome.result == replay.outcome.result
        assert first.verification.status is VerificationStatus.VERIFIED
        assert replay.verification.status is VerificationStatus.VERIFIED
        assert first.reservation.disposition.value == "CREATED"
        assert replay.reservation.disposition.value == "REUSED"
        committed = _eos_counts(eos_runtime, tenant_id)
        assert committed[EOS_BUSINESS_OPERATION_TABLE.name] == 1
        assert committed[EOS_IDEMPOTENCY_TABLE.name] == 1
        assert committed[EOS_VOUCHER_DRAFT_TABLE.name] == 1
        assert committed[EOS_VOUCHER_DRAFT_LINE_TABLE.name] == 2
        assert committed[EOS_OUTBOX_TABLE.name] == 1
        assert committed[EOS_PROJECT_TABLE.name] == baseline[EOS_PROJECT_TABLE.name]
        assert committed[EOS_ACCOUNT_TABLE.name] == baseline[EOS_ACCOUNT_TABLE.name]

        conflict_context = _context(
            skill,
            tenant_id=tenant_id,
            operation_id=operation_id,
            suffix=f"{suffix}-conflict",
        )
        conflict_request = _controlled_request(
            public_api=public_api,
            skill=skill,
            contract=contract,
            context=conflict_context,
            payload={**payload, "description": "conflicting payload"},
            now=now,
            suffix=f"{suffix}-conflict",
        )
        with pytest.raises(IdempotencyConflictError):
            asyncio.run(integration.execute(conflict_request))
        assert _eos_counts(eos_runtime, tenant_id) == committed

        eos_authorization.active = False
        denied_operation = str(uuid4())
        denied_context = _context(
            skill,
            tenant_id=tenant_id,
            operation_id=denied_operation,
            suffix=f"{suffix}-denied",
        )
        denied = asyncio.run(
            integration.execute(
                _controlled_request(
                    public_api=public_api,
                    skill=skill,
                    contract=contract,
                    context=denied_context,
                    payload=payload,
                    now=now,
                    suffix=f"{suffix}-denied",
                )
            )
        )
        assert isinstance(denied.outcome, public_api.write_not_committed)
        assert denied.verification is None
        assert _eos_counts(eos_runtime, tenant_id) == committed

        eos_authorization.active = True
        invalid_operation = str(uuid4())
        invalid_context = _context(
            skill,
            tenant_id=tenant_id,
            operation_id=invalid_operation,
            suffix=f"{suffix}-invalid",
        )
        invalid = asyncio.run(
            integration.execute(
                _controlled_request(
                    public_api=public_api,
                    skill=skill,
                    contract=contract,
                    context=invalid_context,
                    payload=_payload(
                        tenant_id=tenant_id,
                        project_id=str(uuid4()),
                        debit_id=str(uuid4()),
                        credit_id=credit_id,
                        description="invalid project and account",
                    ),
                    now=now,
                    suffix=f"{suffix}-invalid",
                )
            )
        )
        assert isinstance(invalid.outcome, public_api.write_not_committed)
        assert invalid.verification is None
        assert _eos_counts(eos_runtime, tenant_id) == committed

        wrong_hash = type(request.intent.payload_hash)("sha256:" + "0" * 64)
        with pytest.raises(WriteIntentError, match="payload_hash"):
            WriteIntent(
                tenant_id=request.intent.tenant_id,
                business_operation_id=request.intent.business_operation_id,
                node_id=request.intent.node_id,
                tool_ref=request.intent.tool_ref,
                tool_id=request.intent.tool_id,
                approval_id=request.intent.approval_id,
                skill_semantic_hash=request.intent.skill_semantic_hash,
                canonical_arguments=request.intent.canonical_arguments,
                payload_hash=wrong_hash,
                write_intent_hash=request.intent.write_intent_hash,
            )
        assert _eos_counts(eos_runtime, tenant_id) == committed

        with ae_engine.connect() as connection:
            ae_counts = dict(
                connection.execute(
                    text(
                        "SELECT 'idempotency' AS kind, count(*) AS total "
                        "FROM ae_nsl_idem_evidence WHERE tenant_id = :tenant_id "
                        "UNION ALL "
                        "SELECT 'write_evidence', count(*) "
                        "FROM ae_nsl_write_evidence WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).all()
            )
        assert ae_counts == {"idempotency": 3, "write_evidence": 3}
        assert policy_source.calls == 5
        assert eos_authorization.calls == 4
    finally:
        _cleanup_ae(ae_engine, tenant_id)
        _cleanup_eos(eos_runtime, tenant_id)
        assert all(
            count == 0 for count in _eos_counts(eos_runtime, tenant_id).values()
        )
        ae_engine.dispose()
        eos_runtime.dispose()
