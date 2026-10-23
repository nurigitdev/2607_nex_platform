from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nex_runtime import build_unit_of_work
from nex_runtime.semantic_hashes import (
    semantic_sha256_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import (
    Boolean,
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
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .approval_policies import (
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
)
from .business_transactions import EOS_BUSINESS_OPERATION_TABLE, EOS_METADATA
from .organization import EOS_ORG_UNIT_TABLE
from .projects import EOS_PROJECT_TABLE

EOS_APPROVAL_INSTANCE_STATES = frozenset(
    {"PENDING", "APPROVED", "REJECTED", "CANCELLED", "INVALIDATED"}
)
EOS_APPROVAL_STAGE_STATES = frozenset(
    {"WAITING", "ACTIVE", "APPROVED", "REJECTED", "CANCELLED"}
)
EOS_APPROVAL_DECISIONS = frozenset({"APPROVE", "REJECT"})

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_STABLE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")

EOS_APPROVAL_INSTANCE_TABLE = Table(
    "eos_approval_instance",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("approval_instance_id", Uuid(as_uuid=False), primary_key=True),
    Column("idempotency_key", String(256), nullable=False),
    Column("approval_policy_id", Uuid(as_uuid=False), nullable=False),
    Column("policy_version", Integer, nullable=False),
    Column("policy_hash", String(71), nullable=False),
    Column("approval_domain", String(32), nullable=False),
    Column("business_operation_id", Uuid(as_uuid=False), nullable=False),
    Column("operation", String(128), nullable=False),
    Column("protected_operation_ref", String(256), nullable=False),
    Column("payload_hash", String(71), nullable=False),
    Column("write_intent_hash", String(71), nullable=False),
    Column("requester_ref_type", String(32), nullable=False),
    Column("requester_id", String(128), nullable=False),
    Column("org_unit_id", Uuid(as_uuid=False), nullable=False),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("state", String(16), nullable=False),
    Column("active_stage_order", Integer, nullable=True),
    Column("stage_count", Integer, nullable=False),
    Column("version", Integer, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("correlation_id", String(128), nullable=False),
    Column("causation_id", String(128), nullable=False),
    Column("binding_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "idempotency_key",
        name="ux_eos_approval_instance_idem",
    ),
    UniqueConstraint(
        "tenant_id", "binding_hash", name="ux_eos_approval_instance_binding"
    ),
    ForeignKeyConstraint(
        ("tenant_id", "approval_policy_id"),
        (
            "eos_approval_policy.tenant_id",
            "eos_approval_policy.approval_policy_id",
        ),
        name="fk_eos_approval_instance_policy",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "business_operation_id"),
        (
            "eos_business_operation.tenant_id",
            "eos_business_operation.business_operation_id",
        ),
        name="fk_eos_approval_instance_operation",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "org_unit_id"),
        ("eos_org_unit.tenant_id", "eos_org_unit.org_unit_id"),
        name="fk_eos_approval_instance_org",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_approval_instance_project",
    ),
    CheckConstraint(
        "stage_count BETWEEN 1 AND 5", name="ck_eos_approval_instance_stage_count"
    ),
    CheckConstraint("version > 0", name="ck_eos_approval_instance_version"),
    CheckConstraint(
        "active_stage_order IS NULL OR " "active_stage_order BETWEEN 1 AND stage_count",
        name="ck_eos_approval_instance_active_stage",
    ),
)
Index(
    "ix_eos_approval_instance_operation",
    EOS_APPROVAL_INSTANCE_TABLE.c.tenant_id,
    EOS_APPROVAL_INSTANCE_TABLE.c.business_operation_id,
    EOS_APPROVAL_INSTANCE_TABLE.c.state,
)

EOS_APPROVAL_STAGE_TABLE = Table(
    "eos_approval_stage",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("approval_stage_id", Uuid(as_uuid=False), primary_key=True),
    Column("approval_instance_id", Uuid(as_uuid=False), nullable=False),
    Column("stage_order", Integer, nullable=False),
    Column("policy_stage_order", Integer, nullable=False),
    Column("position_type", String(32), nullable=False),
    Column("quorum_count", Integer, nullable=False),
    Column("separation_policy", String(32), nullable=False),
    Column("state", String(16), nullable=False),
    Column("version", Integer, nullable=False),
    Column("activated_at", DateTime(timezone=True), nullable=True),
    Column("decided_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "approval_instance_id",
        "stage_order",
        name="ux_eos_approval_stage_order",
    ),
    UniqueConstraint(
        "tenant_id",
        "approval_instance_id",
        "approval_stage_id",
        name="ux_eos_approval_stage_instance",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "approval_instance_id"),
        (
            "eos_approval_instance.tenant_id",
            "eos_approval_instance.approval_instance_id",
        ),
        name="fk_eos_approval_stage_instance",
        ondelete="CASCADE",
    ),
    CheckConstraint("stage_order BETWEEN 1 AND 5", name="ck_eos_approval_stage_order"),
    CheckConstraint(
        "policy_stage_order BETWEEN 1 AND 5",
        name="ck_eos_approval_stage_policy_order",
    ),
    CheckConstraint("quorum_count > 0", name="ck_eos_approval_stage_quorum"),
    CheckConstraint("version > 0", name="ck_eos_approval_stage_version"),
)
Index(
    "ux_eos_approval_stage_active",
    EOS_APPROVAL_STAGE_TABLE.c.tenant_id,
    EOS_APPROVAL_STAGE_TABLE.c.approval_instance_id,
    unique=True,
    sqlite_where=EOS_APPROVAL_STAGE_TABLE.c.state == "ACTIVE",
    postgresql_where=EOS_APPROVAL_STAGE_TABLE.c.state == "ACTIVE",
)

