from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_transactions import EOS_METADATA
from .projects import (
    EOS_NVT_PROJECT_TABLE,
    EOS_PROJECT_TABLE,
    SqlAlchemyEosProjectRepository,
)

PROJECT_APPLICATION_CREATE_SCOPE = "project:application:create"
PROJECT_APPLICATION_READ_SCOPE = "project:application:read"
PROJECT_APPLICATION_SUBMIT_SCOPE = "project:application:submit"
PROJECT_REFERENCE_RESOLVE_SCOPE = "project:project:read"

PROJECT_APPLICATION_CREATE_OPERATION = "PROJECT.APPLICATION.CREATE"
PROJECT_APPLICATION_REVISE_OPERATION = "PROJECT.APPLICATION.REVISE"
PROJECT_APPLICATION_SUBMIT_OPERATION = "PROJECT.APPLICATION.SUBMIT"
PROJECT_APPLICATION_GET_OPERATION = "PROJECT.APPLICATION.GET"
PROJECT_REFERENCE_RESOLVE_OPERATION = "PROJECT.PROJECT.RESOLVE"

PROJECT_PURPOSE_TYPES = frozenset({"D", "M", "S", "O", "I", "G"})
PROJECT_APPLICATION_STATES = frozenset({"DRAFT", "SUBMITTED", "APPROVED", "REJECTED"})
PROJECT_CODE_KINDS = frozenset({"REQUEST", "REGISTRATION"})
PROJECT_SERIAL_MIN = 1
PROJECT_SERIAL_MAX = 9999

