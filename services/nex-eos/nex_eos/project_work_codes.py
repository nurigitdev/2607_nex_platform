from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from nex_runtime import DEFAULT_OPERATION_REGISTRY, OperationNameError
from nex_runtime.semantic_hashes import (
    nsl_write_payload_hash_ref,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
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
from .legal_entities import EOS_PROJECT_COMPANY_BINDING_TABLE
from .project_memberships import EOS_PROJECT_MEMBER_TABLE
from .project_authorization import (
    EosProjectAuthorizationError,
    EosProjectAuthorizationGate,
)
from .projects import EOS_PROJECT_TABLE
from .voucher_commands import EosServiceCaller

PROJECT_WORK_CODE_SET_APPROVE_OPERATION = "PROJECT.WORK_CODE_SET.APPROVE"
PROJECT_WORK_CODE_READ_SCOPE = "project:work-code:read"
PROJECT_WORK_CODE_APPROVE_SCOPE = "project:work-code:approve"
PROJECT_ADMIN_SCOPE = "project:project:admin"

D12_CATALOG_ID = "mybee.fl.d12.project-governance"
D12_CATALOG_VERSION = "1.0.0"
D12_CATALOG_DIGEST = (
    "sha256:31e5a24a8a5e62f80fc1571a4a232723a90f9c1b628841ae80df24654848c8ba"
)
MANDATORY_D12_WORK_CODE_IDS = (
    "FL0012004",
    "FL0012005",
    "FL0012006",
    "FL0012013",
    "FL0012026",
)
MANDATORY_D12_CODES_HASH = semantic_sha256_hash_ref(
    {
        "domain": "EOS-D12-MANDATORY-WORK-CODES-V1",
        "code_ids": list(MANDATORY_D12_WORK_CODE_IDS),
    }
)

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_SEMVER = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
_REVISION_HASH = re.compile(r"^[0-9a-f]{64}$")

EOS_PROJECT_WORK_CODE_SET_TABLE = Table(
    "eos_project_work_code_set",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), primary_key=True),
    Column("work_set_id", Uuid(as_uuid=False), primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("catalog_id", String(128), nullable=False),
    Column("catalog_version", String(32), nullable=False),
    Column("catalog_digest", String(71), nullable=False),
    Column("template_ref", String(256), nullable=False),
    Column("template_version", String(32), nullable=False),
    Column("mandatory_codes_hash", String(71), nullable=False),
    Column("approved_proof_hash", String(71), nullable=False),
    Column("approved_by_subject_id", String(128), nullable=False),
    Column("pm_subject_id", String(128), nullable=False),
    Column("pa_agent_id", String(128), nullable=False),
    Column("pa_identity_evidence_hash", String(71), nullable=False),
    Column("state", String(16), nullable=False),
    Column("effective_from", Date, nullable=False),
    Column("work_set_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_project_work_set_project",
    ),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "revision",
        name="ux_eos_project_work_set_revision",
    ),
    UniqueConstraint("tenant_id", "work_set_hash", name="ux_eos_project_work_set_hash"),
    CheckConstraint("revision > 0", name="ck_eos_project_work_set_revision"),
    CheckConstraint("state = 'APPROVED'", name="ck_eos_project_work_set_state"),
    CheckConstraint(
        "catalog_id = 'mybee.fl.d12.project-governance' "
        "AND catalog_version = '1.0.0' "
        "AND catalog_digest = "
        "'sha256:31e5a24a8a5e62f80fc1571a4a232723a90f9c1b628841ae80df24654848c8ba'",
        name="ck_eos_project_work_set_catalog",
    ),
    CheckConstraint(
        f"mandatory_codes_hash = '{MANDATORY_D12_CODES_HASH}'",
        name="ck_eos_project_work_set_mandatory_hash",
    ),
)
Index(
    "ix_eos_project_work_set_current",
    EOS_PROJECT_WORK_CODE_SET_TABLE.c.tenant_id,
    EOS_PROJECT_WORK_CODE_SET_TABLE.c.project_id,
    EOS_PROJECT_WORK_CODE_SET_TABLE.c.revision,
)

