from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nex_runtime import DEFAULT_OPERATION_REGISTRY, OperationNameError
from nex_runtime.semantic_hashes import (
    nsl_write_payload_hash_ref,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    or_,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_transactions import (
    EOS_METADATA,
    EosBusinessOperationError,
    EosBusinessOperationRequest,
    EosBusinessTransactionCoordinator,
)
from .project_memberships import EOS_PROJECT_MEMBER_TABLE
from .project_authorization import (
    EosProjectAuthorizationError,
    EosProjectAuthorizationGate,
)
from .project_work_codes import (
    EOS_PROJECT_WORK_CODE_ENTRY_TABLE,
    EOS_PROJECT_WORK_CODE_SET_TABLE,
)
from .projects import EOS_PROJECT_TABLE
from .voucher_commands import EosServiceCaller

PROJECT_WORK_ASSIGNMENT_ASSIGN_OPERATION = "PROJECT.WORK_ASSIGNMENT.ASSIGN"
PROJECT_WORK_ASSIGNMENT_LIST_OPERATION = "PROJECT.WORK_ASSIGNMENT.LIST"
PROJECT_WORK_ASSIGNMENT_MANAGE_SCOPE = "project:work-assignment:manage"
PROJECT_WORK_ASSIGNMENT_READ_SCOPE = "project:work-assignment:read"
PROJECT_WORK_ASSIGNMENT_PERFORM_SCOPE = "project:work-assignment:perform"
PROJECT_ADMIN_SCOPE = "project:project:admin"

PROJECT_WORK_ASSIGNMENT_PERFORMER_KINDS = frozenset({"HUMAN", "AGENT"})
PROJECT_WORK_ASSIGNMENT_SCOPES = frozenset({"EXECUTE", "REVIEW", "REPORT"})
PRIVATE_PAYROLL_FIELDS = frozenset(
    {
        "actual_day_rate",
        "actual_payroll_cost",
        "actual_salary",
        "compensation",
        "employee_salary",
        "payroll_amount",
        "salary",
    }
)

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_REVISION_HASH = re.compile(r"^[0-9a-f]{64}$")
_ASSIGNMENT_FIELDS = frozenset(
    {
        "assignment_id",
        "work_set_id",
        "work_set_revision",
        "work_code_id",
        "performer_kind",
        "subject_ref",
        "assignment_scope",
        "planned_man_days",
        "planned_grade_id",
        "grade_policy_ref",
        "grade_policy_hash",
        "valid_from",
        "valid_until",
        "approved_proof_hash",
    }
)

EOS_PROJECT_WORK_ASSIGNMENT_TABLE = Table(
    "eos_project_work_assignment",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("assignment_id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("work_set_id", Uuid(as_uuid=False), nullable=False),
    Column("work_set_revision", Integer, nullable=False),
    Column("work_code_id", String(16), nullable=False),
    Column("performer_kind", String(16), nullable=False),
    Column("subject_ref", String(128), nullable=False),
    Column("performer_authority_hash", String(71), nullable=False),
    Column("assignment_scope", String(16), nullable=False),
    Column("planned_man_days", Numeric(12, 4), nullable=False),
    Column("planned_grade_id", String(64), nullable=False),
    Column("grade_policy_ref", String(256), nullable=False),
    Column("grade_policy_hash", String(71), nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_until", Date, nullable=True),
    Column("approved_proof_hash", String(71), nullable=False),
    Column("approved_by_subject_id", String(128), nullable=False),
    Column("assignment_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        (
            "tenant_id",
            "project_id",
            "work_set_id",
            "work_set_revision",
            "work_code_id",
        ),
        (
            "eos_project_work_code_entry.tenant_id",
            "eos_project_work_code_entry.project_id",
            "eos_project_work_code_entry.work_set_id",
            "eos_project_work_code_entry.work_set_revision",
            "eos_project_work_code_entry.work_code_id",
        ),
        name="fk_eos_project_assignment_code",
    ),
    UniqueConstraint(
        "tenant_id",
        "assignment_hash",
        name="ux_eos_project_assignment_hash",
    ),
    CheckConstraint("work_set_revision > 0", name="ck_eos_project_assignment_revision"),
    CheckConstraint(
        "performer_kind IN ('HUMAN', 'AGENT')",
        name="ck_eos_project_assignment_performer",
    ),
    CheckConstraint(
        "assignment_scope IN ('EXECUTE', 'REVIEW', 'REPORT')",
        name="ck_eos_project_assignment_scope",
    ),
    CheckConstraint("planned_man_days > 0", name="ck_eos_project_assignment_man_days"),
    CheckConstraint(
        "valid_until IS NULL OR valid_until >= valid_from",
        name="ck_eos_project_assignment_period",
    ),
)
Index(
    "ix_eos_project_assignment_project",
    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.tenant_id,
    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.project_id,
    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_from,
    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_until,
    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.work_code_id,
)
Index(
    "ix_eos_project_assignment_subject",
    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.tenant_id,
    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.subject_ref,
    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.performer_kind,
    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_from,
    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_until,
)


class EosProjectWorkAssignmentError(RuntimeError):
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


@dataclass(frozen=True)
class ProjectWorkAssignmentInput:
    tenant_id: str
    assignment_id: str
    project_id: str
    work_set_id: str
    work_set_revision: int
    work_code_id: str
    performer_kind: str
    subject_ref: str
    performer_authority_hash: str
    assignment_scope: str
    planned_man_days: Decimal
    planned_grade_id: str
    grade_policy_ref: str
    grade_policy_hash: str
    valid_from: date
    valid_until: date | None
    approved_proof_hash: str
    approved_by_subject_id: str


class SqlAlchemyEosProjectWorkAssignmentRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def assign_in_session(
        self, session: Session, value: ProjectWorkAssignmentInput
    ) -> dict[str, Any]:
        record = _assignment_record(value)
        existing = (
            session.execute(
                select(EOS_PROJECT_WORK_ASSIGNMENT_TABLE).where(
                    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.tenant_id
                    == record["tenant_id"],
                    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.assignment_id
                    == record["assignment_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            if _assignment_semantics(existing) == _assignment_semantics(record):
                return _assignment_projection(existing)
            raise _conflict("WorkAssignment identity has different semantics")

        project = (
            session.execute(
                select(EOS_PROJECT_TABLE)
                .where(
                    EOS_PROJECT_TABLE.c.tenant_id == record["tenant_id"],
                    EOS_PROJECT_TABLE.c.project_id == record["project_id"],
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if project is None:
            raise _not_found("Project was not found in tenant scope")
        if project["status"] != "ACTIVE":
            raise _conflict("Project must be technically ACTIVE")

        work_set = (
            session.execute(
                select(EOS_PROJECT_WORK_CODE_SET_TABLE).where(
                    EOS_PROJECT_WORK_CODE_SET_TABLE.c.tenant_id == record["tenant_id"],
                    EOS_PROJECT_WORK_CODE_SET_TABLE.c.project_id
                    == record["project_id"],
                    EOS_PROJECT_WORK_CODE_SET_TABLE.c.work_set_id
                    == record["work_set_id"],
                    EOS_PROJECT_WORK_CODE_SET_TABLE.c.revision
                    == record["work_set_revision"],
                    EOS_PROJECT_WORK_CODE_SET_TABLE.c.state == "APPROVED",
                    EOS_PROJECT_WORK_CODE_SET_TABLE.c.effective_from
                    <= record["valid_from"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if work_set is None:
            raise _conflict("An effective approved WorkCodeSet revision is required")
        code_exists = session.execute(
            select(EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.work_code_id).where(
                EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.tenant_id == record["tenant_id"],
                EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.project_id == record["project_id"],
                EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.work_set_id
                == record["work_set_id"],
                EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.work_set_revision
                == record["work_set_revision"],
                EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.work_code_id
                == record["work_code_id"],
            )
        ).scalar_one_or_none()
        if code_exists is None:
            raise _conflict("Work code is not admitted by the selected WorkCodeSet")

        if record["performer_kind"] == "HUMAN":
            self._require_human_performer(session, record)
        elif record["subject_ref"] != work_set["pa_agent_id"]:
            raise _denied("Agent performer must be the WorkCodeSet PA identity")

        overlap = session.execute(
            select(EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.assignment_id).where(
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.tenant_id == record["tenant_id"],
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.project_id == record["project_id"],
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.performer_kind
                == record["performer_kind"],
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.subject_ref
                == record["subject_ref"],
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.work_code_id
                == record["work_code_id"],
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_from
                <= (record["valid_until"] or date.max),
                or_(
                    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_until.is_(None),
                    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_until
                    >= record["valid_from"],
                ),
            )
        ).scalar_one_or_none()
        if overlap is not None:
            raise _conflict("Overlapping performer WorkAssignment is not allowed")

        session.execute(EOS_PROJECT_WORK_ASSIGNMENT_TABLE.insert().values(**record))
        return _assignment_projection(record)

    def assign(self, value: ProjectWorkAssignmentInput) -> dict[str, Any]:
        try:
            with self._session_factory.begin() as session:
                return self.assign_in_session(session, value)
        except EosProjectWorkAssignmentError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "WorkAssignment violates an identity or overlap guard"
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def list_for_project(
        self,
        *,
        tenant_id: str,
        project_id: str,
        effective_on: date | None = None,
        work_code_id: str | None = None,
    ) -> list[dict[str, Any]]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        statement = select(EOS_PROJECT_WORK_ASSIGNMENT_TABLE).where(
            EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.tenant_id == tenant_id,
            EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.project_id == project_id,
        )
        if effective_on is not None:
            effective_on = _date("effective_on", effective_on)
            statement = statement.where(
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_from <= effective_on,
                or_(
                    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_until.is_(None),
                    EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_until >= effective_on,
                ),
            )
        if work_code_id is not None:
            statement = statement.where(
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.work_code_id
                == _work_code("work_code_id", work_code_id)
            )
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        statement.order_by(
                            EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.work_code_id,
                            EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.valid_from,
                            EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.subject_ref,
                            EOS_PROJECT_WORK_ASSIGNMENT_TABLE.c.assignment_id,
                        )
                    )
                    .mappings()
                    .all()
                )
            return [_assignment_projection(row) for row in rows]
        except EosProjectWorkAssignmentError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    @staticmethod
    def require_project_role(
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
        roles: frozenset[str] | None = None,
    ) -> None:
        role = session.execute(
            select(EOS_PROJECT_MEMBER_TABLE.c.member_role).where(
                EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_MEMBER_TABLE.c.project_id == project_id,
                EOS_PROJECT_MEMBER_TABLE.c.subject_id == subject_id,
                EOS_PROJECT_MEMBER_TABLE.c.status == "ACTIVE",
            )
        ).scalar_one_or_none()
        if role is None or (roles is not None and role not in roles):
            raise _denied("An active authorized Project membership is required")

    @staticmethod
    def _require_human_performer(session: Session, record: Mapping[str, Any]) -> None:
        member = (
            session.execute(
                select(EOS_PROJECT_MEMBER_TABLE).where(
                    EOS_PROJECT_MEMBER_TABLE.c.tenant_id == record["tenant_id"],
                    EOS_PROJECT_MEMBER_TABLE.c.project_id == record["project_id"],
                    EOS_PROJECT_MEMBER_TABLE.c.subject_id == record["subject_ref"],
                    EOS_PROJECT_MEMBER_TABLE.c.status == "ACTIVE",
                )
            )
            .mappings()
            .one_or_none()
        )
        if member is None or member["member_role"] == "VIEWER":
            raise _denied("Human performer requires an active non-viewer membership")
        valid_from = member["valid_from"]
        if (
            isinstance(valid_from, datetime)
            and valid_from.date() > record["valid_from"]
        ):
            raise _denied("Human membership is not effective on assignment start")


class EosProjectWorkAssignmentService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        coordinator: EosBusinessTransactionCoordinator,
        authorization_source: AuthorizationSource,
        project_authorizer: EosProjectAuthorizationGate | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._coordinator = coordinator
        self._authorization_source = authorization_source
        self._project_authorizer = project_authorizer
        self._repository = SqlAlchemyEosProjectWorkAssignmentRepository(session_factory)

    def assign(
        self, payload: Mapping[str, Any], *, caller: EosServiceCaller
    ) -> dict[str, Any]:
        _require_service_caller(caller)
        envelope = _write_envelope(payload)
        requester = _scoped_id(
            "requester_subject_id", payload.get("requester_subject_id")
        )
        project_id = _uuid("project_id", payload.get("project_id"))
        assignment = _assignment_payload(payload.get("assignment"))
        requester_authorization = self._authorize(
            tenant_id=envelope["tenant_id"],
            subject_id=requester,
            required_scope=PROJECT_WORK_ASSIGNMENT_MANAGE_SCOPE,
            project_id=project_id,
        )
        performer_kind = _choice(
            "performer_kind",
            assignment.get("performer_kind"),
            PROJECT_WORK_ASSIGNMENT_PERFORMER_KINDS,
        )
        subject_ref = _scoped_id("subject_ref", assignment.get("subject_ref"))
        performer_authority_hash = (
            self._human_performer_authority(
                tenant_id=envelope["tenant_id"],
                subject_id=subject_ref,
                project_id=project_id,
            )
            if performer_kind == "HUMAN"
            else _hash_ref(
                "performer_authority_hash",
                self._agent_authority_hash(
                    tenant_id=envelope["tenant_id"],
                    project_id=project_id,
                    subject_ref=subject_ref,
                    work_set_id=assignment.get("work_set_id"),
                    work_set_revision=assignment.get("work_set_revision"),
                ),
            )
        )
        value = ProjectWorkAssignmentInput(
            tenant_id=envelope["tenant_id"],
            assignment_id=assignment.get("assignment_id"),
            project_id=project_id,
            work_set_id=assignment.get("work_set_id"),
            work_set_revision=assignment.get("work_set_revision"),
            work_code_id=assignment.get("work_code_id"),
            performer_kind=performer_kind,
            subject_ref=subject_ref,
            performer_authority_hash=performer_authority_hash,
            assignment_scope=assignment.get("assignment_scope"),
            planned_man_days=assignment.get("planned_man_days"),
            planned_grade_id=assignment.get("planned_grade_id"),
            grade_policy_ref=assignment.get("grade_policy_ref"),
            grade_policy_hash=assignment.get("grade_policy_hash"),
            valid_from=_date_input("valid_from", assignment.get("valid_from")),
            valid_until=_optional_date_input(
                "valid_until", assignment.get("valid_until")
            ),
            approved_proof_hash=assignment.get("approved_proof_hash"),
            approved_by_subject_id=requester,
        )

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise RuntimeError("WorkAssignment requires a database transaction")
            self._repository.require_project_role(
                session,
                tenant_id=envelope["tenant_id"],
                project_id=project_id,
                subject_id=requester,
                roles=frozenset({"OWNER", "MANAGER"}),
            )
            created = self._repository.assign_in_session(session, value)
            return {
                "business_result_ref": (
                    f"eos.project-work-assignment:{created['assignment_id']}"
                ),
                "work_assignment": created,
                "authorization_revision_hash": requester_authorization["revision_hash"],
            }

        requested_operation = envelope.pop("requested_operation")

        def admitted_mutation(session: Session | None) -> Mapping[str, Any]:
            try:
                return {
                    **mutation(session),
                    "requested_operation": requested_operation,
                    "canonical_operation": PROJECT_WORK_ASSIGNMENT_ASSIGN_OPERATION,
                }
            except EosProjectWorkAssignmentError as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc

        try:
            result = self._coordinator.execute(
                EosBusinessOperationRequest(**envelope), admitted_mutation
            )
        except EosBusinessOperationError as exc:
            raise EosProjectWorkAssignmentError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        return result.to_public_projection()

    def list_assignments(
        self,
        *,
        tenant_id: str,
        project_id: str,
        requester_subject_id: str,
        effective_on: date | None = None,
        work_code_id: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        requester = _scoped_id("requester_subject_id", requester_subject_id)
        authorization = self._authorize(
            tenant_id=tenant_id,
            subject_id=requester,
            required_scope=PROJECT_WORK_ASSIGNMENT_READ_SCOPE,
            project_id=project_id,
        )
        if PROJECT_ADMIN_SCOPE not in authorization["scopes"]:
            try:
                with self._session_factory() as session:
                    self._repository.require_project_role(
                        session,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        subject_id=requester,
                    )
            except EosProjectWorkAssignmentError:
                raise
            except SQLAlchemyError as exc:
                raise _unavailable() from exc
        items = self._repository.list_for_project(
            tenant_id=tenant_id,
            project_id=project_id,
            effective_on=effective_on,
            work_code_id=work_code_id,
        )
        return {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "effective_on": effective_on.isoformat() if effective_on else None,
            "work_code_id": work_code_id,
            "items": items,
            "count": len(items),
            "data_classification": "INTERNAL_PLANNING",
            "private_payroll_excluded": True,
        }

    def _authorize(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        required_scope: str,
        project_id: str,
    ) -> dict[str, Any]:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id, subject_id=subject_id
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied(f"Current {required_scope} authorization was denied") from exc
        except Exception as exc:
            raise EosProjectWorkAssignmentError(
                "EOS_PROJECT_WORK_ASSIGNMENT_AUTHORIZATION_UNAVAILABLE",
                "OA effective authorization is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        admitted = _admit_authorization(
            value,
            tenant_id=tenant_id,
            subject_id=subject_id,
            required_scope=required_scope,
            project_id=project_id,
        )
        if (
            self._project_authorizer is not None
            and required_scope
            in {
                PROJECT_WORK_ASSIGNMENT_MANAGE_SCOPE,
                PROJECT_WORK_ASSIGNMENT_PERFORM_SCOPE,
            }
        ):
            try:
                self._project_authorizer.authorize(
                    tenant_id=tenant_id,
                    subject_id=subject_id,
                    project_id=project_id,
                    action=required_scope,
                    correlation_id=f"eos-work-assignment:{subject_id}:{project_id}",
                )
            except EosProjectAuthorizationError as exc:
                raise EosProjectWorkAssignmentError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc
        return admitted

    def _human_performer_authority(
        self, *, tenant_id: str, subject_id: str, project_id: str
    ) -> str:
        authorization = self._authorize(
            tenant_id=tenant_id,
            subject_id=subject_id,
            required_scope=PROJECT_WORK_ASSIGNMENT_PERFORM_SCOPE,
            project_id=project_id,
        )
        return "sha256:" + authorization["revision_hash"]

    def _agent_authority_hash(
        self,
        *,
        tenant_id: str,
        project_id: str,
        subject_ref: str,
        work_set_id: object,
        work_set_revision: object,
    ) -> str:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        select(
                            EOS_PROJECT_WORK_CODE_SET_TABLE.c.pa_agent_id,
                            EOS_PROJECT_WORK_CODE_SET_TABLE.c.pa_identity_evidence_hash,
                        ).where(
                            EOS_PROJECT_WORK_CODE_SET_TABLE.c.tenant_id == tenant_id,
                            EOS_PROJECT_WORK_CODE_SET_TABLE.c.project_id == project_id,
                            EOS_PROJECT_WORK_CODE_SET_TABLE.c.work_set_id
                            == _uuid("work_set_id", work_set_id),
                            EOS_PROJECT_WORK_CODE_SET_TABLE.c.revision
                            == _positive_int("work_set_revision", work_set_revision),
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except EosProjectWorkAssignmentError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        if row is None or row["pa_agent_id"] != subject_ref:
            raise _denied("Agent performer must match the admitted PA identity")
        return row["pa_identity_evidence_hash"]


def project_work_assignment_payload_hash(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise _invalid("payload must be an object")
    projected = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "business_operation_id",
            "idempotency_key",
            "payload_hash",
            "requested_operation",
            "trace",
        }
    }
    return nsl_write_payload_hash_ref(
        {"operation": PROJECT_WORK_ASSIGNMENT_ASSIGN_OPERATION, **projected}
    )


def _write_envelope(payload: Mapping[str, Any]) -> dict[str, str]:
    requested = payload.get(
        "requested_operation", PROJECT_WORK_ASSIGNMENT_ASSIGN_OPERATION
    )
    try:
        resolution = DEFAULT_OPERATION_REGISTRY.resolve(requested)
    except OperationNameError as exc:
        raise _invalid("requested_operation is not admitted") from exc
    if resolution.canonical_operation != PROJECT_WORK_ASSIGNMENT_ASSIGN_OPERATION:
        raise _invalid("requested_operation does not match the route operation")
    supplied_hash = _text("payload_hash", payload.get("payload_hash"), 256)
    if supplied_hash != project_work_assignment_payload_hash(payload):
        raise EosProjectWorkAssignmentError(
            "EOS_PROJECT_WORK_ASSIGNMENT_PAYLOAD_HASH_MISMATCH",
            "Canonical WorkAssignment payload hash does not match",
            status_code=422,
        )
    return {
        "tenant_id": _scoped_id("tenant_id", payload.get("tenant_id")),
        "business_operation_id": _uuid(
            "business_operation_id", payload.get("business_operation_id")
        ),
        "idempotency_key": _text(
            "idempotency_key", payload.get("idempotency_key"), 256
        ),
        "operation": PROJECT_WORK_ASSIGNMENT_ASSIGN_OPERATION,
        "payload_hash": supplied_hash,
        "requested_operation": resolution.requested_operation,
    }


def _assignment_payload(value: object) -> Mapping[str, Any]:
    item = _object("assignment", value)
    forbidden = PRIVATE_PAYROLL_FIELDS.intersection(item)
    if forbidden:
        raise EosProjectWorkAssignmentError(
            "EOS_PROJECT_WORK_ASSIGNMENT_PRIVATE_PAYROLL_FORBIDDEN",
            "Private payroll fields are not admitted by the planning contract",
            status_code=422,
        )
    if set(item) != _ASSIGNMENT_FIELDS:
        raise _invalid("assignment fields do not match the admitted planning contract")
    return item


def _assignment_record(value: ProjectWorkAssignmentInput) -> dict[str, Any]:
    if not isinstance(value, ProjectWorkAssignmentInput):
        raise _invalid("value must be ProjectWorkAssignmentInput")
    valid_from = _date("valid_from", value.valid_from)
    valid_until = (
        _date("valid_until", value.valid_until)
        if value.valid_until is not None
        else None
    )
    if valid_until is not None and valid_until < valid_from:
        raise _invalid("valid_until must be on or after valid_from")
    record = {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "assignment_id": _uuid("assignment_id", value.assignment_id),
        "project_id": _uuid("project_id", value.project_id),
        "work_set_id": _uuid("work_set_id", value.work_set_id),
        "work_set_revision": _positive_int(
            "work_set_revision", value.work_set_revision
        ),
        "work_code_id": _work_code("work_code_id", value.work_code_id),
        "performer_kind": _choice(
            "performer_kind",
            value.performer_kind,
            PROJECT_WORK_ASSIGNMENT_PERFORMER_KINDS,
        ),
        "subject_ref": _scoped_id("subject_ref", value.subject_ref),
        "performer_authority_hash": _hash_ref(
            "performer_authority_hash", value.performer_authority_hash
        ),
        "assignment_scope": _choice(
            "assignment_scope", value.assignment_scope, PROJECT_WORK_ASSIGNMENT_SCOPES
        ),
        "planned_man_days": _positive_decimal(
            "planned_man_days", value.planned_man_days
        ),
        "planned_grade_id": _text("planned_grade_id", value.planned_grade_id, 64),
        "grade_policy_ref": _text("grade_policy_ref", value.grade_policy_ref, 256),
        "grade_policy_hash": _hash_ref("grade_policy_hash", value.grade_policy_hash),
        "valid_from": valid_from,
        "valid_until": valid_until,
        "approved_proof_hash": _hash_ref(
            "approved_proof_hash", value.approved_proof_hash
        ),
        "approved_by_subject_id": _scoped_id(
            "approved_by_subject_id", value.approved_by_subject_id
        ),
    }
    record["assignment_hash"] = semantic_sha256_hash_ref(
        {
            "domain": "EOS-PROJECT-WORK-ASSIGNMENT-V1",
            **{key: _wire_value(item) for key, item in record.items()},
        }
    )
    record["created_at"] = datetime.now(UTC)
    return record


def _assignment_semantics(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        _wire_value(value.get(field))
        for field in (
            "tenant_id",
            "assignment_id",
            "project_id",
            "work_set_id",
            "work_set_revision",
            "work_code_id",
            "performer_kind",
            "subject_ref",
            "performer_authority_hash",
            "assignment_scope",
            "planned_man_days",
            "planned_grade_id",
            "grade_policy_ref",
            "grade_policy_hash",
            "valid_from",
            "valid_until",
            "approved_proof_hash",
            "approved_by_subject_id",
            "assignment_hash",
        )
    )


def _assignment_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: _wire_value(value[field])
        for field in (
            "tenant_id",
            "assignment_id",
            "project_id",
            "work_set_id",
            "work_set_revision",
            "work_code_id",
            "performer_kind",
            "subject_ref",
            "performer_authority_hash",
            "assignment_scope",
            "planned_man_days",
            "planned_grade_id",
            "grade_policy_ref",
            "grade_policy_hash",
            "valid_from",
            "valid_until",
            "approved_proof_hash",
            "approved_by_subject_id",
            "assignment_hash",
            "created_at",
        )
    }


def _admit_authorization(
    value: object,
    *,
    tenant_id: str,
    subject_id: str,
    required_scope: str,
    project_id: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("active") is not True:
        raise _denied("Active OA authority is required")
    if value.get("tenant_id") != tenant_id or value.get("subject_id") != subject_id:
        raise _denied("OA tenant and subject scope do not match")
    scopes = _string_set(value.get("scopes"))
    if required_scope not in scopes:
        raise _denied(f"Current {required_scope} authorization was denied")
    revision_hash = value.get("revision_hash")
    if (
        not isinstance(revision_hash, str)
        or _REVISION_HASH.fullmatch(revision_hash) is None
    ):
        raise _denied("OA authorization revision is invalid")
    project_ids = value.get("project_ids")
    if project_ids is not None and project_id not in _string_set(project_ids):
        raise _denied("OA Project scope does not include the target Project")
    return {"scopes": scopes, "revision_hash": revision_hash}


def _require_service_caller(value: object) -> None:
    if (
        not isinstance(value, EosServiceCaller)
        or value.audience != "nex-eos"
        or "service:call" not in value.scopes
    ):
        raise _denied("Authenticated nex-eos service trust is required")


def _object(field: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an object")
    return value


def _string_set(value: object) -> set[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _denied("OA scope projection is invalid")
    normalized = {item for item in value if isinstance(item, str) and item}
    if len(normalized) != len(value):
        raise _denied("OA scope projection is invalid")
    return normalized


def _scoped_id(field: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(f"{field} has invalid stable-reference syntax")
    return normalized


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} must be a positive integer")
    return value


def _positive_decimal(field: str, value: object) -> Decimal:
    if isinstance(value, (bool, float)):
        raise _invalid(f"{field} must be an exact positive decimal")
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _invalid(f"{field} must be an exact positive decimal") from exc
    if not normalized.is_finite() or normalized <= 0 or normalized > Decimal(99999999):
        raise _invalid(f"{field} must be within the admitted positive range")
    if normalized.as_tuple().exponent < -4:
        raise _invalid(f"{field} supports at most four decimal places")
    return normalized.quantize(Decimal("0.0001"))


def _text(field: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(f"{field} must contain 1..{maximum} characters")
    return normalized


def _choice(field: str, value: object, allowed: frozenset[str]) -> str:
    normalized = _text(field, value, 64)
    if normalized not in allowed:
        raise _invalid(f"{field} is not admitted")
    return normalized


def _work_code(field: str, value: object) -> str:
    normalized = _text(field, value, 16)
    if _WORK_CODE.fullmatch(normalized) is None:
        raise _invalid(f"{field} must be a canonical FL work code")
    return normalized


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a SHA-256 hash reference") from exc


def _date(field: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise _invalid(f"{field} must be a date")
    return value


def _date_input(field: str, value: object) -> date:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be an ISO date") from exc


def _optional_date_input(field: str, value: object) -> date | None:
    return None if value is None else _date_input(field, value)


def _wire_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _conflict(detail: str) -> EosProjectWorkAssignmentError:
    return EosProjectWorkAssignmentError(
        "EOS_PROJECT_WORK_ASSIGNMENT_CONFLICT", detail, status_code=409
    )


def _not_found(detail: str) -> EosProjectWorkAssignmentError:
    return EosProjectWorkAssignmentError(
        "EOS_PROJECT_WORK_ASSIGNMENT_NOT_FOUND", detail, status_code=404
    )


def _denied(detail: str) -> EosProjectWorkAssignmentError:
    return EosProjectWorkAssignmentError(
        "EOS_PROJECT_WORK_ASSIGNMENT_AUTHORIZATION_DENIED", detail, status_code=403
    )


def _invalid(detail: str) -> EosProjectWorkAssignmentError:
    return EosProjectWorkAssignmentError(
        "EOS_PROJECT_WORK_ASSIGNMENT_INVALID", detail, status_code=422
    )


def _unavailable() -> EosProjectWorkAssignmentError:
    return EosProjectWorkAssignmentError(
        "EOS_PROJECT_WORK_ASSIGNMENT_PERSISTENCE_UNAVAILABLE",
        "Project WorkAssignment persistence is unavailable",
        status_code=503,
        retryable=True,
    )
