from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .approval_instances import (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_PROOF_TABLE,
)
from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_transactions import EOS_METADATA
from .cost_source_pools import COST_SOURCE_KINDS
from .legal_entities import (
    EOS_LEGAL_ENTITY_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
)
from .project_work_assignments import EOS_PROJECT_WORK_ASSIGNMENT_TABLE
from .projects import EOS_PROJECT_TABLE

ALLOCATION_PLAN_RELEASE_OPERATION = "FINANCE.COST_ALLOCATION_PLAN.RELEASE"
ALLOCATION_PLAN_GET_OPERATION = "FINANCE.COST_ALLOCATION_PLAN.GET"
ALLOCATION_PLAN_APPROVE_SCOPE = "finance:cost-allocation-plan:approve"
ALLOCATION_PLAN_SCHEMA = "eos_cost_allocation_plan.v1"

ALLOCATION_BASIS_KINDS = frozenset(
    {
        "ACTUAL_WORK",
        "APPROVED_PLAN",
        "USAGE",
        "HEADCOUNT_CASCADE",
        "JUSTIFIED_PERCENTAGE",
    }
)
ALLOCATION_SCOPE_TYPES = frozenset({"COMPANY", "PROJECT_SET", "PROJECT"})
ALLOCATION_CONFIDENTIALITY_CLASSES = frozenset(
    {"INTERNAL", "CONFIDENTIAL", "RESTRICTED"}
)
_BASIS_PRIORITY = {
    "ACTUAL_WORK": 1,
    "USAGE": 1,
    "APPROVED_PLAN": 2,
    "HEADCOUNT_CASCADE": 3,
    "JUSTIFIED_PERCENTAGE": 4,
}
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")


EOS_COST_ALLOCATION_PLAN_TABLE = Table(
    "eos_cost_allocation_plan",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("plan_id", Uuid(as_uuid=False), primary_key=True),
    Column("plan_revision", Integer, primary_key=True),
    Column("source_kind", String(32), nullable=False),
    Column("scope_type", String(32), nullable=False),
    Column("basis_kind", String(32), nullable=False),
    Column("rule_release_hash", String(71), nullable=False),
    Column("basis_source_ref", String(256), nullable=False),
    Column("basis_source_hash", String(71), nullable=False),
    Column("effective_start", Date, nullable=False),
    Column("effective_end", Date, nullable=True),
    Column("approved_by", String(128), nullable=False),
    Column("approved_proof", String(256), nullable=False),
    Column("state", String(16), nullable=False),
    Column("plan_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id", "company_id", "plan_hash", name="ux_eos_cost_plan_hash"
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_cost_plan_company",
    ),
    CheckConstraint("plan_revision > 0", name="ck_eos_cost_plan_revision"),
    CheckConstraint(
        "basis_kind IN ('ACTUAL_WORK','APPROVED_PLAN','USAGE',"
        "'HEADCOUNT_CASCADE','JUSTIFIED_PERCENTAGE')",
        name="ck_eos_cost_plan_basis",
    ),
    CheckConstraint(
        "state IN ('DRAFT','APPROVED','REVOKED','SUPERSEDED')",
        name="ck_eos_cost_plan_state",
    ),
    CheckConstraint(
        "effective_end IS NULL OR effective_end >= effective_start",
        name="ck_eos_cost_plan_period",
    ),
)

EOS_COST_ALLOCATION_PLAN_LINE_TABLE = Table(
    "eos_cost_allocation_plan_line",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("plan_id", Uuid(as_uuid=False), primary_key=True),
    Column("plan_revision", Integer, primary_key=True),
    Column("line_no", Integer, primary_key=True),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("project_code", String(11), nullable=False),
    Column("work_code", String(32), nullable=True),
    Column("basis_units", Numeric(24, 8), nullable=False),
    Column("allocation_ratio", Numeric(18, 12), nullable=False),
    Column("eligibility_hash", String(71), nullable=False),
    Column("confidentiality_class", String(32), nullable=False),
    Column("line_hash", String(71), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "plan_id", "plan_revision"),
        (
            "eos_cost_allocation_plan.tenant_id",
            "eos_cost_allocation_plan.company_id",
            "eos_cost_allocation_plan.plan_id",
            "eos_cost_allocation_plan.plan_revision",
        ),
        name="fk_eos_cost_plan_line_plan",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_cost_plan_line_project",
    ),
    CheckConstraint("line_no > 0", name="ck_eos_cost_plan_line_no"),
    CheckConstraint("basis_units >= 0", name="ck_eos_cost_plan_line_basis"),
    CheckConstraint(
        "allocation_ratio >= 0 AND allocation_ratio <= 1",
        name="ck_eos_cost_plan_line_ratio",
    ),
)