EOS_PROJECT_WORK_CODE_ENTRY_TABLE = Table(
    "eos_project_work_code_entry",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), primary_key=True),
    Column("work_set_id", Uuid(as_uuid=False), primary_key=True),
    Column("work_set_revision", Integer, primary_key=True),
    Column("work_code_id", String(16), primary_key=True),
    Column("ordinal", Integer, nullable=False),
    Column("mandatory", Boolean, nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "project_id", "work_set_id", "work_set_revision"),
        (
            "eos_project_work_code_set.tenant_id",
            "eos_project_work_code_set.project_id",
            "eos_project_work_code_set.work_set_id",
            "eos_project_work_code_set.revision",
        ),
        name="fk_eos_project_work_code_entry_set",
    ),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "work_set_id",
        "work_set_revision",
        "ordinal",
        name="ux_eos_project_work_code_entry_order",
    ),
    CheckConstraint("ordinal > 0", name="ck_eos_project_work_code_entry_order"),
)


class EosProjectWorkCodeError(RuntimeError):
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
class ProjectWorkCodeSetApproval:
    tenant_id: str
    project_id: str
    work_set_id: str
    revision: int
    catalog_id: str
    catalog_version: str
    catalog_digest: str
    template_ref: str
    template_version: str
    code_ids: tuple[str, ...]
    approved_proof_hash: str
    approved_by_subject_id: str
    pm_subject_id: str
    pa_agent_id: str
    pa_identity_evidence_hash: str
    effective_from: date


class SqlAlchemyEosProjectWorkCodeRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def approve_in_session(
        self, session: Session, value: ProjectWorkCodeSetApproval
    ) -> dict[str, Any]:
        record, code_ids = _approval_record(value)
        existing = self._set_by_identity(session, record)
        if existing is not None:
            entries = self._entry_ids(session, existing)
            if (
                _set_semantics(existing) == _set_semantics(record)
                and entries == code_ids
            ):
                return _set_projection(existing, entries)
            raise _conflict("WorkCodeSet identity has different semantics")

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
            raise _conflict(
                "Project must be technically ACTIVE for WorkCodeSet approval"
            )

        latest = self._latest_header(session, record["tenant_id"], record["project_id"])
        if latest is None:
            if record["revision"] != 1:
                raise _conflict("First WorkCodeSet revision must be 1")
        elif (
            record["work_set_id"] != latest["work_set_id"]
            or record["revision"] != int(latest["revision"]) + 1
        ):
            raise _conflict("WorkCodeSet revision must advance the existing set by one")

        session.execute(EOS_PROJECT_WORK_CODE_SET_TABLE.insert().values(**record))
        session.execute(
            EOS_PROJECT_WORK_CODE_ENTRY_TABLE.insert(),
            [
                {
                    "tenant_id": record["tenant_id"],
                    "project_id": record["project_id"],
                    "work_set_id": record["work_set_id"],
                    "work_set_revision": record["revision"],
                    "work_code_id": code_id,
                    "ordinal": index,
                    "mandatory": code_id in MANDATORY_D12_WORK_CODE_IDS,
                }
                for index, code_id in enumerate(code_ids, 1)
            ],
        )
        return _set_projection(record, code_ids)

    def approve(self, value: ProjectWorkCodeSetApproval) -> dict[str, Any]:
        try:
            with self._session_factory.begin() as session:
                return self.approve_in_session(session, value)
        except EosProjectWorkCodeError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "WorkCodeSet violates an identity or revision guard"
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_current_set(
        self, *, tenant_id: str, project_id: str, effective_on: date | None = None
    ) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        effective_on = _date("effective_on", effective_on or datetime.now(UTC).date())
        try:
            with self._session_factory() as session:
                header = self._latest_header(
                    session, tenant_id, project_id, effective_on=effective_on
                )
                if header is None:
                    return None
                return _set_projection(header, self._entry_ids(session, header))
        except EosProjectWorkCodeError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def evaluate_business_readiness(
        self, *, tenant_id: str, project_id: str, effective_on: date | None = None
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        effective_on = _date("effective_on", effective_on or datetime.now(UTC).date())
        try:
            with self._session_factory() as session:
                return self._evaluate_in_session(
                    session,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    effective_on=effective_on,
                )
        except EosProjectWorkCodeError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def require_project_role(
        self,
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

    def _evaluate_in_session(
        self,
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        effective_on: date,
    ) -> dict[str, Any]:
        project = (
            session.execute(
                select(EOS_PROJECT_TABLE).where(
                    EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                    EOS_PROJECT_TABLE.c.project_id == project_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if project is None:
            raise _not_found("Project was not found in tenant scope")

        header = self._latest_header(
            session, tenant_id, project_id, effective_on=effective_on
        )
        code_ids = self._entry_ids(session, header) if header is not None else ()
        required_codes_ok = (
            header is not None
            and header["catalog_id"] == D12_CATALOG_ID
            and header["catalog_version"] == D12_CATALOG_VERSION
            and header["catalog_digest"] == D12_CATALOG_DIGEST
            and header["mandatory_codes_hash"] == MANDATORY_D12_CODES_HASH
            and set(MANDATORY_D12_WORK_CODE_IDS).issubset(code_ids)
        )

        bindings = (
            session.execute(
                select(EOS_PROJECT_COMPANY_BINDING_TABLE.c.binding_id).where(
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.tenant_id == tenant_id,
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.project_id == project_id,
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.state == "APPROVED",
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_from <= effective_on,
                    (
                        EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until.is_(None)
                        | (
                            EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until
                            > effective_on
                        )
                    ),
                )
            )
            .scalars()
            .all()
        )
        project_company_bound = len(bindings) == 1
        pm_assigned = False
        members_eligible = False
        pa_identity_bound = False
        if header is not None:
            pm_assigned = (
                session.execute(
                    select(EOS_PROJECT_MEMBER_TABLE.c.project_membership_id).where(
                        EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id,
                        EOS_PROJECT_MEMBER_TABLE.c.project_id == project_id,
                        EOS_PROJECT_MEMBER_TABLE.c.subject_id
                        == header["pm_subject_id"],
                        EOS_PROJECT_MEMBER_TABLE.c.member_role == "MANAGER",
                        EOS_PROJECT_MEMBER_TABLE.c.status == "ACTIVE",
                    )
                ).scalar_one_or_none()
                is not None
            )
            members_eligible = (
                session.execute(
                    select(func.count())
                    .select_from(EOS_PROJECT_MEMBER_TABLE)
                    .where(
                        EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id,
                        EOS_PROJECT_MEMBER_TABLE.c.project_id == project_id,
                        EOS_PROJECT_MEMBER_TABLE.c.status == "ACTIVE",
                    )
                ).scalar_one()
                > 0
            )
            pa_identity_bound = (
                bool(header["pa_agent_id"])
                and header["pa_agent_id"] != header["pm_subject_id"]
            )

        reasons: list[str] = []
        if project["status"] != "ACTIVE":
            reasons.append("PROJECT_INACTIVE")
        if header is None:
            reasons.append("WORK_CODE_SET_MISSING")
        elif not required_codes_ok:
            reasons.append("MANDATORY_WORK_CODES_INVALID")
        if not project_company_bound:
            reasons.append(
                "PROJECT_COMPANY_BINDING_AMBIGUOUS"
                if len(bindings) > 1
                else "PROJECT_COMPANY_BINDING_MISSING"
            )
        if header is not None and not pm_assigned:
            reasons.append("PM_MEMBERSHIP_MISSING")
        if header is not None and not members_eligible:
            reasons.append("PROJECT_MEMBER_MISSING")
        if header is not None and not pa_identity_bound:
            reasons.append("PA_IDENTITY_MISSING_OR_CONFLICTING")

        ready = not reasons
        if ready:
            state = "BUSINESS_READY"
        elif project["status"] != "ACTIVE" or (
            header is not None and not required_codes_ok
        ):
            state = "BLOCKED"
        elif header is None:
            state = "DRAFT_CONFIGURATION"
        elif pm_assigned and members_eligible and pa_identity_bound:
            state = "MEMBER_READY"
        else:
            state = "WORK_SET_APPROVED"

        source = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "technical_status": project["status"],
            "work_set_hash": header["work_set_hash"] if header else None,
            "company_binding_ids": sorted(str(item) for item in bindings),
            "required_codes_ok": required_codes_ok,
            "project_company_bound": project_company_bound,
            "pm_assigned": pm_assigned,
            "members_eligible": members_eligible,
            "pa_identity_bound": pa_identity_bound,
            "effective_on": effective_on.isoformat(),
        }
        return {
            **source,
            "state": state,
            "business_ready": ready,
            "budget_bound_if_required": True,
            "reason_codes": reasons,
            "source_hash": semantic_sha256_hash_ref(
                {"domain": "EOS-PROJECT-BUSINESS-READINESS-V1", **source}
            ),
            "work_set": _set_projection(header, code_ids) if header else None,
        }

    @staticmethod
    def _set_by_identity(
        session: Session, record: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        return (
            session.execute(
                select(EOS_PROJECT_WORK_CODE_SET_TABLE).where(
                    EOS_PROJECT_WORK_CODE_SET_TABLE.c.tenant_id == record["tenant_id"],
                    EOS_PROJECT_WORK_CODE_SET_TABLE.c.project_id
                    == record["project_id"],
                    EOS_PROJECT_WORK_CODE_SET_TABLE.c.work_set_id
                    == record["work_set_id"],
                    EOS_PROJECT_WORK_CODE_SET_TABLE.c.revision == record["revision"],
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _latest_header(
        session: Session,
        tenant_id: str,
        project_id: str,
        *,
        effective_on: date | None = None,
    ) -> Mapping[str, Any] | None:
        statement = select(EOS_PROJECT_WORK_CODE_SET_TABLE).where(
            EOS_PROJECT_WORK_CODE_SET_TABLE.c.tenant_id == tenant_id,
            EOS_PROJECT_WORK_CODE_SET_TABLE.c.project_id == project_id,
            EOS_PROJECT_WORK_CODE_SET_TABLE.c.state == "APPROVED",
        )
        if effective_on is not None:
            statement = statement.where(
                EOS_PROJECT_WORK_CODE_SET_TABLE.c.effective_from <= effective_on
            )
        return (
            session.execute(
                statement.order_by(
                    EOS_PROJECT_WORK_CODE_SET_TABLE.c.revision.desc()
                ).limit(1)
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _entry_ids(
        session: Session, header: Mapping[str, Any] | None
    ) -> tuple[str, ...]:
        if header is None:
            return ()
        return tuple(
            session.execute(
                select(EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.work_code_id)
                .where(
                    EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.tenant_id
                    == header["tenant_id"],
                    EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.project_id
                    == header["project_id"],
                    EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.work_set_id
                    == header["work_set_id"],
                    EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.work_set_revision
                    == header["revision"],
                )
                .order_by(EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.ordinal)
            ).scalars()
        )


class EosProjectBusinessService:
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
        self._repository = SqlAlchemyEosProjectWorkCodeRepository(session_factory)

    def approve_work_code_set(
        self, payload: Mapping[str, Any], *, caller: EosServiceCaller
    ) -> dict[str, Any]:
        _require_service_caller(caller)
        envelope = _write_envelope(payload)
        requester = _scoped_id(
            "requester_subject_id", payload.get("requester_subject_id")
        )
        project_id = _uuid("project_id", payload.get("project_id"))
        work_set = _object("work_set", payload.get("work_set"))
        authorization = self._authorize(
            tenant_id=envelope["tenant_id"],
            subject_id=requester,
            required_scope=PROJECT_WORK_CODE_APPROVE_SCOPE,
            project_id=project_id,
        )
        pm_subject_id = _scoped_id("pm_subject_id", work_set.get("pm_subject_id"))
        self._require_active_subject(envelope["tenant_id"], pm_subject_id)
        approval = ProjectWorkCodeSetApproval(
            tenant_id=envelope["tenant_id"],
            project_id=project_id,
            work_set_id=work_set.get("work_set_id"),
            revision=work_set.get("revision"),
            catalog_id=work_set.get("catalog_id"),
            catalog_version=work_set.get("catalog_version"),
            catalog_digest=work_set.get("catalog_digest"),
            template_ref=work_set.get("template_ref"),
            template_version=work_set.get("template_version"),
            code_ids=_code_ids(work_set.get("code_ids")),
            approved_proof_hash=work_set.get("approved_proof_hash"),
            approved_by_subject_id=requester,
            pm_subject_id=pm_subject_id,
            pa_agent_id=work_set.get("pa_agent_id"),
            pa_identity_evidence_hash=work_set.get("pa_identity_evidence_hash"),
            effective_from=_date_input(
                "effective_from", work_set.get("effective_from")
            ),
        )

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise RuntimeError(
                    "WorkCodeSet approval requires a database transaction"
                )
            self._repository.require_project_role(
                session,
                tenant_id=envelope["tenant_id"],
                project_id=project_id,
                subject_id=requester,
                roles=frozenset({"OWNER", "MANAGER"}),
            )
            approved = self._repository.approve_in_session(session, approval)
            return {
                "business_result_ref": (
                    f"eos.project-work-set:{project_id}:{approved['revision']}"
                ),
                "work_set": approved,
                "authorization_revision_hash": authorization["revision_hash"],
            }

        requested_operation = envelope.pop("requested_operation")

        def admitted_mutation(session: Session | None) -> Mapping[str, Any]:
            try:
                return {
                    **mutation(session),
                    "requested_operation": requested_operation,
                    "canonical_operation": PROJECT_WORK_CODE_SET_APPROVE_OPERATION,
                }
            except EosProjectWorkCodeError as exc:
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
            raise EosProjectWorkCodeError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        return result.to_public_projection()

    def get_work_code_set(
        self,
        *,
        tenant_id: str,
        project_id: str,
        requester_subject_id: str,
        effective_on: date | None = None,
    ) -> dict[str, Any]:
        tenant_id, project_id, requester_subject_id = self._read_scope(
            tenant_id, project_id, requester_subject_id
        )
        found = self._repository.get_current_set(
            tenant_id=tenant_id, project_id=project_id, effective_on=effective_on
        )
        if found is None:
            raise _not_found("Project has no effective approved WorkCodeSet")
        return found

    def get_business_readiness(
        self,
        *,
        tenant_id: str,
        project_id: str,
        requester_subject_id: str,
        effective_on: date | None = None,
    ) -> dict[str, Any]:
        tenant_id, project_id, _requester = self._read_scope(
            tenant_id, project_id, requester_subject_id
        )
        return self._repository.evaluate_business_readiness(
            tenant_id=tenant_id, project_id=project_id, effective_on=effective_on
        )

    def _read_scope(
        self, tenant_id: str, project_id: str, requester_subject_id: str
    ) -> tuple[str, str, str]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        requester = _scoped_id("requester_subject_id", requester_subject_id)
        authorization = self._authorize(
            tenant_id=tenant_id,
            subject_id=requester,
            required_scope=PROJECT_WORK_CODE_READ_SCOPE,
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
            except EosProjectWorkCodeError:
                raise
            except SQLAlchemyError as exc:
                raise _unavailable() from exc
        return tenant_id, project_id, requester

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
            raise EosProjectWorkCodeError(
                "EOS_PROJECT_WORK_CODE_AUTHORIZATION_UNAVAILABLE",
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
            and required_scope == PROJECT_WORK_CODE_APPROVE_SCOPE
        ):
            try:
                self._project_authorizer.authorize(
                    tenant_id=tenant_id,
                    subject_id=subject_id,
                    project_id=project_id,
                    action=required_scope,
                    correlation_id=f"eos-work-code:{subject_id}:{project_id}",
                )
            except EosProjectAuthorizationError as exc:
                raise EosProjectWorkCodeError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc
        return admitted

    def _require_active_subject(self, tenant_id: str, subject_id: str) -> None:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id, subject_id=subject_id
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied("The designated PM is inactive") from exc
        except Exception as exc:
            raise EosProjectWorkCodeError(
                "EOS_PROJECT_WORK_CODE_AUTHORIZATION_UNAVAILABLE",
                "OA PM status is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        _admit_authorization(
            value,
            tenant_id=tenant_id,
            subject_id=subject_id,
            required_scope=None,
            project_id=None,
        )


def project_work_code_set_payload_hash(payload: Mapping[str, Any]) -> str:
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
        {"operation": PROJECT_WORK_CODE_SET_APPROVE_OPERATION, **projected}
    )


def _write_envelope(payload: Mapping[str, Any]) -> dict[str, str]:
    requested = payload.get(
        "requested_operation", PROJECT_WORK_CODE_SET_APPROVE_OPERATION
    )
    try:
        resolution = DEFAULT_OPERATION_REGISTRY.resolve(requested)
    except OperationNameError as exc:
        raise _invalid("requested_operation is not admitted") from exc
    if resolution.canonical_operation != PROJECT_WORK_CODE_SET_APPROVE_OPERATION:
        raise _invalid("requested_operation does not match the route operation")
    supplied_hash = _text("payload_hash", payload.get("payload_hash"), 256)
    if supplied_hash != project_work_code_set_payload_hash(payload):
        raise EosProjectWorkCodeError(
            "EOS_PROJECT_WORK_CODE_PAYLOAD_HASH_MISMATCH",
            "Canonical WorkCodeSet payload hash does not match",
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
        "operation": PROJECT_WORK_CODE_SET_APPROVE_OPERATION,
        "payload_hash": supplied_hash,
        "requested_operation": resolution.requested_operation,
    }


def _approval_record(
    value: ProjectWorkCodeSetApproval,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    if not isinstance(value, ProjectWorkCodeSetApproval):
        raise _invalid("value must be ProjectWorkCodeSetApproval")
    if (
        value.catalog_id != D12_CATALOG_ID
        or value.catalog_version != D12_CATALOG_VERSION
        or value.catalog_digest != D12_CATALOG_DIGEST
    ):
        raise _conflict("WorkCodeSet catalog identity is not admitted")
    code_ids = _code_ids(value.code_ids)
    missing = sorted(set(MANDATORY_D12_WORK_CODE_IDS) - set(code_ids))
    if missing:
        raise _conflict("Mandatory D12 work codes are missing: " + ", ".join(missing))
    pm_subject_id = _scoped_id("pm_subject_id", value.pm_subject_id)
    pa_agent_id = _scoped_id("pa_agent_id", value.pa_agent_id)
    if pm_subject_id == pa_agent_id:
        raise _conflict("Human PM and Project Agent identities must be distinct")
    semantics = {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "project_id": _uuid("project_id", value.project_id),
        "work_set_id": _uuid("work_set_id", value.work_set_id),
        "revision": _positive_int("revision", value.revision),
        "catalog_id": value.catalog_id,
        "catalog_version": value.catalog_version,
        "catalog_digest": _hash_ref("catalog_digest", value.catalog_digest),
        "template_ref": _text("template_ref", value.template_ref, 256),
        "template_version": _semver("template_version", value.template_version),
        "mandatory_codes_hash": MANDATORY_D12_CODES_HASH,
        "approved_proof_hash": _hash_ref(
            "approved_proof_hash", value.approved_proof_hash
        ),
        "approved_by_subject_id": _scoped_id(
            "approved_by_subject_id", value.approved_by_subject_id
        ),
        "pm_subject_id": pm_subject_id,
        "pa_agent_id": pa_agent_id,
        "pa_identity_evidence_hash": _hash_ref(
            "pa_identity_evidence_hash", value.pa_identity_evidence_hash
        ),
        "state": "APPROVED",
        "effective_from": _date("effective_from", value.effective_from),
    }
    hash_values = {
        **semantics,
        "effective_from": semantics["effective_from"].isoformat(),
        "code_ids": list(code_ids),
    }
    return {
        **semantics,
        "work_set_hash": semantic_sha256_hash_ref(
            {"domain": "EOS-PROJECT-WORK-CODE-SET-V1", **hash_values}
        ),
        "created_at": datetime.now(UTC),
    }, code_ids


def _set_projection(
    header: Mapping[str, Any], code_ids: Sequence[str]
) -> dict[str, Any]:
    return {
        **{
            key: _wire_value(value)
            for key, value in header.items()
            if key != "created_at"
        },
        "created_at": _wire_value(header["created_at"]),
        "code_ids": list(code_ids),
    }


def _set_semantics(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        _wire_value(value[field])
        for field in (
            "tenant_id",
            "project_id",
            "work_set_id",
            "revision",
            "catalog_id",
            "catalog_version",
            "catalog_digest",
            "template_ref",
            "template_version",
            "mandatory_codes_hash",
            "approved_proof_hash",
            "approved_by_subject_id",
            "pm_subject_id",
            "pa_agent_id",
            "pa_identity_evidence_hash",
            "state",
            "effective_from",
            "work_set_hash",
        )
    )


def _admit_authorization(
    value: object,
    *,
    tenant_id: str,
    subject_id: str,
    required_scope: str | None,
    project_id: str | None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("active") is not True:
        raise _denied("Active OA authority is required")
    if value.get("tenant_id") != tenant_id or value.get("subject_id") != subject_id:
        raise _denied("OA tenant and subject scope do not match")
    scopes = _string_set(value.get("scopes"))
    if required_scope is not None and required_scope not in scopes:
        raise _denied(f"Current {required_scope} authorization was denied")
    revision_hash = value.get("revision_hash")
    if (
        not isinstance(revision_hash, str)
        or _REVISION_HASH.fullmatch(revision_hash) is None
    ):
        raise _denied("OA authorization revision is invalid")
    project_ids = value.get("project_ids")
    if (
        project_id is not None
        and project_ids is not None
        and project_id not in _string_set(project_ids)
    ):
        raise _denied("OA Project scope does not include the target Project")
    return {"scopes": scopes, "revision_hash": revision_hash}


def _require_service_caller(value: object) -> None:
    if (
        not isinstance(value, EosServiceCaller)
        or value.audience != "nex-eos"
        or "service:call" not in value.scopes
    ):
        raise _denied("Authenticated nex-eos service trust is required")


def _code_ids(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("code_ids must be an array")
    codes = tuple(str(item) for item in value)
    if not 1 <= len(codes) <= 100 or any(
        _WORK_CODE.fullmatch(item) is None for item in codes
    ):
        raise _invalid("code_ids must contain 1..100 canonical FL work codes")
    if len(set(codes)) != len(codes):
        raise _invalid("code_ids must not contain duplicates")
    if codes != tuple(sorted(codes, key=lambda item: item.encode("utf-8"))):
        raise _invalid("code_ids must use canonical byte order")
    return codes


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


def _text(field: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(f"{field} must contain 1..{maximum} characters")
    return normalized


def _semver(field: str, value: object) -> str:
    normalized = _text(field, value, 32)
    if _SEMVER.fullmatch(normalized) is None:
        raise _invalid(f"{field} must use semantic version syntax")
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


def _wire_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _conflict(detail: str) -> EosProjectWorkCodeError:
    return EosProjectWorkCodeError(
        "EOS_PROJECT_WORK_CODE_CONFLICT", detail, status_code=409
    )


def _not_found(detail: str) -> EosProjectWorkCodeError:
    return EosProjectWorkCodeError(
        "EOS_PROJECT_WORK_CODE_NOT_FOUND", detail, status_code=404
    )


def _denied(detail: str) -> EosProjectWorkCodeError:
    return EosProjectWorkCodeError(
        "EOS_PROJECT_WORK_CODE_AUTHORIZATION_DENIED", detail, status_code=403
    )


def _invalid(detail: str) -> EosProjectWorkCodeError:
    return EosProjectWorkCodeError(
        "EOS_PROJECT_WORK_CODE_INVALID", detail, status_code=422
    )


def _unavailable() -> EosProjectWorkCodeError:
    return EosProjectWorkCodeError(
        "EOS_PROJECT_WORK_CODE_PERSISTENCE_UNAVAILABLE",
        "Project WorkCodeSet persistence is unavailable",
        status_code=503,
        retryable=True,
    )