_SEOUL = ZoneInfo("Asia/Seoul")
_TENANT_CODE = re.compile(r"^[A-Z0-9]{4}$")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_REQUEST_CODE = re.compile(r"^[A-Z0-9]{4}R[0-9]{6}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


EOS_PROJECT_CODE_COUNTER_TABLE = Table(
    "eos_project_code_counter",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("tenant_code", String(4), nullable=False),
    Column("code_kind", String(16), primary_key=True),
    Column("purpose_type", String(1), primary_key=True),
    Column("code_year", Integer, primary_key=True),
    Column("last_serial", Integer, nullable=False),
    Column("version", Integer, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_code",
        "code_kind",
        "purpose_type",
        "code_year",
        name="ux_eos_project_counter_code_scope",
    ),
    CheckConstraint(
        "code_kind IN ('REQUEST', 'REGISTRATION')",
        name="ck_eos_project_counter_kind",
    ),
    CheckConstraint(
        "(code_kind = 'REQUEST' AND purpose_type = 'R') OR "
        "(code_kind = 'REGISTRATION' AND purpose_type IN ('D', 'M', 'S', 'O', 'I', 'G'))",
        name="ck_eos_project_counter_purpose",
    ),
    CheckConstraint("code_year BETWEEN 0 AND 99", name="ck_eos_project_counter_year"),
    CheckConstraint(
        "last_serial BETWEEN 1 AND 9999", name="ck_eos_project_counter_serial"
    ),
    CheckConstraint("version > 0", name="ck_eos_project_counter_version"),
)

EOS_PROJECT_APPLICATION_TABLE = Table(
    "eos_project_application",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("application_id", Uuid(as_uuid=False), primary_key=True),
    Column("tenant_code", String(4), nullable=False),
    Column("code_year", Integer, nullable=False),
    Column("project_request_code", String(11), nullable=False),
    Column("purpose_type", String(1), nullable=False),
    Column("state", String(16), nullable=False),
    Column("applicant_subject_id", String(128), nullable=False),
    Column("current_revision", Integer, nullable=False),
    Column("approved_project_id", Uuid(as_uuid=False), nullable=True),
    Column("approved_project_code", String(64), nullable=True),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("submitted_at", DateTime(timezone=True), nullable=True),
    Column("decided_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint(
        "tenant_id",
        "project_request_code",
        name="ux_eos_project_application_request",
    ),
    UniqueConstraint(
        "project_request_code", name="ux_eos_project_application_code_global"
    ),
    CheckConstraint(
        "length(tenant_code) = 4", name="ck_eos_project_application_tenant_code"
    ),
    CheckConstraint(
        "length(project_request_code) = 11",
        name="ck_eos_project_application_request_code",
    ),
    CheckConstraint(
        "purpose_type IN ('D', 'M', 'S', 'O', 'I', 'G')",
        name="ck_eos_project_application_purpose",
    ),
    CheckConstraint(
        "state IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED')",
        name="ck_eos_project_application_state",
    ),
    CheckConstraint("current_revision > 0", name="ck_eos_project_application_revision"),
    CheckConstraint("version > 0", name="ck_eos_project_application_version"),
)
Index(
    "ix_eos_project_application_state",
    EOS_PROJECT_APPLICATION_TABLE.c.tenant_id,
    EOS_PROJECT_APPLICATION_TABLE.c.state,
    EOS_PROJECT_APPLICATION_TABLE.c.updated_at,
    EOS_PROJECT_APPLICATION_TABLE.c.application_id,
)

EOS_PROJECT_APP_REVISION_TABLE = Table(
    "eos_project_app_revision",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("application_id", Uuid(as_uuid=False), primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("request_hash", String(71), nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("created_by_subject_id", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "application_id",
        "request_hash",
        name="ux_eos_project_app_revision_hash",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "application_id"),
        (
            "eos_project_application.tenant_id",
            "eos_project_application.application_id",
        ),
        name="fk_eos_project_app_revision",
    ),
    CheckConstraint("revision > 0", name="ck_eos_project_app_revision_number"),
    CheckConstraint(
        "length(request_hash) = 71", name="ck_eos_project_app_revision_hash"
    ),
)


class EosProjectApplicationError(RuntimeError):
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
class ProjectApplicationDraft:
    tenant_id: str
    application_id: str
    purpose_type: str
    applicant_subject_id: str
    name: str
    parent_project_id: str | None = None
    nvt_project_id: str | None = None
    company_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    currency: str = "KRW"


class SqlAlchemyEosProjectApplicationRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_draft(
        self,
        value: ProjectApplicationDraft,
        *,
        issued_at: datetime | None = None,
    ) -> dict[str, Any]:
        payload = _draft_payload(value)
        request_hash = semantic_sha256_hash_ref(payload)
        tenant_id = payload["tenant_id"]
        application_id = payload["application_id"]
        try:
            with self._session_factory.begin() as session:
                existing = self._application_by_id(
                    session,
                    tenant_id=tenant_id,
                    application_id=application_id,
                    for_update=True,
                )
                if existing is not None:
                    current = self._projection(session, existing)
                    if (
                        current["request_hash"] == request_hash
                        and current["applicant_subject_id"]
                        == payload["applicant_subject_id"]
                    ):
                        return current
                    raise _conflict(
                        "Project application identity has different semantics"
                    )
                self._require_hierarchy_target(session, payload)
                instant = _instant(issued_at)
                year = instant.astimezone(_SEOUL).year % 100
                request_code = self._allocate_code_in_session(
                    session,
                    tenant_id=tenant_id,
                    tenant_code=payload["tenant_code"],
                    code_kind="REQUEST",
                    purpose_type="R",
                    code_year=year,
                    now=instant,
                )
                record = {
                    "tenant_id": tenant_id,
                    "application_id": application_id,
                    "tenant_code": payload["tenant_code"],
                    "code_year": year,
                    "project_request_code": request_code,
                    "purpose_type": payload["purpose_type"],
                    "state": "DRAFT",
                    "applicant_subject_id": payload["applicant_subject_id"],
                    "current_revision": 1,
                    "approved_project_id": None,
                    "approved_project_code": None,
                    "version": 1,
                    "created_at": instant,
                    "updated_at": instant,
                    "submitted_at": None,
                    "decided_at": None,
                }
                session.execute(EOS_PROJECT_APPLICATION_TABLE.insert().values(**record))
                self._insert_revision(
                    session,
                    record=record,
                    payload=payload,
                    request_hash=request_hash,
                    actor_subject_id=payload["applicant_subject_id"],
                    created_at=instant,
                )
                return {
                    **_wire(record),
                    "request_hash": request_hash,
                    "payload": payload,
                }
        except EosProjectApplicationError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "Project application identity, request code, or revision conflicts"
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def revise_draft(
        self,
        value: ProjectApplicationDraft,
        *,
        expected_version: int,
        actor_subject_id: str,
    ) -> dict[str, Any]:
        payload = _draft_payload(value)
        request_hash = semantic_sha256_hash_ref(payload)
        actor = _scoped_id("actor_subject_id", actor_subject_id)
        expected = _positive_int("expected_version", expected_version)
        try:
            with self._session_factory.begin() as session:
                current = self._required_application(
                    session,
                    tenant_id=payload["tenant_id"],
                    application_id=payload["application_id"],
                    for_update=True,
                )
                self._require_applicant(current, actor)
                if current["state"] != "DRAFT":
                    raise _conflict("Only a DRAFT Project application can be revised")
                if int(current["version"]) != expected:
                    raise _version_conflict()
                current_projection = self._projection(session, current)
                if current_projection["request_hash"] == request_hash:
                    return current_projection
                self._require_hierarchy_target(session, payload)
                now = datetime.now(UTC)
                revision = int(current["current_revision"]) + 1
                changed = {
                    "purpose_type": payload["purpose_type"],
                    "current_revision": revision,
                    "version": expected + 1,
                    "updated_at": now,
                }
                result = session.execute(
                    update(EOS_PROJECT_APPLICATION_TABLE)
                    .where(
                        EOS_PROJECT_APPLICATION_TABLE.c.tenant_id
                        == payload["tenant_id"],
                        EOS_PROJECT_APPLICATION_TABLE.c.application_id
                        == payload["application_id"],
                        EOS_PROJECT_APPLICATION_TABLE.c.version == expected,
                    )
                    .values(**changed)
                )
                if result.rowcount != 1:
                    raise _version_conflict()
                updated = {**dict(current), **changed}
                self._insert_revision(
                    session,
                    record=updated,
                    payload=payload,
                    request_hash=request_hash,
                    actor_subject_id=actor,
                    created_at=now,
                )
                return {
                    **_wire(updated),
                    "request_hash": request_hash,
                    "payload": payload,
                }
        except EosProjectApplicationError:
            raise
        except IntegrityError as exc:
            raise _conflict("Project application revision conflicts") from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def submit(
        self,
        *,
        tenant_id: str,
        project_request_code: str,
        expected_version: int,
        actor_subject_id: str,
    ) -> dict[str, Any]:
        tenant_id = _tenant_code(tenant_id)
        request_code = _request_code(project_request_code)
        actor = _scoped_id("actor_subject_id", actor_subject_id)
        expected = _positive_int("expected_version", expected_version)
        try:
            with self._session_factory.begin() as session:
                current = self._required_by_request_code(
                    session,
                    tenant_id=tenant_id,
                    request_code=request_code,
                    for_update=True,
                )
                self._require_applicant(current, actor)
                if (
                    current["state"] == "SUBMITTED"
                    and int(current["version"]) == expected + 1
                ):
                    return self._projection(session, current)
                if current["state"] != "DRAFT":
                    raise _conflict("Only a DRAFT Project application can be submitted")
                if int(current["version"]) != expected:
                    raise _version_conflict()
                now = datetime.now(UTC)
                changed = {
                    "state": "SUBMITTED",
                    "version": expected + 1,
                    "submitted_at": now,
                    "updated_at": now,
                }
                result = session.execute(
                    update(EOS_PROJECT_APPLICATION_TABLE)
                    .where(
                        EOS_PROJECT_APPLICATION_TABLE.c.tenant_id == tenant_id,
                        EOS_PROJECT_APPLICATION_TABLE.c.application_id
                        == current["application_id"],
                        EOS_PROJECT_APPLICATION_TABLE.c.version == expected,
                    )
                    .values(**changed)
                )
                if result.rowcount != 1:
                    raise _version_conflict()
                return self._projection(session, {**dict(current), **changed})
        except EosProjectApplicationError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_by_request_code(
        self, *, tenant_id: str, project_request_code: str
    ) -> dict[str, Any] | None:
        tenant_id = _tenant_code(tenant_id)
        request_code = _request_code(project_request_code)
        try:
            with self._session_factory() as session:
                row = self._application_by_request_code(
                    session,
                    tenant_id=tenant_id,
                    request_code=request_code,
                )
                return self._projection(session, row) if row is not None else None
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def allocate_registration_code(
        self,
        *,
        tenant_id: str,
        purpose_type: str,
        issued_at: datetime | None = None,
    ) -> str:
        tenant_id = _tenant_code(tenant_id)
        purpose = _purpose_type(purpose_type)
        instant = _instant(issued_at)
        year = instant.astimezone(_SEOUL).year % 100
        try:
            with self._session_factory.begin() as session:
                return self._allocate_code_in_session(
                    session,
                    tenant_id=tenant_id,
                    tenant_code=tenant_id,
                    code_kind="REGISTRATION",
                    purpose_type=purpose,
                    code_year=year,
                    now=instant,
                )
        except EosProjectApplicationError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def allocate_registration_code_in_session(
        self,
        session: Session,
        *,
        tenant_id: str,
        purpose_type: str,
        issued_at: datetime | None = None,
    ) -> str:
        """Allocate the S00B registration code in its approval transaction."""

        tenant_id = _tenant_code(tenant_id)
        purpose = _purpose_type(purpose_type)
        instant = _instant(issued_at)
        return self._allocate_code_in_session(
            session,
            tenant_id=tenant_id,
            tenant_code=tenant_id,
            code_kind="REGISTRATION",
            purpose_type=purpose,
            code_year=instant.astimezone(_SEOUL).year % 100,
            now=instant,
        )

    @staticmethod
    def _allocate_code_in_session(
        session: Session,
        *,
        tenant_id: str,
        tenant_code: str,
        code_kind: str,
        purpose_type: str,
        code_year: int,
        now: datetime,
    ) -> str:
        values = {
            "tenant_id": tenant_id,
            "tenant_code": tenant_code,
            "code_kind": code_kind,
            "purpose_type": purpose_type,
            "code_year": code_year,
            "last_serial": PROJECT_SERIAL_MIN,
            "version": 1,
            "updated_at": now,
        }
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            statement = postgresql_insert(EOS_PROJECT_CODE_COUNTER_TABLE).values(
                **values
            )
        elif dialect == "sqlite":
            statement = sqlite_insert(EOS_PROJECT_CODE_COUNTER_TABLE).values(**values)
        else:
            return SqlAlchemyEosProjectApplicationRepository._allocate_locked_fallback(
                session, values
            )
        statement = statement.on_conflict_do_update(
            index_elements=[
                "tenant_id",
                "code_kind",
                "purpose_type",
                "code_year",
            ],
            set_={
                "last_serial": EOS_PROJECT_CODE_COUNTER_TABLE.c.last_serial + 1,
                "version": EOS_PROJECT_CODE_COUNTER_TABLE.c.version + 1,
                "updated_at": now,
            },
            where=EOS_PROJECT_CODE_COUNTER_TABLE.c.last_serial < PROJECT_SERIAL_MAX,
        ).returning(EOS_PROJECT_CODE_COUNTER_TABLE.c.last_serial)
        serial = session.execute(statement).scalar_one_or_none()
        if serial is None:
            raise EosProjectApplicationError(
                "EOS_PROJECT_CODE_EXHAUSTED",
                "Project code serial range 0001..9999 is exhausted for the year",
                status_code=409,
            )
        return _format_code(
            tenant_code=tenant_code,
            code_kind=code_kind,
            purpose_type=purpose_type,
            code_year=code_year,
            serial=int(serial),
        )

    @staticmethod
    def _allocate_locked_fallback(session: Session, values: Mapping[str, Any]) -> str:
        key = {
            field: values[field]
            for field in ("tenant_id", "code_kind", "purpose_type", "code_year")
        }
        current = (
            session.execute(
                select(EOS_PROJECT_CODE_COUNTER_TABLE)
                .where(
                    *(
                        EOS_PROJECT_CODE_COUNTER_TABLE.c[field] == item
                        for field, item in key.items()
                    )
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if current is None:
            session.execute(EOS_PROJECT_CODE_COUNTER_TABLE.insert().values(**values))
            serial = 1
        else:
            serial = int(current["last_serial"]) + 1
            if serial > PROJECT_SERIAL_MAX:
                raise EosProjectApplicationError(
                    "EOS_PROJECT_CODE_EXHAUSTED",
                    "Project code serial range 0001..9999 is exhausted for the year",
                    status_code=409,
                )
            session.execute(
                update(EOS_PROJECT_CODE_COUNTER_TABLE)
                .where(
                    *(
                        EOS_PROJECT_CODE_COUNTER_TABLE.c[field] == item
                        for field, item in key.items()
                    )
                )
                .values(
                    last_serial=serial,
                    version=int(current["version"]) + 1,
                    updated_at=values["updated_at"],
                )
            )
        return _format_code(
            tenant_code=str(values["tenant_code"]),
            code_kind=str(values["code_kind"]),
            purpose_type=str(values["purpose_type"]),
            code_year=int(values["code_year"]),
            serial=serial,
        )

    @staticmethod
    def _insert_revision(
        session: Session,
        *,
        record: Mapping[str, Any],
        payload: Mapping[str, Any],
        request_hash: str,
        actor_subject_id: str,
        created_at: datetime,
    ) -> None:
        session.execute(
            EOS_PROJECT_APP_REVISION_TABLE.insert().values(
                tenant_id=record["tenant_id"],
                application_id=record["application_id"],
                revision=record["current_revision"],
                request_hash=request_hash,
                payload_json=canonical_json(payload),
                created_by_subject_id=actor_subject_id,
                created_at=created_at,
            )
        )

    @staticmethod
    def _application_by_id(
        session: Session,
        *,
        tenant_id: str,
        application_id: str,
        for_update: bool = False,
    ) -> Mapping[str, Any] | None:
        statement = select(EOS_PROJECT_APPLICATION_TABLE).where(
            EOS_PROJECT_APPLICATION_TABLE.c.tenant_id == tenant_id,
            EOS_PROJECT_APPLICATION_TABLE.c.application_id == application_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return session.execute(statement).mappings().one_or_none()

    @staticmethod
    def _application_by_request_code(
        session: Session,
        *,
        tenant_id: str,
        request_code: str,
        for_update: bool = False,
    ) -> Mapping[str, Any] | None:
        statement = select(EOS_PROJECT_APPLICATION_TABLE).where(
            EOS_PROJECT_APPLICATION_TABLE.c.tenant_id == tenant_id,
            EOS_PROJECT_APPLICATION_TABLE.c.project_request_code == request_code,
        )
        if for_update:
            statement = statement.with_for_update()
        return session.execute(statement).mappings().one_or_none()

    def _required_application(
        self, session: Session, **kwargs: Any
    ) -> Mapping[str, Any]:
        row = self._application_by_id(session, **kwargs)
        if row is None:
            raise _not_found()
        return row

    def _required_by_request_code(
        self, session: Session, **kwargs: Any
    ) -> Mapping[str, Any]:
        row = self._application_by_request_code(session, **kwargs)
        if row is None:
            raise _not_found()
        return row

    @staticmethod
    def _projection(session: Session, record: Mapping[str, Any]) -> dict[str, Any]:
        revision = (
            session.execute(
                select(EOS_PROJECT_APP_REVISION_TABLE).where(
                    EOS_PROJECT_APP_REVISION_TABLE.c.tenant_id == record["tenant_id"],
                    EOS_PROJECT_APP_REVISION_TABLE.c.application_id
                    == record["application_id"],
                    EOS_PROJECT_APP_REVISION_TABLE.c.revision
                    == record["current_revision"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if revision is None:
            raise EosProjectApplicationError(
                "EOS_PROJECT_APPLICATION_CORRUPT",
                "Project application current revision is missing",
                status_code=503,
                retryable=True,
            )
        return {
            **_wire(record),
            "request_hash": revision["request_hash"],
            "payload": json.loads(revision["payload_json"]),
        }

    @staticmethod
    def _require_applicant(record: Mapping[str, Any], actor: str) -> None:
        if record["applicant_subject_id"] != actor:
            raise EosProjectApplicationError(
                "EOS_PROJECT_APPLICATION_OWNER_DENIED",
                "Only the Project applicant can change this application",
                status_code=403,
            )

    @staticmethod
    def _require_hierarchy_target(session: Session, payload: Mapping[str, Any]) -> None:
        tenant_id = str(payload["tenant_id"])
        parent_project_id = payload["parent_project_id"]
        nvt_project_id = payload["nvt_project_id"]
        if parent_project_id is not None:
            found = session.execute(
                select(EOS_PROJECT_TABLE.c.status).where(
                    EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                    EOS_PROJECT_TABLE.c.project_id == parent_project_id,
                )
            ).scalar_one_or_none()
            if found is None:
                raise EosProjectApplicationError(
                    "EOS_PROJECT_PARENT_NOT_FOUND",
                    "Parent Project was not found in tenant scope",
                    status_code=404,
                )
            if found != "ACTIVE":
                raise _conflict("Parent Project must be ACTIVE")
            return
        found = session.execute(
            select(EOS_NVT_PROJECT_TABLE.c.status).where(
                EOS_NVT_PROJECT_TABLE.c.tenant_id == tenant_id,
                EOS_NVT_PROJECT_TABLE.c.nvt_project_id == nvt_project_id,
            )
        ).scalar_one_or_none()
        if found is None:
            raise EosProjectApplicationError(
                "EOS_NVT_PROJECT_NOT_FOUND",
                "NVTProject was not found in tenant scope",
                status_code=404,
            )
        if found != "ACTIVE":
            raise _conflict("NVTProject must be ACTIVE")


class EosProjectApplicationService:
    def __init__(
        self,
        repository: SqlAlchemyEosProjectApplicationRepository,
        authorization_source: AuthorizationSource,
        projects: SqlAlchemyEosProjectRepository,
    ) -> None:
        self._repository = repository
        self._authorization_source = authorization_source
        self._projects = projects

    def create_draft(
        self, value: ProjectApplicationDraft, *, requester_subject_id: str
    ) -> dict[str, Any]:
        requester = _scoped_id("requester_subject_id", requester_subject_id)
        if requester != _scoped_id("applicant_subject_id", value.applicant_subject_id):
            raise EosProjectApplicationError(
                "EOS_PROJECT_APPLICATION_APPLICANT_MISMATCH",
                "Requester must be the Project applicant",
                status_code=403,
            )
        self._authorize(value.tenant_id, requester, PROJECT_APPLICATION_CREATE_SCOPE)
        return self._repository.create_draft(value)

    def revise_draft(
        self,
        value: ProjectApplicationDraft,
        *,
        expected_version: int,
        requester_subject_id: str,
    ) -> dict[str, Any]:
        requester = _scoped_id("requester_subject_id", requester_subject_id)
        self._authorize(value.tenant_id, requester, PROJECT_APPLICATION_CREATE_SCOPE)
        return self._repository.revise_draft(
            value,
            expected_version=expected_version,
            actor_subject_id=requester,
        )

    def submit(
        self,
        *,
        tenant_id: str,
        project_request_code: str,
        expected_version: int,
        requester_subject_id: str,
    ) -> dict[str, Any]:
        requester = _scoped_id("requester_subject_id", requester_subject_id)
        self._authorize(tenant_id, requester, PROJECT_APPLICATION_SUBMIT_SCOPE)
        return self._repository.submit(
            tenant_id=tenant_id,
            project_request_code=project_request_code,
            expected_version=expected_version,
            actor_subject_id=requester,
        )

    def get_application(
        self,
        *,
        tenant_id: str,
        project_request_code: str,
        requester_subject_id: str,
    ) -> dict[str, Any]:
        requester = _scoped_id("requester_subject_id", requester_subject_id)
        authorization = self._authorize(
            tenant_id, requester, PROJECT_APPLICATION_READ_SCOPE
        )
        found = self._repository.get_by_request_code(
            tenant_id=tenant_id,
            project_request_code=project_request_code,
        )
        if found is None:
            raise _not_found()
        if (
            found["applicant_subject_id"] != requester
            and "project:application:admin" not in authorization["scopes"]
        ):
            raise EosProjectApplicationError(
                "EOS_PROJECT_APPLICATION_READ_DENIED",
                "Project application is outside requester scope",
                status_code=403,
            )
        return found

    def resolve_project(
        self,
        *,
        tenant_id: str,
        project_code: str,
        requester_subject_id: str,
        active_only: bool = False,
    ) -> dict[str, Any]:
        requester = _scoped_id("requester_subject_id", requester_subject_id)
        self._authorize(tenant_id, requester, PROJECT_REFERENCE_RESOLVE_SCOPE)
        found = self._projects.get_project_by_code(
            tenant_id=tenant_id,
            project_code=project_code,
            active_only=active_only,
        )
        if found is None:
            raise EosProjectApplicationError(
                "EOS_PROJECT_CODE_NOT_FOUND",
                "Project registration code was not found in tenant scope",
                status_code=404,
            )
        return {
            key: item
            for key, item in _wire(found).items()
            if key not in {"project_id", "parent_project_id", "nvt_project_id"}
        }

    def _authorize(
        self, tenant_id: str, subject_id: str, required_scope: str
    ) -> Mapping[str, Any]:
        tenant_id = _tenant_code(tenant_id)
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except AuthorizationSubjectDenied as exc:
            raise EosProjectApplicationError(
                "EOS_PROJECT_APPLICATION_AUTHORIZATION_DENIED",
                "OA denied Project application authority",
                status_code=403,
            ) from exc
        except Exception as exc:
            raise EosProjectApplicationError(
                "EOS_PROJECT_APPLICATION_AUTHORIZATION_UNAVAILABLE",
                "OA Project application authority is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        if not isinstance(value, Mapping):
            raise EosProjectApplicationError(
                "EOS_PROJECT_APPLICATION_AUTHORIZATION_UNAVAILABLE",
                "OA Project application authority is malformed",
                status_code=503,
                retryable=True,
            )
        scopes = value.get("scopes")
        if (
            value.get("active") is not True
            or value.get("tenant_id") != tenant_id
            or value.get("subject_id") != subject_id
            or not isinstance(scopes, (list, tuple, set, frozenset))
            or required_scope not in scopes
        ):
            raise EosProjectApplicationError(
                "EOS_PROJECT_APPLICATION_AUTHORIZATION_DENIED",
                "OA denied Project application authority",
                status_code=403,
            )
        return value


def _draft_payload(value: ProjectApplicationDraft) -> dict[str, Any]:
    tenant_id = _tenant_code(value.tenant_id)
    application_id = _uuid("application_id", value.application_id)
    parent_project_id = _optional_uuid("parent_project_id", value.parent_project_id)
    nvt_project_id = _optional_uuid("nvt_project_id", value.nvt_project_id)
    if (parent_project_id is None) == (nvt_project_id is None):
        raise _invalid("exactly one of parent_project_id or nvt_project_id is required")
    start_date = _optional_date("start_date", value.start_date)
    end_date = _optional_date("end_date", value.end_date)
    if start_date is not None and end_date is not None and end_date < start_date:
        raise _invalid("end_date must not precede start_date")
    return {
        "schema_version": "eos_project_application_draft.v1",
        "tenant_id": tenant_id,
        "tenant_code": tenant_id,
        "application_id": application_id,
        "purpose_type": _purpose_type(value.purpose_type),
        "applicant_subject_id": _scoped_id(
            "applicant_subject_id", value.applicant_subject_id
        ),
        "name": _text("name", value.name, 256),
        "parent_project_id": parent_project_id,
        "nvt_project_id": nvt_project_id,
        "company_id": _optional_uuid("company_id", value.company_id),
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "currency": _currency(value.currency),
    }


def _format_code(
    *,
    tenant_code: str,
    code_kind: str,
    purpose_type: str,
    code_year: int,
    serial: int,
) -> str:
    marker = "R" if code_kind == "REQUEST" else purpose_type
    code = f"{tenant_code}{marker}{code_year:02d}{serial:04d}"
    validator = _REQUEST_CODE if code_kind == "REQUEST" else _PROJECT_CODE
    if validator.fullmatch(code) is None:
        raise _invalid("generated Project code is invalid")
    return code


def _wire(value: Mapping[str, Any]) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, datetime):
            projection[key] = (
                item if item.tzinfo is not None else item.replace(tzinfo=UTC)
            ).isoformat()
        elif isinstance(item, date):
            projection[key] = item.isoformat()
        else:
            projection[key] = item
    return projection


def _instant(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid("issued_at must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _tenant_code(value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if _TENANT_CODE.fullmatch(normalized) is None:
        raise _invalid("tenant_id must be the four-character tenant code")
    return normalized


def _request_code(value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if _REQUEST_CODE.fullmatch(normalized) is None:
        raise _invalid("project_request_code has invalid syntax")
    return normalized


def _purpose_type(value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized not in PROJECT_PURPOSE_TYPES:
        raise _invalid(f"purpose_type must be one of {sorted(PROJECT_PURPOSE_TYPES)}")
    return normalized


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{field_name} must be a UUID") from exc


def _optional_uuid(field_name: str, value: object) -> str | None:
    return None if value is None else _uuid(field_name, value)


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} has invalid stable-reference syntax")
    return normalized


def _text(field_name: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(f"{field_name} must contain 1..{maximum} characters")
    return normalized


def _currency(value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if _CURRENCY.fullmatch(normalized) is None:
        raise _invalid("currency must be a three-letter uppercase code")
    return normalized


def _optional_date(field_name: str, value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime) or not isinstance(value, date):
        raise _invalid(f"{field_name} must be a date")
    return value


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field_name} must be a positive integer")
    return value


def _invalid(detail: str) -> EosProjectApplicationError:
    return EosProjectApplicationError(
        "EOS_PROJECT_APPLICATION_INVALID", detail, status_code=422
    )


def _conflict(detail: str) -> EosProjectApplicationError:
    return EosProjectApplicationError(
        "EOS_PROJECT_APPLICATION_CONFLICT", detail, status_code=409
    )


def _version_conflict() -> EosProjectApplicationError:
    return EosProjectApplicationError(
        "EOS_PROJECT_APPLICATION_VERSION_CONFLICT",
        "Project application version changed before mutation",
        status_code=409,
    )


def _not_found() -> EosProjectApplicationError:
    return EosProjectApplicationError(
        "EOS_PROJECT_APPLICATION_NOT_FOUND",
        "Project application was not found in tenant scope",
        status_code=404,
    )


def _unavailable() -> EosProjectApplicationError:
    return EosProjectApplicationError(
        "EOS_PROJECT_APPLICATION_PERSISTENCE_FAILED",
        "Project application persistence is unavailable",
        status_code=503,
        retryable=True,
    )
