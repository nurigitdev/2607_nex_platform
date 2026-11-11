from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import DEFAULT_OPERATION_REGISTRY, OperationNameError
from nex_runtime.semantic_hashes import (
    canonical_json,
    nsl_write_payload_hash_ref,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .approval_policies import (
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
)
from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_formal_wc import WcApprovalWorkItemClient
from .business_transactions import (
    EOS_METADATA,
    EosBusinessOperationError,
    EosBusinessOperationRequest,
    EosBusinessTransactionCoordinator,
)
from .legal_entities import (
    EOS_LEGAL_ENTITY_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
)
from .projects import EOS_PROJECT_TABLE
from .voucher_commands import EosServiceCaller

ACCOUNTING_APPROVAL_REQUEST_OPERATION = "FINANCE.ACCOUNTING_APPROVAL.REQUEST"
ACCOUNTING_APPROVAL_REQUEST_SCOPE = "finance:journal:request-approval"
SCOPED_APPROVAL_PURPOSES = frozenset({"DOCUMENT_SIGNOFF", "ACCOUNTING_POSTING"})
SCOPED_APPROVAL_SCOPE_TYPES = frozenset({"COMPANY", "PROJECT", "PROJECT_SET"})
SCOPED_APPROVAL_STATES = frozenset(
    {"PENDING", "APPROVED", "REJECTED", "CANCELLED", "EXPIRED"}
)

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_REVISION_HASH = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")

EOS_SCOPED_APPROVAL_CASE_TABLE = Table(
    "eos_scoped_approval_case",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("case_id", Uuid(as_uuid=False), primary_key=True),
    Column("idempotency_key", String(256), nullable=False),
    Column("company_id", Uuid(as_uuid=False), nullable=False),
    Column("purpose", String(32), nullable=False),
    Column("scope_type", String(16), nullable=False),
    Column("project_set_hash", String(71), nullable=False),
    Column("subject_ref", String(256), nullable=False),
    Column("subject_revision", Integer, nullable=False),
    Column("subject_hash", String(71), nullable=False),
    Column("requester_ref_type", String(32), nullable=False),
    Column("requester_id", String(128), nullable=False),
    Column("approval_policy_id", Uuid(as_uuid=False), nullable=False),
    Column("approval_policy_version", Integer, nullable=False),
    Column("approval_policy_hash", String(71), nullable=False),
    Column("oa_decision_ref", String(128), nullable=False),
    Column("authorization_revision_hash", String(71), nullable=False),
    Column("authorization_checked_at", DateTime(timezone=True), nullable=False),
    Column("state", String(16), nullable=False),
    Column("active_stage_order", Integer, nullable=True),
    Column("stage_count", Integer, nullable=False),
    Column("target_role_ref", String(32), nullable=True),
    Column("version", Integer, nullable=False),
    Column("case_hash", String(71), nullable=False),
    Column("created_business_operation_id", Uuid(as_uuid=False), nullable=False),
    Column("correlation_id", String(128), nullable=False),
    Column("causation_id", String(128), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint(
        "tenant_id", "idempotency_key", name="ux_eos_scoped_approval_idem"
    ),
    UniqueConstraint("tenant_id", "case_hash", name="ux_eos_scoped_approval_hash"),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_scoped_approval_company",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "approval_policy_id"),
        ("eos_approval_policy.tenant_id", "eos_approval_policy.approval_policy_id"),
        name="fk_eos_scoped_approval_policy",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "created_business_operation_id"),
        (
            "eos_business_operation.tenant_id",
            "eos_business_operation.business_operation_id",
        ),
        name="fk_eos_scoped_approval_operation",
    ),
    CheckConstraint(
        "purpose IN ('DOCUMENT_SIGNOFF', 'ACCOUNTING_POSTING')",
        name="ck_eos_scoped_approval_purpose",
    ),
    CheckConstraint(
        "scope_type IN ('COMPANY', 'PROJECT', 'PROJECT_SET')",
        name="ck_eos_scoped_approval_scope",
    ),
    CheckConstraint(
        "state IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED', 'EXPIRED')",
        name="ck_eos_scoped_approval_state",
    ),
    CheckConstraint("subject_revision > 0", name="ck_eos_scoped_approval_revision"),
    CheckConstraint(
        "stage_count BETWEEN 1 AND 5", name="ck_eos_scoped_approval_stage_count"
    ),
    CheckConstraint(
        "active_stage_order IS NULL OR active_stage_order BETWEEN 1 AND stage_count",
        name="ck_eos_scoped_approval_active_stage",
    ),
    CheckConstraint("version > 0", name="ck_eos_scoped_approval_version"),
)
Index(
    "ix_eos_scoped_approval_state",
    EOS_SCOPED_APPROVAL_CASE_TABLE.c.tenant_id,
    EOS_SCOPED_APPROVAL_CASE_TABLE.c.company_id,
    EOS_SCOPED_APPROVAL_CASE_TABLE.c.state,
    EOS_SCOPED_APPROVAL_CASE_TABLE.c.created_at,
)
Index(
    "ux_eos_scoped_approval_subject",
    EOS_SCOPED_APPROVAL_CASE_TABLE.c.tenant_id,
    EOS_SCOPED_APPROVAL_CASE_TABLE.c.company_id,
    EOS_SCOPED_APPROVAL_CASE_TABLE.c.purpose,
    EOS_SCOPED_APPROVAL_CASE_TABLE.c.subject_ref,
    EOS_SCOPED_APPROVAL_CASE_TABLE.c.subject_revision,
    unique=True,
    postgresql_where=EOS_SCOPED_APPROVAL_CASE_TABLE.c.state.in_(
        ("PENDING", "APPROVED")
    ),
    sqlite_where=EOS_SCOPED_APPROVAL_CASE_TABLE.c.state.in_(("PENDING", "APPROVED")),
)