class EosAllocationPlanError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


class AllocationPlanRepository(Protocol):
    def load_approval_context(
        self, *, tenant_id: str, approval_proof_id: str
    ) -> Mapping[str, Any] | None: ...

    def release(
        self,
        candidate: Mapping[str, Any],
        *,
        approval_proof_id: str,
    ) -> tuple[dict[str, Any], bool]: ...

    def get(
        self,
        *,
        tenant_id: str,
        company_id: str,
        plan_id: str,
        plan_revision: int,
    ) -> dict[str, Any] | None: ...


class SqlAlchemyEosAllocationPlanRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock=None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def load_approval_context(
        self, *, tenant_id: str, approval_proof_id: str
    ) -> Mapping[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_approval_context(
                    session,
                    tenant_id=_scoped_id("tenant_id", tenant_id),
                    approval_proof_id=_uuid("approval_proof_id", approval_proof_id),
                )
        except EosAllocationPlanError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def release(
        self,
        candidate: Mapping[str, Any],
        *,
        approval_proof_id: str,
    ) -> tuple[dict[str, Any], bool]:
        try:
            with self._session_factory.begin() as session:
                context = _load_approval_context(
                    session,
                    tenant_id=candidate["tenant_id"],
                    approval_proof_id=approval_proof_id,
                )
                if context is None:
                    raise _conflict(
                        "Final BUSINESS_FORMAL approval proof was not found"
                    )
                _require_exact_approval(context, candidate)
                existing = _load_plan(
                    session,
                    tenant_id=candidate["tenant_id"],
                    company_id=candidate["company_id"],
                    plan_id=candidate["plan_id"],
                    plan_revision=candidate["plan_revision"],
                )
                if existing is not None:
                    if (
                        existing["plan_hash"] != candidate["plan_hash"]
                        or existing["approved_proof"] != context["approval_proof_ref"]
                    ):
                        raise _conflict(
                            "Allocation plan revision has different immutable semantics"
                        )
                    return (
                        _plan_projection(existing, _load_lines(session, existing)),
                        False,
                    )

                _require_next_revision(session, candidate)
                _require_company_and_project_scope(session, candidate)
                _require_basis_evidence(session, candidate)
                now = _aware_utc("clock", self._clock())
                record = {
                    key: candidate[key]
                    for key in (
                        "tenant_id",
                        "company_id",
                        "plan_id",
                        "plan_revision",
                        "source_kind",
                        "scope_type",
                        "basis_kind",
                        "rule_release_hash",
                        "basis_source_ref",
                        "basis_source_hash",
                        "effective_start",
                        "effective_end",
                        "plan_hash",
                    )
                }
                record.update(
                    approved_by=context["decided_by_id"],
                    approved_proof=context["approval_proof_ref"],
                    state="APPROVED",
                    created_at=now,
                )
                session.execute(
                    EOS_COST_ALLOCATION_PLAN_TABLE.insert().values(**record)
                )
                line_records = [
                    {
                        "tenant_id": candidate["tenant_id"],
                        "company_id": candidate["company_id"],
                        "plan_id": candidate["plan_id"],
                        "plan_revision": candidate["plan_revision"],
                        **line,
                    }
                    for line in candidate["lines"]
                ]
                session.execute(
                    EOS_COST_ALLOCATION_PLAN_LINE_TABLE.insert(), line_records
                )
                return _plan_projection(record, line_records), True
        except EosAllocationPlanError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "Allocation plan identity or immutable lineage already exists"
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get(
        self,
        *,
        tenant_id: str,
        company_id: str,
        plan_id: str,
        plan_revision: int,
    ) -> dict[str, Any] | None:
        identity = {
            "tenant_id": _scoped_id("tenant_id", tenant_id),
            "company_id": _uuid("company_id", company_id),
            "plan_id": _uuid("plan_id", plan_id),
            "plan_revision": _positive_int("plan_revision", plan_revision),
        }
        try:
            with self._session_factory() as session:
                record = _load_plan(session, **identity)
                if record is None:
                    return None
                return _plan_projection(record, _load_lines(session, record))
        except EosAllocationPlanError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


class EosAllocationPlanService:
    def __init__(
        self,
        *,
        repository: AllocationPlanRepository,
        authorization_source: AuthorizationSource,
    ) -> None:
        self._repository = repository
        self._authorization_source = authorization_source

    def release(
        self,
        *,
        tenant_id: str,
        company_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        proof_id, candidate = _admit_release(
            tenant_id=tenant_id,
            company_id=company_id,
            payload=payload,
        )
        context = self._repository.load_approval_context(
            tenant_id=candidate["tenant_id"], approval_proof_id=proof_id
        )
        if context is None:
            raise _conflict("Final BUSINESS_FORMAL approval proof was not found")
        _require_exact_approval(context, candidate)
        authorization_revision = self._fresh_authorization(
            tenant_id=candidate["tenant_id"], subject_id=context["decided_by_id"]
        )
        plan, created = self._repository.release(candidate, approval_proof_id=proof_id)
        return {
            **plan,
            "operation": ALLOCATION_PLAN_RELEASE_OPERATION,
            "idempotency_disposition": "CREATED" if created else "EXACT_REPLAY",
            "release_authorization_revision_hash": authorization_revision,
        }

    def get(
        self,
        *,
        tenant_id: str,
        company_id: str,
        plan_id: str,
        plan_revision: int,
    ) -> dict[str, Any]:
        plan = self._repository.get(
            tenant_id=tenant_id,
            company_id=company_id,
            plan_id=plan_id,
            plan_revision=plan_revision,
        )
        if plan is None:
            raise EosAllocationPlanError(
                "EOS_COST_ALLOCATION_PLAN_NOT_FOUND",
                "Allocation plan revision was not found in tenant and company scope",
                status_code=404,
            )
        return {
            **plan,
            "operation": ALLOCATION_PLAN_GET_OPERATION,
            "idempotency_disposition": "EXACT_REPLAY",
            "release_authorization_revision_hash": None,
        }

    def _fresh_authorization(self, *, tenant_id: str, subject_id: str) -> str:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id, subject_id=subject_id
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied("OA denied the current allocation plan approver") from exc
        except Exception as exc:
            raise _unavailable("OA effective authorization is unavailable") from exc
        if (
            not isinstance(value, Mapping)
            or value.get("active") is not True
            or value.get("tenant_id") != tenant_id
            or value.get("subject_id") != subject_id
        ):
            raise _denied("Active OA allocation plan authority is required")
        scopes = value.get("scopes")
        if isinstance(scopes, (str, bytes)) or not isinstance(scopes, Sequence):
            raise _denied("OA allocation plan authority is malformed")
        if ALLOCATION_PLAN_APPROVE_SCOPE not in scopes:
            raise _denied("Current allocation plan approval scope is required")
        return _bare_revision_hash(value.get("revision_hash"))


def _admit_release(
    *, tenant_id: str, company_id: str, payload: Mapping[str, Any]
) -> tuple[str, dict[str, Any]]:
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "approval_proof_id",
        "plan",
    }:
        raise _invalid("payload", "must contain only canonical release fields")
    if payload.get("schema_version") != "eos_cost_allocation_plan_release.v1":
        raise _invalid("schema_version", "is not supported")
    plan = payload.get("plan")
    if not isinstance(plan, Mapping) or set(plan) != {
        "plan_id",
        "plan_revision",
        "source_kind",
        "scope_type",
        "basis_kind",
        "rule_release_hash",
        "basis_source_ref",
        "basis_source_hash",
        "effective_start",
        "effective_end",
        "lines",
    }:
        raise _invalid("plan", "must contain only canonical allocation fields")
    lines = _admit_lines(plan.get("lines"))
    effective_start = _date_value("effective_start", plan.get("effective_start"))
    effective_end = _optional_date("effective_end", plan.get("effective_end"))
    if effective_end is not None and effective_end < effective_start:
        raise _invalid("effective_end", "cannot precede effective_start")
    candidate = {
        "tenant_id": _scoped_id("tenant_id", tenant_id),
        "company_id": _uuid("company_id", company_id),
        "plan_id": _uuid("plan_id", plan.get("plan_id")),
        "plan_revision": _positive_int("plan_revision", plan.get("plan_revision")),
        "source_kind": _choice(
            "source_kind", plan.get("source_kind"), COST_SOURCE_KINDS
        ),
        "scope_type": _choice(
            "scope_type", plan.get("scope_type"), ALLOCATION_SCOPE_TYPES
        ),
        "basis_kind": _choice(
            "basis_kind", plan.get("basis_kind"), ALLOCATION_BASIS_KINDS
        ),
        "rule_release_hash": _hash_ref(
            "rule_release_hash", plan.get("rule_release_hash")
        ),
        "basis_source_ref": _text(
            "basis_source_ref", plan.get("basis_source_ref"), 256
        ),
        "basis_source_hash": _hash_ref(
            "basis_source_hash", plan.get("basis_source_hash")
        ),
        "effective_start": effective_start,
        "effective_end": effective_end,
        "lines": lines,
    }
    if candidate["scope_type"] == "PROJECT" and len(lines) != 1:
        raise _invalid("scope_type", "PROJECT scope requires exactly one line")
    candidate["plan_hash"] = semantic_sha256_hash_ref(
        {
            "domain": "EOS-COST-ALLOCATION-PLAN-V1",
            **{
                key: _wire_value(value)
                for key, value in candidate.items()
                if key != "lines"
            },
            "lines": [
                {key: _wire_value(value) for key, value in line.items()}
                for line in lines
            ],
        }
    )
    return _uuid("approval_proof_id", payload.get("approval_proof_id")), candidate


def _admit_lines(value: object) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise _invalid("lines", "must be a non-empty sequence")
    lines: list[dict[str, Any]] = []
    expected_fields = {
        "line_no",
        "project_id",
        "project_code",
        "work_code",
        "basis_units",
        "allocation_ratio",
        "eligibility_hash",
        "confidentiality_class",
    }
    for item in value:
        if not isinstance(item, Mapping) or set(item) != expected_fields:
            raise _invalid("lines", "contains a non-canonical line")
        project_code = str(item.get("project_code", ""))
        if _PROJECT_CODE.fullmatch(project_code) is None:
            raise _invalid("project_code", "has an invalid approved code")
        work_code = item.get("work_code")
        if work_code is not None and (
            not isinstance(work_code, str) or _WORK_CODE.fullmatch(work_code) is None
        ):
            raise _invalid("work_code", "has an invalid FL code")
        basis_units = _positive_decimal(
            "basis_units", item.get("basis_units"), Decimal("0.00000001")
        )
        ratio = _positive_decimal(
            "allocation_ratio", item.get("allocation_ratio"), Decimal("0.000000000001")
        )
        if ratio > 1:
            raise _invalid("allocation_ratio", "must not exceed one")
        line = {
            "line_no": _positive_int("line_no", item.get("line_no")),
            "project_id": _uuid("project_id", item.get("project_id")),
            "project_code": project_code,
            "work_code": work_code,
            "basis_units": basis_units,
            "allocation_ratio": ratio,
            "eligibility_hash": _hash_ref(
                "eligibility_hash", item.get("eligibility_hash")
            ),
            "confidentiality_class": _choice(
                "confidentiality_class",
                item.get("confidentiality_class"),
                ALLOCATION_CONFIDENTIALITY_CLASSES,
            ),
        }
        line["line_hash"] = semantic_sha256_hash_ref(
            {
                "domain": "EOS-COST-ALLOCATION-PLAN-LINE-V1",
                **{key: _wire_value(item) for key, item in line.items()},
            }
        )
        lines.append(line)
    if [line["line_no"] for line in lines] != list(range(1, len(lines) + 1)):
        raise _invalid("line_no", "must be contiguous and ordered from one")
    if len({line["project_id"] for line in lines}) != len(lines):
        raise _invalid("lines", "must not repeat a target Project")
    ratio_total = sum((line["allocation_ratio"] for line in lines), Decimal(0))
    if ratio_total != Decimal(1):
        raise _invalid("allocation_ratio", "line ratios must total exactly one")
    return lines


def _load_approval_context(
    session: Session, *, tenant_id: str, approval_proof_id: str
) -> dict[str, Any] | None:
    proof = EOS_APPROVAL_PROOF_TABLE
    instance = EOS_APPROVAL_INSTANCE_TABLE
    decision = EOS_APPROVAL_DECISION_TABLE
    row = (
        session.execute(
            select(
                proof.c.approval_proof_id,
                proof.c.approval_instance_id,
                proof.c.business_operation_id,
                proof.c.approval_domain,
                proof.c.protected_operation_ref,
                proof.c.payload_hash,
                proof.c.policy_hash,
                proof.c.proof_hash,
                instance.c.state.label("instance_state"),
                instance.c.operation,
                instance.c.payload_hash.label("instance_payload_hash"),
                instance.c.policy_hash.label("instance_policy_hash"),
                instance.c.business_operation_id.label("instance_operation_id"),
                decision.c.decision,
                decision.c.authorized_by_oa,
                decision.c.decided_by_id,
                decision.c.authorization_revision_hash,
            )
            .select_from(
                proof.join(
                    instance,
                    (proof.c.tenant_id == instance.c.tenant_id)
                    & (proof.c.approval_instance_id == instance.c.approval_instance_id),
                ).join(
                    decision,
                    (proof.c.tenant_id == decision.c.tenant_id)
                    & (proof.c.final_wc_decision_id == decision.c.wc_decision_id),
                )
            )
            .where(
                proof.c.tenant_id == tenant_id,
                proof.c.approval_proof_id == approval_proof_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return {
        **dict(row),
        "approval_proof_ref": f"eos.approval-proof:{row['approval_proof_id']}",
    }


def _require_exact_approval(
    context: Mapping[str, Any], candidate: Mapping[str, Any]
) -> None:
    expected_ref = (
        f"eos.cost-allocation-plan:{candidate['plan_id']}:"
        f"revision:{candidate['plan_revision']}"
    )
    if (
        context["approval_domain"] != "BUSINESS_FORMAL"
        or context["instance_state"] != "APPROVED"
        or context["decision"] != "APPROVE"
        or context["authorized_by_oa"] is not True
    ):
        raise _conflict("Approval proof is not a final authorized approval")
    if (
        context["payload_hash"] != candidate["plan_hash"]
        or context["instance_payload_hash"] != candidate["plan_hash"]
        or context["operation"] != ALLOCATION_PLAN_RELEASE_OPERATION
        or context["protected_operation_ref"] != expected_ref
        or context["policy_hash"] != context["instance_policy_hash"]
        or context["business_operation_id"] != context["instance_operation_id"]
    ):
        raise EosAllocationPlanError(
            "EOS_COST_ALLOCATION_PLAN_PROOF_MISMATCH",
            "Approval proof does not bind the exact allocation plan revision",
            status_code=409,
        )


def _require_next_revision(session: Session, candidate: Mapping[str, Any]) -> None:
    maximum = session.scalar(
        select(func.max(EOS_COST_ALLOCATION_PLAN_TABLE.c.plan_revision)).where(
            EOS_COST_ALLOCATION_PLAN_TABLE.c.tenant_id == candidate["tenant_id"],
            EOS_COST_ALLOCATION_PLAN_TABLE.c.company_id == candidate["company_id"],
            EOS_COST_ALLOCATION_PLAN_TABLE.c.plan_id == candidate["plan_id"],
        )
    )
    expected = 1 if maximum is None else int(maximum) + 1
    if candidate["plan_revision"] != expected:
        raise _conflict(
            f"Allocation plan revision must be the next immutable revision {expected}"
        )


def _require_company_and_project_scope(
    session: Session, candidate: Mapping[str, Any]
) -> None:
    company = (
        session.execute(
            select(EOS_LEGAL_ENTITY_TABLE).where(
                EOS_LEGAL_ENTITY_TABLE.c.tenant_id == candidate["tenant_id"],
                EOS_LEGAL_ENTITY_TABLE.c.company_id == candidate["company_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if company is None:
        raise _not_found("LegalEntity was not found in tenant scope")
    if (
        company["status"] != "ACTIVE"
        or company["effective_from"] > candidate["effective_start"]
    ):
        raise _conflict("LegalEntity is not active for the plan effective period")
    for line in candidate["lines"]:
        project = (
            session.execute(
                select(
                    EOS_PROJECT_TABLE.c.project_code, EOS_PROJECT_TABLE.c.status
                ).where(
                    EOS_PROJECT_TABLE.c.tenant_id == candidate["tenant_id"],
                    EOS_PROJECT_TABLE.c.project_id == line["project_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if project is None:
            raise _not_found("Allocation target Project was not found")
        if project["project_code"] != line["project_code"]:
            raise _conflict("Allocation target Project code differs from authority")
        if project["status"] not in {"ACTIVE", "CLOSING"}:
            raise _conflict("Allocation target Project is not financially active")
        binding = session.scalar(
            select(EOS_PROJECT_COMPANY_BINDING_TABLE.c.binding_id).where(
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.tenant_id == candidate["tenant_id"],
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.project_id == line["project_id"],
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.company_id
                == candidate["company_id"],
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.state == "APPROVED",
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_from
                <= candidate["effective_start"],
                (
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until.is_(None)
                    | (
                        EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until
                        >= (candidate["effective_end"] or candidate["effective_start"])
                    )
                ),
            )
        )
        if binding is None:
            raise _conflict(
                "Allocation target Project lacks an effective company binding"
            )


def _require_basis_evidence(session: Session, candidate: Mapping[str, Any]) -> None:
    if candidate["basis_kind"] != "APPROVED_PLAN":
        return
    assignment_hashes: list[str] = []
    for line in candidate["lines"]:
        if line["work_code"] is None:
            raise _conflict("APPROVED_PLAN basis requires a WorkCode on every line")
        rows = list(
            session.execute(
                select(
                    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.planned_man_days,
                    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.assignment_hash,
                ).where(
                    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.tenant_id
                    == candidate["tenant_id"],
                    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.project_id
                    == line["project_id"],
                    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.work_code_id
                    == line["work_code"],
                    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_from
                    <= candidate["effective_start"],
                    (
                        EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_until.is_(None)
                        | (
                            EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_until
                            >= (
                                candidate["effective_end"]
                                or candidate["effective_start"]
                            )
                        )
                    ),
                )
            ).mappings()
        )
        if not rows:
            raise _conflict("APPROVED_PLAN basis lacks an effective WorkAssignment")
        total = sum((Decimal(str(row["planned_man_days"])) for row in rows), Decimal())
        if total != line["basis_units"]:
            raise _conflict(
                "APPROVED_PLAN basis units differ from effective WorkAssignments"
            )
        assignment_hashes.extend(str(row["assignment_hash"]) for row in rows)
    observed_hash = semantic_sha256_hash_ref(
        {
            "domain": "EOS-COST-ALLOCATION-APPROVED-PLAN-BASIS-V1",
            "assignment_hashes": sorted(assignment_hashes),
        }
    )
    if observed_hash != candidate["basis_source_hash"]:
        raise _conflict(
            "APPROVED_PLAN basis source hash differs from effective WorkAssignments"
        )


def _load_plan(session: Session, **identity: Any) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_COST_ALLOCATION_PLAN_TABLE).where(
                EOS_COST_ALLOCATION_PLAN_TABLE.c.tenant_id == identity["tenant_id"],
                EOS_COST_ALLOCATION_PLAN_TABLE.c.company_id == identity["company_id"],
                EOS_COST_ALLOCATION_PLAN_TABLE.c.plan_id == identity["plan_id"],
                EOS_COST_ALLOCATION_PLAN_TABLE.c.plan_revision
                == identity["plan_revision"],
            )
        )
        .mappings()
        .one_or_none()
    )


def _load_lines(session: Session, record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list(
        session.execute(
            select(EOS_COST_ALLOCATION_PLAN_LINE_TABLE)
            .where(
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.tenant_id == record["tenant_id"],
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.company_id
                == record["company_id"],
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.plan_id == record["plan_id"],
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.plan_revision
                == record["plan_revision"],
            )
            .order_by(EOS_COST_ALLOCATION_PLAN_LINE_TABLE.c.line_no)
        ).mappings()
    )


def _plan_projection(
    record: Mapping[str, Any], lines: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "schema_version": ALLOCATION_PLAN_SCHEMA,
        **{
            key: _wire_value(record[key])
            for key in (
                "tenant_id",
                "company_id",
                "plan_id",
                "plan_revision",
                "source_kind",
                "scope_type",
                "basis_kind",
                "rule_release_hash",
                "basis_source_ref",
                "basis_source_hash",
                "effective_start",
                "effective_end",
                "approved_by",
                "approved_proof",
                "state",
                "plan_hash",
                "created_at",
            )
        },
        "basis_priority": _BASIS_PRIORITY[record["basis_kind"]],
        "lines": [
            {
                key: _wire_value(line[key])
                for key in (
                    "line_no",
                    "project_id",
                    "project_code",
                    "work_code",
                    "basis_units",
                    "allocation_ratio",
                    "eligibility_hash",
                    "confidentiality_class",
                    "line_hash",
                )
            }
            for line in lines
        ],
    }


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field, "must be a UUID") from exc


def _scoped_id(field: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise _invalid(field, "has an invalid format")
    return value


def _text(field: str, value: object, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise _invalid(field, f"must be non-empty and at most {limit} characters")
    return value


def _choice(field: str, value: object, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _invalid(field, "contains an unsupported value")
    return value


def _hash_ref(field: str, value: object) -> str:
    if not isinstance(value, str) or _HASH_REF.fullmatch(value) is None:
        raise _invalid(field, "must be a sha256 hash reference")
    return value


def _bare_revision_hash(value: object) -> str:
    if not isinstance(value, str):
        raise _denied("OA authorization revision hash is missing")
    bare = value.removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", bare) is None:
        raise _denied("OA authorization revision hash is malformed")
    return bare


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _invalid(field, "must be a positive integer")
    return value


def _positive_decimal(field: str, value: object, quantum: Decimal) -> Decimal:
    try:
        number = Decimal(str(value)).quantize(quantum)
    except (InvalidOperation, ValueError) as exc:
        raise _invalid(field, "must be a finite decimal") from exc
    if not number.is_finite() or number <= 0:
        raise _invalid(field, "must be greater than zero")
    return number


def _date_value(field: str, value: object) -> date:
    if not isinstance(value, str):
        raise _invalid(field, "must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _invalid(field, "must be an ISO date") from exc


def _optional_date(field: str, value: object) -> date | None:
    return None if value is None else _date_value(field, value)


def _aware_utc(field: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EosAllocationPlanError(
            "EOS_COST_ALLOCATION_PLAN_CLOCK_INVALID",
            f"{field} must be a timezone-aware datetime",
            status_code=500,
        )
    return value.astimezone(UTC)


def _wire_value(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _invalid(field: str, detail: str) -> EosAllocationPlanError:
    return EosAllocationPlanError(
        "EOS_COST_ALLOCATION_PLAN_INVALID",
        f"{field} {detail}",
        status_code=422,
    )


def _not_found(detail: str) -> EosAllocationPlanError:
    return EosAllocationPlanError(
        "EOS_COST_ALLOCATION_PLAN_REFERENCE_NOT_FOUND",
        detail,
        status_code=404,
    )


def _conflict(detail: str) -> EosAllocationPlanError:
    return EosAllocationPlanError(
        "EOS_COST_ALLOCATION_PLAN_CONFLICT",
        detail,
        status_code=409,
    )


def _denied(detail: str) -> EosAllocationPlanError:
    return EosAllocationPlanError(
        "EOS_COST_ALLOCATION_PLAN_AUTHORIZATION_DENIED",
        detail,
        status_code=403,
    )


def _unavailable(
    detail: str = "Allocation plan persistence is unavailable",
) -> EosAllocationPlanError:
    return EosAllocationPlanError(
        "EOS_COST_ALLOCATION_PLAN_UNAVAILABLE",
        detail,
        status_code=503,
        retryable=True,
    )