EOS_APPROVAL_DECISION_TABLE = Table(
    "eos_approval_decision",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("approval_decision_id", Uuid(as_uuid=False), primary_key=True),
    Column("approval_instance_id", Uuid(as_uuid=False), nullable=False),
    Column("approval_stage_id", Uuid(as_uuid=False), nullable=False),
    Column("wc_approval_work_item_id", Uuid(as_uuid=False), nullable=False),
    Column("wc_decision_id", Uuid(as_uuid=False), nullable=False),
    Column("decision", String(16), nullable=False),
    Column("decision_version", Integer, nullable=False),
    Column("decided_by_ref_type", String(32), nullable=False),
    Column("decided_by_id", String(128), nullable=False),
    Column("decision_comment", Text, nullable=True),
    Column("authorized_by_oa", Boolean, nullable=False),
    Column("oa_decision_ref", String(128), nullable=False),
    Column("authorization_revision_hash", String(71), nullable=False),
    Column("authorization_checked_at", DateTime(timezone=True), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    Column("decision_hash", String(71), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("tenant_id", "wc_decision_id", name="ux_eos_approval_decision_wc"),
    UniqueConstraint(
        "tenant_id",
        "approval_stage_id",
        "decision_version",
        name="ux_eos_approval_decision_version",
    ),
    UniqueConstraint(
        "tenant_id", "decision_hash", name="ux_eos_approval_decision_hash"
    ),
    ForeignKeyConstraint(
        ("tenant_id", "approval_instance_id", "approval_stage_id"),
        (
            "eos_approval_stage.tenant_id",
            "eos_approval_stage.approval_instance_id",
            "eos_approval_stage.approval_stage_id",
        ),
        name="fk_eos_approval_decision_stage",
        ondelete="RESTRICT",
    ),
    CheckConstraint("decision_version > 0", name="ck_eos_approval_decision_version"),
    CheckConstraint("authorized_by_oa = TRUE", name="ck_eos_approval_decision_oa"),
)


class EosApprovalInstanceError(RuntimeError):
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
class ApprovalInstanceInput:
    tenant_id: str
    approval_instance_id: str
    idempotency_key: str
    approval_policy_id: str
    business_operation_id: str
    protected_operation_ref: str
    payload_hash: str
    write_intent_hash: str
    requester_ref: Mapping[str, Any]
    org_unit_id: str
    project_id: str
    correlation_id: str
    causation_id: str
    expires_at: datetime | None = None


Clock = Callable[[], datetime]


class SqlAlchemyEosApprovalInstanceRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Clock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_or_get_instance(
        self, value: ApprovalInstanceInput
    ) -> tuple[dict[str, Any], bool]:
        request = _request_record(value)
        now = _aware_datetime("created_at", self._clock())
        if request["expires_at"] is not None and request["expires_at"] <= now:
            raise _invalid("expires_at", "must be later than creation time")
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                existing = self._load_by_idempotency_key(
                    transaction.db,
                    tenant_id=request["tenant_id"],
                    idempotency_key=request["idempotency_key"],
                )
                if existing is not None:
                    _require_same_request(existing, request)
                    return self._full_projection(transaction.db, existing), False

                policy, policy_stages = self._load_effective_policy(
                    transaction.db,
                    tenant_id=request["tenant_id"],
                    approval_policy_id=request["approval_policy_id"],
                    effective_at=now,
                )
                operation = self._load_operation(
                    transaction.db,
                    tenant_id=request["tenant_id"],
                    business_operation_id=request["business_operation_id"],
                    payload_hash=request["payload_hash"],
                )
                self._require_active_reference(
                    transaction.db,
                    EOS_ORG_UNIT_TABLE,
                    id_column="org_unit_id",
                    tenant_id=request["tenant_id"],
                    reference_id=request["org_unit_id"],
                )
                self._require_active_reference(
                    transaction.db,
                    EOS_PROJECT_TABLE,
                    id_column="project_id",
                    tenant_id=request["tenant_id"],
                    reference_id=request["project_id"],
                )
                instance, stages = _instance_records(
                    request,
                    policy=policy,
                    policy_stages=policy_stages,
                    operation=operation,
                    now=now,
                )
                transaction.db.execute(
                    EOS_APPROVAL_INSTANCE_TABLE.insert().values(**instance)
                )
                transaction.db.execute(EOS_APPROVAL_STAGE_TABLE.insert(), stages)
                return _projection(instance, stages, ()), True
        except EosApprovalInstanceError:
            raise
        except IntegrityError as exc:
            replay = self._load_after_conflict(request)
            if replay is not None:
                return replay, False
            raise _conflict() from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def get_instance(
        self, *, tenant_id: str, approval_instance_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        approval_instance_id = _uuid("approval_instance_id", approval_instance_id)
        try:
            with self._session_factory() as session:
                instance = self._load_instance(
                    session,
                    tenant_id=tenant_id,
                    approval_instance_id=approval_instance_id,
                )
                if instance is None:
                    return None
                return self._full_projection(session, instance)
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def get_by_idempotency_key(
        self, *, tenant_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        idempotency_key = _idempotency_key(idempotency_key)
        try:
            with self._session_factory() as session:
                instance = self._load_by_idempotency_key(
                    session,
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                )
                if instance is None:
                    return None
                return self._full_projection(session, instance)
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def get_active_stage(
        self, *, tenant_id: str, approval_instance_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        approval_instance_id = _uuid("approval_instance_id", approval_instance_id)
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        select(EOS_APPROVAL_STAGE_TABLE).where(
                            EOS_APPROVAL_STAGE_TABLE.c.tenant_id == tenant_id,
                            EOS_APPROVAL_STAGE_TABLE.c.approval_instance_id
                            == approval_instance_id,
                            EOS_APPROVAL_STAGE_TABLE.c.state == "ACTIVE",
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return _stage_projection(row) if row is not None else None

    def list_decisions(
        self, *, tenant_id: str, approval_instance_id: str
    ) -> list[dict[str, Any]]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        approval_instance_id = _uuid("approval_instance_id", approval_instance_id)
        try:
            with self._session_factory() as session:
                rows = self._load_decisions(
                    session,
                    tenant_id=tenant_id,
                    approval_instance_id=approval_instance_id,
                )
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return [_decision_projection(row) for row in rows]

    def _load_after_conflict(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                existing = self._load_by_idempotency_key(
                    session,
                    tenant_id=request["tenant_id"],
                    idempotency_key=request["idempotency_key"],
                )
                if existing is None:
                    return None
                _require_same_request(existing, request)
                return self._full_projection(session, existing)
        except EosApprovalInstanceError:
            raise
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    @staticmethod
    def _load_effective_policy(
        session: Session,
        *,
        tenant_id: str,
        approval_policy_id: str,
        effective_at: datetime,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        policy = (
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
        if policy is None:
            raise _invalid("approval_policy_id", "does not exist in tenant scope")
        policy = dict(policy)
        if (
            policy["approval_domain"] != "BUSINESS_FORMAL"
            or policy["status"] != "ACTIVE"
            or _as_utc(policy["effective_from"]) > effective_at
            or (
                policy["effective_until"] is not None
                and _as_utc(policy["effective_until"]) <= effective_at
            )
        ):
            raise EosApprovalInstanceError(
                "EOS_APPROVAL_POLICY_NOT_EFFECTIVE",
                "Approval policy is not active for BUSINESS_FORMAL at creation time",
                status_code=409,
            )
        stages = [
            dict(row)
            for row in session.execute(
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
            raise EosApprovalInstanceError(
                "EOS_APPROVAL_POLICY_INVALID_STATE",
                "Approval policy has no persisted stages",
                status_code=409,
            )
        return policy, stages

    @staticmethod
    def _load_operation(
        session: Session,
        *,
        tenant_id: str,
        business_operation_id: str,
        payload_hash: str,
    ) -> dict[str, Any]:
        operation = (
            session.execute(
                select(EOS_BUSINESS_OPERATION_TABLE).where(
                    EOS_BUSINESS_OPERATION_TABLE.c.tenant_id == tenant_id,
                    EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                    == business_operation_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if operation is None:
            raise _invalid("business_operation_id", "does not exist in tenant scope")
        operation = dict(operation)
        if operation["commit_state"] != "COMMITTED":
            raise EosApprovalInstanceError(
                "EOS_APPROVAL_OPERATION_NOT_COMMITTED",
                "Protected business operation is not committed",
                status_code=409,
            )
        if operation["payload_hash"] != payload_hash:
            raise EosApprovalInstanceError(
                "EOS_APPROVAL_PAYLOAD_MISMATCH",
                "Approval payload hash does not match the protected operation",
                status_code=409,
            )
        return operation

    @staticmethod
    def _require_active_reference(
        session: Session,
        table: Table,
        *,
        id_column: str,
        tenant_id: str,
        reference_id: str,
    ) -> None:
        found = session.execute(
            select(table.c[id_column]).where(
                table.c.tenant_id == tenant_id,
                table.c[id_column] == reference_id,
                table.c.status == "ACTIVE",
            )
        ).scalar_one_or_none()
        if found is None:
            raise _invalid(
                id_column, "does not reference an active object in tenant scope"
            )

    @staticmethod
    def _load_instance(
        session: Session, *, tenant_id: str, approval_instance_id: str
    ) -> dict[str, Any] | None:
        row = (
            session.execute(
                select(EOS_APPROVAL_INSTANCE_TABLE).where(
                    EOS_APPROVAL_INSTANCE_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVAL_INSTANCE_TABLE.c.approval_instance_id
                    == approval_instance_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    @staticmethod
    def _load_by_idempotency_key(
        session: Session, *, tenant_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        row = (
            session.execute(
                select(EOS_APPROVAL_INSTANCE_TABLE).where(
                    EOS_APPROVAL_INSTANCE_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVAL_INSTANCE_TABLE.c.idempotency_key == idempotency_key,
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    @staticmethod
    def _load_stages(
        session: Session, *, tenant_id: str, approval_instance_id: str
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in session.execute(
                select(EOS_APPROVAL_STAGE_TABLE)
                .where(
                    EOS_APPROVAL_STAGE_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVAL_STAGE_TABLE.c.approval_instance_id
                    == approval_instance_id,
                )
                .order_by(EOS_APPROVAL_STAGE_TABLE.c.stage_order)
            ).mappings()
        ]

    @staticmethod
    def _load_decisions(
        session: Session, *, tenant_id: str, approval_instance_id: str
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in session.execute(
                select(EOS_APPROVAL_DECISION_TABLE)
                .where(
                    EOS_APPROVAL_DECISION_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVAL_DECISION_TABLE.c.approval_instance_id
                    == approval_instance_id,
                )
                .order_by(
                    EOS_APPROVAL_DECISION_TABLE.c.decided_at,
                    EOS_APPROVAL_DECISION_TABLE.c.decision_version,
                )
            ).mappings()
        ]

    def _full_projection(
        self, session: Session, instance: Mapping[str, Any]
    ) -> dict[str, Any]:
        stages = self._load_stages(
            session,
            tenant_id=instance["tenant_id"],
            approval_instance_id=instance["approval_instance_id"],
        )
        decisions = self._load_decisions(
            session,
            tenant_id=instance["tenant_id"],
            approval_instance_id=instance["approval_instance_id"],
        )
        return _projection(instance, stages, decisions)


def _request_record(value: ApprovalInstanceInput) -> dict[str, Any]:
    requester_type, requester_id = _entity_ref(
        "requester_ref", value.requester_ref, "oa.user"
    )
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "approval_instance_id": _uuid(
            "approval_instance_id", value.approval_instance_id
        ),
        "idempotency_key": _idempotency_key(value.idempotency_key),
        "approval_policy_id": _uuid("approval_policy_id", value.approval_policy_id),
        "business_operation_id": _uuid(
            "business_operation_id", value.business_operation_id
        ),
        "protected_operation_ref": _stable_ref(
            "protected_operation_ref", value.protected_operation_ref
        ),
        "payload_hash": _hash_ref("payload_hash", value.payload_hash),
        "write_intent_hash": _hash_ref("write_intent_hash", value.write_intent_hash),
        "requester_ref_type": requester_type,
        "requester_id": requester_id,
        "org_unit_id": _uuid("org_unit_id", value.org_unit_id),
        "project_id": _uuid("project_id", value.project_id),
        "correlation_id": _scoped_id("correlation_id", value.correlation_id),
        "causation_id": _scoped_id("causation_id", value.causation_id),
        "expires_at": (
            _aware_datetime("expires_at", value.expires_at)
            if value.expires_at is not None
            else None
        ),
    }


def _instance_records(
    request: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    policy_stages: Sequence[Mapping[str, Any]],
    operation: Mapping[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    stages = []
    for stage in policy_stages:
        stage_order = int(stage["stage_order"])
        stages.append(
            {
                "tenant_id": request["tenant_id"],
                "approval_stage_id": str(
                    uuid.uuid5(
                        uuid.UUID(request["approval_instance_id"]),
                        f"eos.approval-stage:{stage_order}",
                    )
                ),
                "approval_instance_id": request["approval_instance_id"],
                "stage_order": stage_order,
                "policy_stage_order": stage_order,
                "position_type": stage["position_type"],
                "quorum_count": stage["quorum_count"],
                "separation_policy": stage["separation_policy"],
                "state": "ACTIVE" if stage_order == 1 else "WAITING",
                "version": 1,
                "activated_at": now if stage_order == 1 else None,
                "decided_at": None,
                "created_at": now,
                "updated_at": now,
            }
        )
    binding = {
        "schema_version": "eos_approval_instance_binding.v1",
        **request,
        "policy_ref": {
            "approval_policy_id": str(policy["approval_policy_id"]),
            "version": policy["version"],
            "policy_hash": policy["policy_hash"],
        },
        "approval_domain": policy["approval_domain"],
        "operation": operation["operation"],
        "stages": [
            {
                "approval_stage_id": stage["approval_stage_id"],
                "stage_order": stage["stage_order"],
                "position_type": stage["position_type"],
                "quorum_count": stage["quorum_count"],
                "separation_policy": stage["separation_policy"],
            }
            for stage in stages
        ],
        "expires_at": (
            _timestamp(request["expires_at"])
            if request["expires_at"] is not None
            else None
        ),
    }
    binding.pop("requester_ref_type")
    binding.pop("requester_id")
    binding["requester_ref"] = {
        "type": request["requester_ref_type"],
        "id": request["requester_id"],
    }
    instance = {
        **request,
        "approval_policy_id": str(policy["approval_policy_id"]),
        "policy_version": policy["version"],
        "policy_hash": policy["policy_hash"],
        "approval_domain": policy["approval_domain"],
        "operation": operation["operation"],
        "state": "PENDING",
        "active_stage_order": 1,
        "stage_count": len(stages),
        "version": 1,
        "binding_hash": semantic_sha256_hash_ref(binding),
        "created_at": now,
        "updated_at": now,
    }
    return instance, stages


def _require_same_request(
    existing: Mapping[str, Any], request: Mapping[str, Any]
) -> None:
    fields = (
        "approval_instance_id",
        "idempotency_key",
        "approval_policy_id",
        "business_operation_id",
        "protected_operation_ref",
        "payload_hash",
        "write_intent_hash",
        "requester_ref_type",
        "requester_id",
        "org_unit_id",
        "project_id",
        "correlation_id",
        "causation_id",
    )
    matches = all(str(existing[field]) == str(request[field]) for field in fields)
    existing_expiry = (
        _timestamp(existing["expires_at"])
        if existing["expires_at"] is not None
        else None
    )
    request_expiry = (
        _timestamp(request["expires_at"]) if request["expires_at"] is not None else None
    )
    if not matches or existing_expiry != request_expiry:
        raise EosApprovalInstanceError(
            "EOS_APPROVAL_INSTANCE_REPLAY_CONFLICT",
            "Idempotency key already exists with different immutable binding",
            status_code=409,
        )


def _projection(
    instance: Mapping[str, Any],
    stages: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "eos_approval_instance.v1",
        "tenant_id": instance["tenant_id"],
        "approval_instance_id": str(instance["approval_instance_id"]),
        "idempotency_key": instance["idempotency_key"],
        "policy_ref": {
            "approval_policy_id": str(instance["approval_policy_id"]),
            "version": instance["policy_version"],
            "policy_hash": instance["policy_hash"],
        },
        "approval_domain": instance["approval_domain"],
        "business_operation_id": str(instance["business_operation_id"]),
        "operation": instance["operation"],
        "protected_operation_ref": instance["protected_operation_ref"],
        "payload_hash": instance["payload_hash"],
        "write_intent_hash": instance["write_intent_hash"],
        "requester_ref": {
            "type": instance["requester_ref_type"],
            "id": instance["requester_id"],
        },
        "org_unit_ref": {
            "type": "eos.org_unit",
            "id": str(instance["org_unit_id"]),
        },
        "project_ref": {
            "type": "eos.project",
            "id": str(instance["project_id"]),
        },
        "state": instance["state"],
        "active_stage_order": instance["active_stage_order"],
        "stage_count": instance["stage_count"],
        "version": instance["version"],
        "expires_at": (
            _timestamp(instance["expires_at"])
            if instance["expires_at"] is not None
            else None
        ),
        "correlation_id": instance["correlation_id"],
        "causation_id": instance["causation_id"],
        "binding_hash": instance["binding_hash"],
        "created_at": _timestamp(instance["created_at"]),
        "updated_at": _timestamp(instance["updated_at"]),
        "stages": [_stage_projection(stage) for stage in stages],
        "decision_history": [_decision_projection(item) for item in decisions],
    }


def _stage_projection(stage: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "eos_approval_stage.v1",
        "tenant_id": stage["tenant_id"],
        "approval_stage_id": str(stage["approval_stage_id"]),
        "approval_instance_id": str(stage["approval_instance_id"]),
        "stage_order": stage["stage_order"],
        "policy_stage_order": stage["policy_stage_order"],
        "position_type": stage["position_type"],
        "quorum_count": stage["quorum_count"],
        "separation_policy": stage["separation_policy"],
        "state": stage["state"],
        "version": stage["version"],
        "activated_at": (
            _timestamp(stage["activated_at"])
            if stage["activated_at"] is not None
            else None
        ),
        "decided_at": (
            _timestamp(stage["decided_at"]) if stage["decided_at"] is not None else None
        ),
    }


def _decision_projection(decision: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "eos_approval_decision.v1",
        "tenant_id": decision["tenant_id"],
        "approval_decision_id": str(decision["approval_decision_id"]),
        "approval_instance_id": str(decision["approval_instance_id"]),
        "approval_stage_id": str(decision["approval_stage_id"]),
        "wc_approval_work_item_id": str(decision["wc_approval_work_item_id"]),
        "wc_decision_id": str(decision["wc_decision_id"]),
        "decision": decision["decision"],
        "decision_version": decision["decision_version"],
        "decided_by": {
            "type": decision["decided_by_ref_type"],
            "id": decision["decided_by_id"],
        },
        "decision_comment": decision["decision_comment"],
        "authorized_by_oa": decision["authorized_by_oa"],
        "oa_decision_ref": decision["oa_decision_ref"],
        "authorization_revision_hash": decision["authorization_revision_hash"],
        "authorization_checked_at": _timestamp(decision["authorization_checked_at"]),
        "decided_at": _timestamp(decision["decided_at"]),
        "decision_hash": decision["decision_hash"],
        "recorded_at": _timestamp(decision["recorded_at"]),
    }


def _entity_ref(field_name: str, value: object, expected_type: str) -> tuple[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"type", "id"}:
        raise _invalid(field_name, "must contain exactly type and id")
    if value.get("type") != expected_type:
        raise _invalid(f"{field_name}.type", f"must be {expected_type}")
    return expected_type, _scoped_id(f"{field_name}.id", value.get("id"))


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field_name, "must be a UUID") from exc


def _hash_ref(field_name: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(
            field_name, "must be a lowercase SHA-256 hash reference"
        ) from exc


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _SCOPED_ID.fullmatch(normalized):
        raise _invalid(field_name, "has invalid stable-reference syntax")
    return normalized


def _idempotency_key(value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _IDEMPOTENCY_KEY.fullmatch(normalized):
        raise _invalid("idempotency_key", "has invalid syntax")
    return normalized


def _stable_ref(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _STABLE_REF.fullmatch(normalized):
        raise _invalid(field_name, "has invalid stable-reference syntax")
    return normalized


def _aware_datetime(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(field_name, "must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _invalid(field_name: str, detail: str) -> EosApprovalInstanceError:
    return EosApprovalInstanceError(
        "EOS_APPROVAL_INSTANCE_INVALID",
        f"{field_name} {detail}",
        status_code=422,
    )


def _conflict() -> EosApprovalInstanceError:
    return EosApprovalInstanceError(
        "EOS_APPROVAL_INSTANCE_CONFLICT",
        "Approval instance identity or immutable binding conflicts",
        status_code=409,
    )


def _persistence_error() -> EosApprovalInstanceError:
    return EosApprovalInstanceError(
        "EOS_APPROVAL_INSTANCE_PERSISTENCE_FAILED",
        "Approval instance persistence is unavailable",
        status_code=503,
        retryable=True,
    )