EOS_SCOPED_APPROVAL_BINDING_TABLE = Table(
    "eos_scoped_approval_subject_binding",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("case_id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), nullable=False),
    Column("authorization_scope_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "case_id"),
        ("eos_scoped_approval_case.tenant_id", "eos_scoped_approval_case.case_id"),
        name="fk_eos_scoped_binding_case",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_scoped_binding_project",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_scoped_binding_company",
    ),
    UniqueConstraint(
        "tenant_id",
        "case_id",
        "authorization_scope_hash",
        name="ux_eos_scoped_binding_scope_hash",
    ),
)
Index(
    "ix_eos_scoped_binding_project",
    EOS_SCOPED_APPROVAL_BINDING_TABLE.c.tenant_id,
    EOS_SCOPED_APPROVAL_BINDING_TABLE.c.company_id,
    EOS_SCOPED_APPROVAL_BINDING_TABLE.c.project_id,
)


class EosScopedApprovalError(RuntimeError):
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
class ScopedApprovalCaseInput:
    tenant_id: str
    case_id: str
    idempotency_key: str
    company_id: str
    purpose: str
    scope_type: str
    project_ids: Sequence[str]
    subject_ref: str
    subject_revision: int
    subject_hash: str
    requester_subject_id: str
    approval_policy_id: str
    oa_decision_ref: str
    authorization_revision_hash: str
    authorization_checked_at: datetime
    created_business_operation_id: str
    correlation_id: str
    causation_id: str
    expires_at: datetime | None = None


class SqlAlchemyEosScopedApprovalRepository:
    def __init__(self, session_factory: sessionmaker[Session], *, clock=None) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_in_session(
        self, session: Session, value: ScopedApprovalCaseInput
    ) -> tuple[dict[str, Any], bool]:
        now = _aware_datetime("clock", self._clock())
        request = _case_request(value)
        policy, stages = self._load_policy(
            session,
            tenant_id=request["tenant_id"],
            approval_policy_id=request["approval_policy_id"],
            purpose=request["purpose"],
            effective_at=now,
        )
        self._require_company(session, request, effective_at=now)
        self._require_project_scope(
            session,
            request=request,
            policy=policy,
            effective_at=now,
        )
        record = _case_record(request, policy=policy, stages=stages, now=now)
        existing = self._load_existing(session, request)
        if existing is not None:
            if existing["case_hash"] != record["case_hash"]:
                raise _conflict("Scoped approval replay has different semantics")
            return self._projection(session, existing), False
        bindings = _binding_records(record, request["project_ids"], now=now)
        try:
            session.execute(EOS_SCOPED_APPROVAL_CASE_TABLE.insert().values(**record))
            if bindings:
                session.execute(EOS_SCOPED_APPROVAL_BINDING_TABLE.insert(), bindings)
        except IntegrityError as exc:
            raise _conflict(
                "Scoped approval identity or subject revision conflicts"
            ) from exc
        return _projection(record, bindings), True

    def create(self, value: ScopedApprovalCaseInput) -> tuple[dict[str, Any], bool]:
        try:
            with self._session_factory.begin() as session:
                return self.create_in_session(session, value)
        except EosScopedApprovalError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_case(self, *, tenant_id: str, case_id: str) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id, 128)
        case_id = _uuid("case_id", case_id)
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        select(EOS_SCOPED_APPROVAL_CASE_TABLE).where(
                            EOS_SCOPED_APPROVAL_CASE_TABLE.c.tenant_id == tenant_id,
                            EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == case_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                return self._projection(session, row) if row is not None else None
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    @staticmethod
    def _load_existing(
        session: Session, request: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        return (
            session.execute(
                select(EOS_SCOPED_APPROVAL_CASE_TABLE).where(
                    EOS_SCOPED_APPROVAL_CASE_TABLE.c.tenant_id == request["tenant_id"],
                    (EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == request["case_id"])
                    | (
                        EOS_SCOPED_APPROVAL_CASE_TABLE.c.idempotency_key
                        == request["idempotency_key"]
                    ),
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _load_policy(
        session: Session,
        *,
        tenant_id: str,
        approval_policy_id: str,
        purpose: str,
        effective_at: datetime,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        row = (
            session.execute(
                select(EOS_APPROVAL_POLICY_TABLE).where(
                    EOS_APPROVAL_POLICY_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVAL_POLICY_TABLE.c.approval_policy_id
                    == approval_policy_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise _not_found("Approval policy was not found in tenant scope")
        policy = dict(row)
        if (
            policy["approval_domain"] != "BUSINESS_FORMAL"
            or policy["status"] != "ACTIVE"
            or _as_utc(policy["effective_from"]) > effective_at
            or (
                policy["effective_until"] is not None
                and _as_utc(policy["effective_until"]) <= effective_at
            )
            or policy["transaction_type"] not in (None, purpose)
        ):
            raise _conflict(
                "Approval policy is not effective for the requested purpose"
            )
        stages = [
            dict(item)
            for item in session.execute(
                select(EOS_APPROVAL_POLICY_STAGE_TABLE)
                .where(
                    EOS_APPROVAL_POLICY_STAGE_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVAL_POLICY_STAGE_TABLE.c.approval_policy_id
                    == approval_policy_id,
                )
                .order_by(EOS_APPROVAL_POLICY_STAGE_TABLE.c.stage_order)
            ).mappings()
        ]
        if not stages:
            raise _conflict("Approval policy has no persisted Human stages")
        return policy, stages

    @staticmethod
    def _require_company(
        session: Session, request: Mapping[str, Any], *, effective_at: datetime
    ) -> None:
        company = (
            session.execute(
                select(EOS_LEGAL_ENTITY_TABLE).where(
                    EOS_LEGAL_ENTITY_TABLE.c.tenant_id == request["tenant_id"],
                    EOS_LEGAL_ENTITY_TABLE.c.company_id == request["company_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if company is None:
            raise _not_found("LegalEntity was not found in tenant scope")
        if (
            company["status"] != "ACTIVE"
            or company["effective_from"] > effective_at.date()
        ):
            raise _conflict("LegalEntity is not active at approval request time")

    @staticmethod
    def _require_project_scope(
        session: Session,
        *,
        request: Mapping[str, Any],
        policy: Mapping[str, Any],
        effective_at: datetime,
    ) -> None:
        project_ids = request["project_ids"]
        policy_project = (
            str(policy["project_id"]) if policy["project_id"] is not None else None
        )
        if policy_project is not None and (
            request["scope_type"] != "PROJECT" or project_ids != [policy_project]
        ):
            raise _conflict("Project-specific policy does not match approval scope")
        for project_id in project_ids:
            project = session.execute(
                select(EOS_PROJECT_TABLE.c.status).where(
                    EOS_PROJECT_TABLE.c.tenant_id == request["tenant_id"],
                    EOS_PROJECT_TABLE.c.project_id == project_id,
                )
            ).scalar_one_or_none()
            binding = session.execute(
                select(EOS_PROJECT_COMPANY_BINDING_TABLE.c.binding_id).where(
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.tenant_id
                    == request["tenant_id"],
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.project_id == project_id,
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.company_id
                    == request["company_id"],
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.state == "APPROVED",
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_from
                    <= effective_at.date(),
                    (
                        EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until.is_(None)
                        | (
                            EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until
                            > effective_at.date()
                        )
                    ),
                )
            ).scalar_one_or_none()
            if project != "ACTIVE" or binding is None:
                raise _conflict(
                    "Every scoped Project must be active and bound to the same company"
                )

    @staticmethod
    def _projection(session: Session, value: Mapping[str, Any]) -> dict[str, Any]:
        bindings = [
            dict(row)
            for row in session.execute(
                select(EOS_SCOPED_APPROVAL_BINDING_TABLE)
                .where(
                    EOS_SCOPED_APPROVAL_BINDING_TABLE.c.tenant_id == value["tenant_id"],
                    EOS_SCOPED_APPROVAL_BINDING_TABLE.c.case_id == value["case_id"],
                )
                .order_by(EOS_SCOPED_APPROVAL_BINDING_TABLE.c.project_id)
            ).mappings()
        ]
        return _projection(value, bindings)


class EosScopedApprovalService:
    def __init__(
        self,
        *,
        repository: SqlAlchemyEosScopedApprovalRepository,
        coordinator: EosBusinessTransactionCoordinator,
        authorization_source: AuthorizationSource,
        wc_client: WcApprovalWorkItemClient,
        accounting_review_repository=None,
        clock=None,
    ) -> None:
        self._repository = repository
        self._coordinator = coordinator
        self._authorization_source = authorization_source
        self._wc_client = wc_client
        self._accounting_review_repository = accounting_review_repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def request_case(
        self, payload: Mapping[str, Any], *, caller: EosServiceCaller
    ) -> dict[str, Any]:
        _require_service_caller(caller)
        envelope = _write_envelope(payload)
        case = _case_payload(payload.get("case"))
        accounting_review = case.pop("accounting_review", None)
        if case["tenant_id"] != envelope["tenant_id"]:
            raise _invalid("Case tenant does not match the write envelope")
        authorization = self._authorize(
            tenant_id=envelope["tenant_id"],
            subject_id=case["requester_subject_id"],
            company_id=case["company_id"],
            project_ids=case["project_ids"],
        )
        requested_operation = envelope.pop("requested_operation")
        value = ScopedApprovalCaseInput(
            **case,
            idempotency_key=envelope["idempotency_key"],
            oa_decision_ref=authorization["decision_ref"],
            authorization_revision_hash=authorization["revision_hash"],
            authorization_checked_at=authorization["checked_at"],
            created_business_operation_id=envelope["business_operation_id"],
        )

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise RuntimeError("ScopedApprovalCase requires a database transaction")
            from .accounting_approval import EosAccountingApprovalError

            try:
                scoped_case, _created = self._repository.create_in_session(
                    session, value
                )
                review_projection = None
                if accounting_review is not None:
                    if self._accounting_review_repository is None:
                        raise EosScopedApprovalError(
                            "EOS_ACCOUNTING_REVIEW_UNAVAILABLE",
                            "Accounting review persistence is not configured",
                            status_code=503,
                            retryable=True,
                        )
                    review_projection = (
                        self._accounting_review_repository.create_in_session(
                            session,
                            scoped_case=scoped_case,
                            review=accounting_review,
                        )
                    )
            except EosScopedApprovalError as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc
            except EosAccountingApprovalError as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc
            return {
                "business_result_ref": f"eos.scoped-approval-case:{case['case_id']}",
                "scoped_approval_case": scoped_case,
                "accounting_review": review_projection,
                "requested_operation": requested_operation,
                "canonical_operation": ACCOUNTING_APPROVAL_REQUEST_OPERATION,
            }

        try:
            operation = self._coordinator.execute(
                EosBusinessOperationRequest(**envelope), mutation
            )
        except EosBusinessOperationError as exc:
            raise EosScopedApprovalError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        scoped_case = operation.result["scoped_approval_case"]
        work_item = scoped_approval_work_item(
            scoped_case,
            accounting_review=operation.result.get("accounting_review"),
        )
        try:
            publication = _wc_publication(self._wc_client.create_or_get(work_item))
        except EosScopedApprovalError:
            raise
        except Exception as exc:
            raise EosScopedApprovalError(
                "EOS_SCOPED_APPROVAL_WC_UNAVAILABLE",
                "WC approval publication is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        _require_wc_lineage(publication["work_item"], work_item)
        return {
            "schema_version": "eos_scoped_approval_request_receipt.v2",
            "created": operation.created,
            "tenant_id": operation.tenant_id,
            "business_operation_id": operation.business_operation_id,
            "commit_state": operation.commit_state,
            "scoped_approval_case": scoped_case,
            "wc_publication": publication,
        }

    def _authorize(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        company_id: str,
        project_ids: Sequence[str],
    ) -> dict[str, Any]:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id, subject_id=subject_id
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied("OA denied the approval requester") from exc
        except Exception as exc:
            raise EosScopedApprovalError(
                "EOS_SCOPED_APPROVAL_AUTHORIZATION_UNAVAILABLE",
                "OA effective authorization is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        if not isinstance(value, Mapping) or value.get("active") is not True:
            raise _denied("Active OA requester authorization is required")
        if value.get("tenant_id") != tenant_id or value.get("subject_id") != subject_id:
            raise _denied("OA tenant and requester identity do not match")
        scopes = _string_set("scopes", value.get("scopes"))
        if ACCOUNTING_APPROVAL_REQUEST_SCOPE not in scopes:
            raise _denied("Current finance approval request scope is required")
        revision = value.get("revision_hash")
        if not isinstance(revision, str) or _REVISION_HASH.fullmatch(revision) is None:
            raise _denied("OA authorization revision is invalid")
        company_ids = value.get("company_ids")
        if company_ids is not None and company_id not in _string_set(
            "company_ids", company_ids
        ):
            raise _denied("OA company scope does not include the target company")
        authorized_projects = value.get("project_ids")
        if authorized_projects is not None and not set(project_ids).issubset(
            _string_set("project_ids", authorized_projects)
        ):
            raise _denied("OA Project scope does not include every target Project")
        checked_at = _aware_datetime("authorization clock", self._clock())
        revision_hash = (
            revision if revision.startswith("sha256:") else f"sha256:{revision}"
        )
        decision_ref = value.get("decision_ref")
        if decision_ref is None:
            decision_ref = f"oa-authz:{revision_hash.removeprefix('sha256:')}"
        return {
            "revision_hash": revision_hash,
            "decision_ref": _scoped_id("oa_decision_ref", decision_ref, 128),
            "checked_at": checked_at,
        }


def scoped_approval_payload_hash(payload: Mapping[str, Any]) -> str:
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
        {"operation": ACCOUNTING_APPROVAL_REQUEST_OPERATION, **projected}
    )


def scoped_approval_work_item(
    scoped_case: Mapping[str, Any],
    *,
    accounting_review: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    stage_order = scoped_case["active_stage_order"]
    if stage_order is None or scoped_case["state"] != "PENDING":
        raise _conflict("Scoped approval case has no publishable active stage")
    source_ref = (
        f"eos.scoped-approval-case:{scoped_case['case_id']}:stage:{stage_order}"
    )
    project_ids = scoped_case["project_ids"]
    semantic = {
        "schema_version": "eos_scoped_approval_wc_binding.v2",
        "tenant_id": scoped_case["tenant_id"],
        "case_id": scoped_case["case_id"],
        "case_hash": scoped_case["case_hash"],
        "company_id": scoped_case["company_id"],
        "purpose": scoped_case["purpose"],
        "scope_type": scoped_case["scope_type"],
        "project_set_hash": scoped_case["project_set_hash"],
        "project_ids": project_ids,
        "subject_ref": scoped_case["subject_ref"],
        "subject_revision": scoped_case["subject_revision"],
        "subject_hash": scoped_case["subject_hash"],
        "requester_ref": scoped_case["requester_ref"],
        "policy_ref": scoped_case["approval_policy_ref"],
        "active_stage_order": stage_order,
        "stage_count": scoped_case["stage_count"],
        "target_role_ref": scoped_case["target_role_ref"],
        "authorization_revision_hash": scoped_case["authorization_revision_hash"],
    }
    if accounting_review is not None:
        semantic["accounting_review_hash"] = accounting_review["review_hash"]
    display_summary = {
        "purpose": scoped_case["purpose"],
        "company_id": scoped_case["company_id"],
        "scope_type": scoped_case["scope_type"],
        "project_count": len(project_ids),
        "subject_ref": scoped_case["subject_ref"],
        "subject_revision": scoped_case["subject_revision"],
        "stage_order": stage_order,
        "stage_count": scoped_case["stage_count"],
    }
    if accounting_review is not None:
        display_summary["accounting_review"] = {
            key: accounting_review[key]
            for key in (
                "candidate_id",
                "candidate_revision",
                "original_currency",
                "original_amount",
                "market_base_rate",
                "rate_reference_date",
                "rate_publication",
                "functional_currency",
                "functional_amount",
                "fx_exception",
                "review_hash",
            )
        }
    created_at = scoped_case["created_at"]
    expires_at = scoped_case["expires_at"]
    return {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": scoped_case["tenant_id"],
        "approval_work_item_id": deterministic_scoped_approval_work_item_id(
            tenant_id=scoped_case["tenant_id"],
            case_id=scoped_case["case_id"],
            stage_order=stage_order,
        ),
        "approval_domain": "BUSINESS_FORMAL",
        "source_ref": source_ref,
        "semantic_hash": semantic_sha256_hash_ref(semantic),
        "title": f"Approve {scoped_case['purpose']}: {scoped_case['subject_ref']}",
        "display_safe_summary": canonical_json(display_summary),
        "approval_provider_type": "EOS",
        "approval_target_ref": f"eos.scoped-approval-case:{scoped_case['case_id']}",
        "target_approver_ref": None,
        "target_role_ref": scoped_case["target_role_ref"],
        "target_org_scope_ref": None,
        "target_project_scope_ref": (
            project_ids[0] if scoped_case["scope_type"] == "PROJECT" else None
        ),
        "agent_execution_id": None,
        "executable_step_id": None,
        "nsl_execution_id": None,
        "business_operation_id": scoped_case["created_business_operation_id"],
        "approval_request_id": scoped_case["case_id"],
        "protected_request_ref": scoped_case["subject_ref"],
        "resume_target_ref": source_ref,
        "state": "PENDING",
        "created_at": created_at,
        "expires_at": expires_at,
        "version": scoped_case["version"],
    }


def deterministic_scoped_approval_work_item_id(
    *, tenant_id: str, case_id: str, stage_order: int
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/wc/scoped-business-formal/"
            f"{tenant_id}/{case_id}/{stage_order}",
        )
    )


def _write_envelope(payload: Mapping[str, Any]) -> dict[str, str]:
    requested = payload.get(
        "requested_operation", ACCOUNTING_APPROVAL_REQUEST_OPERATION
    )
    try:
        resolution = DEFAULT_OPERATION_REGISTRY.resolve(requested)
    except OperationNameError as exc:
        raise _invalid("requested_operation is not admitted") from exc
    if resolution.canonical_operation != ACCOUNTING_APPROVAL_REQUEST_OPERATION:
        raise _invalid("requested_operation does not match the route operation")
    supplied_hash = _hash_ref("payload_hash", payload.get("payload_hash"))
    if supplied_hash != scoped_approval_payload_hash(payload):
        raise EosScopedApprovalError(
            "EOS_SCOPED_APPROVAL_PAYLOAD_HASH_MISMATCH",
            "Canonical scoped approval payload hash does not match",
            status_code=422,
        )
    return {
        "tenant_id": _scoped_id("tenant_id", payload.get("tenant_id"), 128),
        "business_operation_id": _uuid(
            "business_operation_id", payload.get("business_operation_id")
        ),
        "idempotency_key": _text(
            "idempotency_key", payload.get("idempotency_key"), 256
        ),
        "operation": ACCOUNTING_APPROVAL_REQUEST_OPERATION,
        "payload_hash": supplied_hash,
        "requested_operation": resolution.requested_operation,
    }


def _case_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("case must be an object")
    fields = {
        "tenant_id",
        "case_id",
        "company_id",
        "purpose",
        "scope_type",
        "project_ids",
        "subject_ref",
        "subject_revision",
        "subject_hash",
        "requester_subject_id",
        "approval_policy_id",
        "correlation_id",
        "causation_id",
        "expires_at",
    }
    optional_fields = {"accounting_review"}
    if not fields.issubset(value) or set(value) - fields - optional_fields:
        raise _invalid("case fields do not match the admitted v2 contract")
    scope_type = _choice(
        "scope_type", value.get("scope_type"), SCOPED_APPROVAL_SCOPE_TYPES
    )
    project_ids = _project_ids(value.get("project_ids"))
    _require_scope_shape(scope_type, project_ids)
    result = {
        "tenant_id": _scoped_id("tenant_id", value.get("tenant_id"), 128),
        "case_id": _uuid("case_id", value.get("case_id")),
        "company_id": _uuid("company_id", value.get("company_id")),
        "purpose": _choice("purpose", value.get("purpose"), SCOPED_APPROVAL_PURPOSES),
        "scope_type": scope_type,
        "project_ids": project_ids,
        "subject_ref": _text("subject_ref", value.get("subject_ref"), 256),
        "subject_revision": _positive_int(
            "subject_revision", value.get("subject_revision")
        ),
        "subject_hash": _hash_ref("subject_hash", value.get("subject_hash")),
        "requester_subject_id": _scoped_id(
            "requester_subject_id", value.get("requester_subject_id"), 128
        ),
        "approval_policy_id": _uuid(
            "approval_policy_id", value.get("approval_policy_id")
        ),
        "correlation_id": _scoped_id(
            "correlation_id", value.get("correlation_id"), 128
        ),
        "causation_id": _scoped_id("causation_id", value.get("causation_id"), 128),
        "expires_at": _optional_datetime("expires_at", value.get("expires_at")),
    }
    if "accounting_review" in value:
        review = value.get("accounting_review")
        if not isinstance(review, Mapping):
            raise _invalid("accounting_review must be an object")
        result["accounting_review"] = dict(review)
    return result


def _case_request(value: ScopedApprovalCaseInput) -> dict[str, Any]:
    if not isinstance(value, ScopedApprovalCaseInput):
        raise _invalid("value must be ScopedApprovalCaseInput")
    project_ids = _project_ids(value.project_ids)
    scope_type = _choice("scope_type", value.scope_type, SCOPED_APPROVAL_SCOPE_TYPES)
    _require_scope_shape(scope_type, project_ids)
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id, 128),
        "case_id": _uuid("case_id", value.case_id),
        "idempotency_key": _text("idempotency_key", value.idempotency_key, 256),
        "company_id": _uuid("company_id", value.company_id),
        "purpose": _choice("purpose", value.purpose, SCOPED_APPROVAL_PURPOSES),
        "scope_type": scope_type,
        "project_ids": project_ids,
        "subject_ref": _text("subject_ref", value.subject_ref, 256),
        "subject_revision": _positive_int("subject_revision", value.subject_revision),
        "subject_hash": _hash_ref("subject_hash", value.subject_hash),
        "requester_subject_id": _scoped_id(
            "requester_subject_id", value.requester_subject_id, 128
        ),
        "approval_policy_id": _uuid("approval_policy_id", value.approval_policy_id),
        "oa_decision_ref": _scoped_id("oa_decision_ref", value.oa_decision_ref, 128),
        "authorization_revision_hash": _hash_ref(
            "authorization_revision_hash", value.authorization_revision_hash
        ),
        "authorization_checked_at": _aware_datetime(
            "authorization_checked_at", value.authorization_checked_at
        ),
        "created_business_operation_id": _uuid(
            "created_business_operation_id", value.created_business_operation_id
        ),
        "correlation_id": _scoped_id("correlation_id", value.correlation_id, 128),
        "causation_id": _scoped_id("causation_id", value.causation_id, 128),
        "expires_at": _optional_datetime("expires_at", value.expires_at),
    }


def _case_record(
    request: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    stages: Sequence[Mapping[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    if request["expires_at"] is not None and request["expires_at"] <= now:
        raise _invalid("expires_at must be later than creation time")
    project_set_hash = semantic_sha256_hash_ref(
        {
            "schema_version": "eos_scoped_approval_project_set.v2",
            "company_id": request["company_id"],
            "scope_type": request["scope_type"],
            "project_ids": request["project_ids"],
        }
    )
    semantics = {
        "schema_version": "eos_scoped_approval_case_semantics.v2",
        "tenant_id": request["tenant_id"],
        "case_id": request["case_id"],
        "company_id": request["company_id"],
        "purpose": request["purpose"],
        "scope_type": request["scope_type"],
        "project_set_hash": project_set_hash,
        "project_ids": request["project_ids"],
        "subject_ref": request["subject_ref"],
        "subject_revision": request["subject_revision"],
        "subject_hash": request["subject_hash"],
        "requester_ref": {
            "type": "oa.user",
            "id": request["requester_subject_id"],
        },
        "approval_policy_id": str(policy["approval_policy_id"]),
        "approval_policy_version": policy["version"],
        "approval_policy_hash": policy["policy_hash"],
        "authorization_revision_hash": request["authorization_revision_hash"],
        "expires_at": _timestamp(request["expires_at"]),
    }
    return {
        "tenant_id": request["tenant_id"],
        "case_id": request["case_id"],
        "idempotency_key": request["idempotency_key"],
        "company_id": request["company_id"],
        "purpose": request["purpose"],
        "scope_type": request["scope_type"],
        "project_set_hash": project_set_hash,
        "subject_ref": request["subject_ref"],
        "subject_revision": request["subject_revision"],
        "subject_hash": request["subject_hash"],
        "requester_ref_type": "oa.user",
        "requester_id": request["requester_subject_id"],
        "approval_policy_id": str(policy["approval_policy_id"]),
        "approval_policy_version": policy["version"],
        "approval_policy_hash": policy["policy_hash"],
        "oa_decision_ref": request["oa_decision_ref"],
        "authorization_revision_hash": request["authorization_revision_hash"],
        "authorization_checked_at": request["authorization_checked_at"],
        "state": "PENDING",
        "active_stage_order": 1,
        "stage_count": len(stages),
        "target_role_ref": stages[0]["position_type"],
        "version": 1,
        "case_hash": semantic_sha256_hash_ref(semantics),
        "created_business_operation_id": request["created_business_operation_id"],
        "correlation_id": request["correlation_id"],
        "causation_id": request["causation_id"],
        "expires_at": request["expires_at"],
        "created_at": now,
        "updated_at": now,
        "decided_at": None,
    }


def _binding_records(
    case: Mapping[str, Any], project_ids: Sequence[str], *, now: datetime
) -> list[dict[str, Any]]:
    return [
        {
            "tenant_id": case["tenant_id"],
            "case_id": case["case_id"],
            "project_id": project_id,
            "company_id": case["company_id"],
            "authorization_scope_hash": semantic_sha256_hash_ref(
                {
                    "schema_version": "eos_scoped_approval_authorization.v2",
                    "tenant_id": case["tenant_id"],
                    "requester_id": case["requester_id"],
                    "company_id": case["company_id"],
                    "project_id": project_id,
                    "required_scope": ACCOUNTING_APPROVAL_REQUEST_SCOPE,
                    "authorization_revision_hash": case["authorization_revision_hash"],
                }
            ),
            "created_at": now,
        }
        for project_id in project_ids
    ]


def _projection(
    value: Mapping[str, Any], bindings: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    project_ids = sorted(str(item["project_id"]) for item in bindings)
    return {
        "schema_version": "eos_scoped_approval_case.v2",
        "tenant_id": value["tenant_id"],
        "case_id": str(value["case_id"]),
        "company_id": str(value["company_id"]),
        "purpose": value["purpose"],
        "scope_type": value["scope_type"],
        "project_set_hash": value["project_set_hash"],
        "project_ids": project_ids,
        "subject_ref": value["subject_ref"],
        "subject_revision": value["subject_revision"],
        "subject_hash": value["subject_hash"],
        "requester_ref": {
            "type": value["requester_ref_type"],
            "id": value["requester_id"],
        },
        "approval_policy_ref": {
            "id": str(value["approval_policy_id"]),
            "version": value["approval_policy_version"],
            "hash": value["approval_policy_hash"],
        },
        "oa_decision_ref": value["oa_decision_ref"],
        "authorization_revision_hash": value["authorization_revision_hash"],
        "authorization_checked_at": _timestamp(value["authorization_checked_at"]),
        "state": value["state"],
        "active_stage_order": value["active_stage_order"],
        "stage_count": value["stage_count"],
        "target_role_ref": value["target_role_ref"],
        "version": value["version"],
        "case_hash": value["case_hash"],
        "created_business_operation_id": str(value["created_business_operation_id"]),
        "correlation_id": value["correlation_id"],
        "causation_id": value["causation_id"],
        "expires_at": _timestamp(value["expires_at"]),
        "created_at": _timestamp(value["created_at"]),
        "updated_at": _timestamp(value["updated_at"]),
        "decided_at": _timestamp(value["decided_at"]),
        "project_bindings": [
            {
                "project_id": str(item["project_id"]),
                "company_id": str(item["company_id"]),
                "authorization_scope_hash": item["authorization_scope_hash"],
            }
            for item in sorted(bindings, key=lambda item: str(item["project_id"]))
        ],
    }


def scoped_approval_case_projection(
    value: Mapping[str, Any], bindings: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Project one scoped case without exposing repository internals."""

    return _projection(value, bindings)


def _project_ids(value: object) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("project_ids must be an array")
    admitted = [_uuid("project_ids", item) for item in value]
    if len(admitted) != len(set(admitted)):
        raise _invalid("project_ids must be unique")
    return sorted(admitted)


def _require_scope_shape(scope_type: str, project_ids: Sequence[str]) -> None:
    if (
        (scope_type == "COMPANY" and project_ids)
        or (scope_type == "PROJECT" and len(project_ids) != 1)
        or (scope_type == "PROJECT_SET" and len(project_ids) < 2)
    ):
        raise _invalid("project_ids do not match scope_type")


def _wc_publication(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EosScopedApprovalError(
            "EOS_SCOPED_APPROVAL_WC_RESPONSE_INVALID",
            "WC approval publication response is invalid",
            status_code=502,
        )
    work_item = value.get("work_item")
    created = value.get("created")
    if not isinstance(work_item, Mapping) or not isinstance(created, bool):
        raise EosScopedApprovalError(
            "EOS_SCOPED_APPROVAL_WC_RESPONSE_INVALID",
            "WC approval publication response is invalid",
            status_code=502,
        )
    return {"work_item": dict(work_item), "created": created}


def _require_wc_lineage(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    fields = (
        "tenant_id",
        "approval_work_item_id",
        "approval_domain",
        "source_ref",
        "semantic_hash",
        "approval_provider_type",
        "approval_target_ref",
        "target_role_ref",
        "target_project_scope_ref",
        "business_operation_id",
        "approval_request_id",
        "protected_request_ref",
        "resume_target_ref",
    )
    if any(actual.get(field) != expected.get(field) for field in fields):
        raise EosScopedApprovalError(
            "EOS_SCOPED_APPROVAL_WC_RESPONSE_INVALID",
            "WC approval publication response lineage is invalid",
            status_code=502,
        )


def _require_service_caller(value: object) -> None:
    if (
        not isinstance(value, EosServiceCaller)
        or value.audience != "nex-eos"
        or "service:call" not in value.scopes
    ):
        raise _denied("Authenticated nex-eos service trust is required")


def _string_set(field: str, value: object) -> set[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _denied(f"OA {field} projection is invalid")
    normalized = {item for item in value if isinstance(item, str) and item}
    if len(normalized) != len(value):
        raise _denied(f"OA {field} projection is invalid")
    return normalized


def _scoped_id(field: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or _SCOPED_ID.fullmatch(value) is None
    ):
        raise _invalid(f"{field} has invalid stable-reference syntax")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} must be a positive integer")
    return value


def _text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _invalid(f"{field} must be non-empty and at most {maximum} characters")
    return value


def _choice(field: str, value: object, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise _invalid(f"{field} must be one of {sorted(choices)}")
    return value


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a sha256 hash reference") from exc


def _aware_datetime(field: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _optional_datetime(field: str, value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _invalid(f"{field} must be an ISO date-time") from exc
    return _aware_datetime(field, value)


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise _conflict("Persisted approval time is invalid")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timestamp(value: object) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> EosScopedApprovalError:
    return EosScopedApprovalError(
        "EOS_SCOPED_APPROVAL_INVALID", detail, status_code=422
    )


def _denied(detail: str) -> EosScopedApprovalError:
    return EosScopedApprovalError(
        "EOS_SCOPED_APPROVAL_AUTHORIZATION_DENIED", detail, status_code=403
    )


def _not_found(detail: str) -> EosScopedApprovalError:
    return EosScopedApprovalError(
        "EOS_SCOPED_APPROVAL_NOT_FOUND", detail, status_code=404
    )


def _conflict(detail: str) -> EosScopedApprovalError:
    return EosScopedApprovalError(
        "EOS_SCOPED_APPROVAL_CONFLICT", detail, status_code=409
    )


def _unavailable() -> EosScopedApprovalError:
    return EosScopedApprovalError(
        "EOS_SCOPED_APPROVAL_PERSISTENCE_UNAVAILABLE",
        "Scoped approval persistence is unavailable",
        status_code=503,
        retryable=True,
    )
