from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from nex_runtime import build_unit_of_work
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import and_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .approval_instances import (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_PROOF_TABLE,
    EOS_APPROVAL_STAGE_TABLE,
    EosApprovalInstanceError,
    SqlAlchemyEosApprovalInstanceRepository,
)
from .business_formal_wc import deterministic_business_formal_work_item_id

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_AUTHORIZATION_CLOCK_SKEW = timedelta(minutes=5)


class EosApprovalTransitionError(RuntimeError):
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
class ApprovalStageDecisionInput:
    tenant_id: str
    approval_instance_id: str
    approval_stage_id: str
    wc_approval_work_item_id: str
    wc_work_item_semantic_hash: str
    wc_decision_id: str
    wc_event_id: str
    decision: str
    decision_version: int
    decided_by_ref: Mapping[str, Any]
    decision_comment: str | None
    authorized_by_oa: bool
    oa_decision_ref: str
    authorization_revision_hash: str
    authorization_checked_at: datetime
    decided_at: datetime
    correlation_id: str
    causation_id: str


class ApprovalInstanceSource(Protocol):
    def get_instance(
        self, *, tenant_id: str, approval_instance_id: str
    ) -> dict[str, Any] | None: ...


Clock = Callable[[], datetime]


class SqlAlchemyEosApprovalTransitionRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Clock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._instances = SqlAlchemyEosApprovalInstanceRepository(session_factory)

    def apply_decision(self, value: ApprovalStageDecisionInput) -> dict[str, Any]:
        admitted = _decision_record(value)
        recorded_at = _aware_datetime("recorded_at", self._clock())
        _require_decision_time(admitted, recorded_at=recorded_at)
        admitted["recorded_at"] = recorded_at
        admitted["decision_hash"] = _decision_hash(admitted)
        created = False
        outcome = "REPLAY"
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                existing = self._load_wc_decision(
                    transaction.db,
                    tenant_id=admitted["tenant_id"],
                    wc_decision_id=admitted["wc_decision_id"],
                    for_update=True,
                )
                if existing is not None:
                    if existing["decision_hash"] != admitted["decision_hash"]:
                        raise _conflict(
                            "WC decision replay changed its immutable EOS binding"
                        )
                else:
                    outcome = self._apply_new_decision(
                        transaction.db,
                        admitted=admitted,
                        recorded_at=recorded_at,
                    )
                    created = True
        except EosApprovalTransitionError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "Approval stage changed concurrently or proof identity conflicts"
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

        try:
            instance = self._instances.get_instance(
                tenant_id=admitted["tenant_id"],
                approval_instance_id=admitted["approval_instance_id"],
            )
            decision = self._get_wc_decision_projection(
                tenant_id=admitted["tenant_id"],
                wc_decision_id=admitted["wc_decision_id"],
            )
            proof = self.get_final_proof(
                tenant_id=admitted["tenant_id"],
                approval_instance_id=admitted["approval_instance_id"],
            )
        except EosApprovalInstanceError as exc:
            raise _persistence_error() from exc
        if instance is None or decision is None:
            raise _persistence_error()
        active_stage = next(
            (stage for stage in instance["stages"] if stage["state"] == "ACTIVE"),
            None,
        )
        return {
            "schema_version": "eos_approval_transition.v1",
            "tenant_id": admitted["tenant_id"],
            "approval_instance_id": admitted["approval_instance_id"],
            "outcome": outcome,
            "created": created,
            "instance": instance,
            "decision": decision,
            "next_active_stage": active_stage,
            "approval_proof": proof,
        }

    def get_final_proof(
        self, *, tenant_id: str, approval_instance_id: str
    ) -> dict[str, Any] | None:
        admitted_tenant = _scoped_id("tenant_id", tenant_id)
        admitted_instance = _uuid("approval_instance_id", approval_instance_id)
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        select(EOS_APPROVAL_PROOF_TABLE).where(
                            EOS_APPROVAL_PROOF_TABLE.c.tenant_id == admitted_tenant,
                            EOS_APPROVAL_PROOF_TABLE.c.approval_instance_id
                            == admitted_instance,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return _proof_projection(row) if row is not None else None

    def _apply_new_decision(
        self,
        session: Session,
        *,
        admitted: Mapping[str, Any],
        recorded_at: datetime,
    ) -> str:
        instance = self._load_instance_for_update(
            session,
            tenant_id=admitted["tenant_id"],
            approval_instance_id=admitted["approval_instance_id"],
        )
        if instance is None:
            raise EosApprovalTransitionError(
                "EOS_APPROVAL_INSTANCE_NOT_FOUND",
                "Approval instance does not exist in tenant scope",
                status_code=404,
            )
        _require_transitionable_instance(instance, admitted)
        stage = self._load_stage_for_update(
            session,
            tenant_id=admitted["tenant_id"],
            approval_instance_id=admitted["approval_instance_id"],
            approval_stage_id=admitted["approval_stage_id"],
        )
        if stage is None:
            raise _conflict("WC decision does not bind an EOS approval stage")
        _require_active_stage(instance, stage)

        decision = {
            "tenant_id": admitted["tenant_id"],
            "approval_decision_id": str(
                uuid.uuid5(
                    uuid.UUID(admitted["approval_instance_id"]),
                    f"eos.approval-decision:{admitted['wc_decision_id']}",
                )
            ),
            "approval_instance_id": admitted["approval_instance_id"],
            "approval_stage_id": admitted["approval_stage_id"],
            "wc_approval_work_item_id": admitted["wc_approval_work_item_id"],
            "wc_decision_id": admitted["wc_decision_id"],
            "decision": admitted["decision"],
            "decision_version": admitted["decision_version"],
            "decided_by_ref_type": admitted["decided_by_ref_type"],
            "decided_by_id": admitted["decided_by_id"],
            "decision_comment": admitted["decision_comment"],
            "authorized_by_oa": admitted["authorized_by_oa"],
            "oa_decision_ref": admitted["oa_decision_ref"],
            "authorization_revision_hash": admitted["authorization_revision_hash"],
            "authorization_checked_at": admitted["authorization_checked_at"],
            "decided_at": admitted["decided_at"],
            "decision_hash": admitted["decision_hash"],
            "recorded_at": admitted["recorded_at"],
        }
        session.execute(EOS_APPROVAL_DECISION_TABLE.insert().values(**decision))
        self._close_active_stage(
            session,
            stage=stage,
            state="APPROVED" if admitted["decision"] == "APPROVE" else "REJECTED",
            decided_at=admitted["decided_at"],
            recorded_at=recorded_at,
        )
        if admitted["decision"] == "REJECT":
            self._reject_instance(
                session,
                instance=instance,
                decided_at=admitted["decided_at"],
                recorded_at=recorded_at,
            )
            return "REJECTED"

        if int(stage["stage_order"]) < int(instance["stage_count"]):
            self._activate_next_stage(
                session,
                instance=instance,
                current_stage=stage,
                activated_at=admitted["decided_at"],
                recorded_at=recorded_at,
            )
            return "NEXT_STAGE_ACTIVE"

        self._approve_instance(
            session,
            instance=instance,
            recorded_at=recorded_at,
        )
        proof = self._proof_record(
            session,
            instance=instance,
            final_stage=stage,
            final_decision=decision,
            issued_at=recorded_at,
        )
        session.execute(EOS_APPROVAL_PROOF_TABLE.insert().values(**proof))
        return "FINAL_APPROVED"

    @staticmethod
    def _close_active_stage(
        session: Session,
        *,
        stage: Mapping[str, Any],
        state: str,
        decided_at: datetime,
        recorded_at: datetime,
    ) -> None:
        result = session.execute(
            update(EOS_APPROVAL_STAGE_TABLE)
            .where(
                EOS_APPROVAL_STAGE_TABLE.c.tenant_id == stage["tenant_id"],
                EOS_APPROVAL_STAGE_TABLE.c.approval_stage_id
                == stage["approval_stage_id"],
                EOS_APPROVAL_STAGE_TABLE.c.state == "ACTIVE",
                EOS_APPROVAL_STAGE_TABLE.c.version == stage["version"],
            )
            .values(
                state=state,
                version=int(stage["version"]) + 1,
                decided_at=decided_at,
                updated_at=recorded_at,
            )
        )
        if int(result.rowcount or 0) != 1:
            raise _conflict("Active approval stage changed concurrently")

    @staticmethod
    def _reject_instance(
        session: Session,
        *,
        instance: Mapping[str, Any],
        decided_at: datetime,
        recorded_at: datetime,
    ) -> None:
        session.execute(
            update(EOS_APPROVAL_STAGE_TABLE)
            .where(
                EOS_APPROVAL_STAGE_TABLE.c.tenant_id == instance["tenant_id"],
                EOS_APPROVAL_STAGE_TABLE.c.approval_instance_id
                == instance["approval_instance_id"],
                EOS_APPROVAL_STAGE_TABLE.c.state == "WAITING",
            )
            .values(
                state="CANCELLED",
                version=EOS_APPROVAL_STAGE_TABLE.c.version + 1,
                updated_at=recorded_at,
            )
        )
        result = session.execute(
            update(EOS_APPROVAL_INSTANCE_TABLE)
            .where(
                EOS_APPROVAL_INSTANCE_TABLE.c.tenant_id == instance["tenant_id"],
                EOS_APPROVAL_INSTANCE_TABLE.c.approval_instance_id
                == instance["approval_instance_id"],
                EOS_APPROVAL_INSTANCE_TABLE.c.state == "PENDING",
                EOS_APPROVAL_INSTANCE_TABLE.c.version == instance["version"],
            )
            .values(
                state="REJECTED",
                active_stage_order=None,
                version=int(instance["version"]) + 1,
                updated_at=max(decided_at, recorded_at),
            )
        )
        if int(result.rowcount or 0) != 1:
            raise _conflict("Approval instance changed concurrently")

    @staticmethod
    def _activate_next_stage(
        session: Session,
        *,
        instance: Mapping[str, Any],
        current_stage: Mapping[str, Any],
        activated_at: datetime,
        recorded_at: datetime,
    ) -> None:
        next_order = int(current_stage["stage_order"]) + 1
        next_stage = (
            session.execute(
                select(EOS_APPROVAL_STAGE_TABLE)
                .where(
                    EOS_APPROVAL_STAGE_TABLE.c.tenant_id == instance["tenant_id"],
                    EOS_APPROVAL_STAGE_TABLE.c.approval_instance_id
                    == instance["approval_instance_id"],
                    EOS_APPROVAL_STAGE_TABLE.c.stage_order == next_order,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if next_stage is None or next_stage["state"] != "WAITING":
            raise _conflict("Next approval stage is not waiting")
        session.execute(
            update(EOS_APPROVAL_STAGE_TABLE)
            .where(
                EOS_APPROVAL_STAGE_TABLE.c.tenant_id == instance["tenant_id"],
                EOS_APPROVAL_STAGE_TABLE.c.approval_stage_id
                == next_stage["approval_stage_id"],
                EOS_APPROVAL_STAGE_TABLE.c.state == "WAITING",
                EOS_APPROVAL_STAGE_TABLE.c.version == next_stage["version"],
            )
            .values(
                state="ACTIVE",
                version=int(next_stage["version"]) + 1,
                activated_at=activated_at,
                updated_at=recorded_at,
            )
        )
        result = session.execute(
            update(EOS_APPROVAL_INSTANCE_TABLE)
            .where(
                EOS_APPROVAL_INSTANCE_TABLE.c.tenant_id == instance["tenant_id"],
                EOS_APPROVAL_INSTANCE_TABLE.c.approval_instance_id
                == instance["approval_instance_id"],
                EOS_APPROVAL_INSTANCE_TABLE.c.state == "PENDING",
                EOS_APPROVAL_INSTANCE_TABLE.c.version == instance["version"],
            )
            .values(
                active_stage_order=next_order,
                version=int(instance["version"]) + 1,
                updated_at=recorded_at,
            )
        )
        if int(result.rowcount or 0) != 1:
            raise _conflict("Approval instance changed concurrently")

    @staticmethod
    def _approve_instance(
        session: Session,
        *,
        instance: Mapping[str, Any],
        recorded_at: datetime,
    ) -> None:
        result = session.execute(
            update(EOS_APPROVAL_INSTANCE_TABLE)
            .where(
                EOS_APPROVAL_INSTANCE_TABLE.c.tenant_id == instance["tenant_id"],
                EOS_APPROVAL_INSTANCE_TABLE.c.approval_instance_id
                == instance["approval_instance_id"],
                EOS_APPROVAL_INSTANCE_TABLE.c.state == "PENDING",
                EOS_APPROVAL_INSTANCE_TABLE.c.version == instance["version"],
            )
            .values(
                state="APPROVED",
                active_stage_order=None,
                version=int(instance["version"]) + 1,
                updated_at=recorded_at,
            )
        )
        if int(result.rowcount or 0) != 1:
            raise _conflict("Approval instance changed concurrently")

    @staticmethod
    def _proof_record(
        session: Session,
        *,
        instance: Mapping[str, Any],
        final_stage: Mapping[str, Any],
        final_decision: Mapping[str, Any],
        issued_at: datetime,
    ) -> dict[str, Any]:
        rows = list(
            session.execute(
                select(
                    EOS_APPROVAL_STAGE_TABLE.c.stage_order,
                    EOS_APPROVAL_STAGE_TABLE.c.approval_stage_id,
                    EOS_APPROVAL_DECISION_TABLE.c.wc_decision_id,
                    EOS_APPROVAL_DECISION_TABLE.c.decision,
                    EOS_APPROVAL_DECISION_TABLE.c.decision_hash,
                )
                .select_from(
                    EOS_APPROVAL_DECISION_TABLE.join(
                        EOS_APPROVAL_STAGE_TABLE,
                        and_(
                            EOS_APPROVAL_DECISION_TABLE.c.tenant_id
                            == EOS_APPROVAL_STAGE_TABLE.c.tenant_id,
                            EOS_APPROVAL_DECISION_TABLE.c.approval_stage_id
                            == EOS_APPROVAL_STAGE_TABLE.c.approval_stage_id,
                        ),
                    )
                )
                .where(
                    EOS_APPROVAL_DECISION_TABLE.c.tenant_id == instance["tenant_id"],
                    EOS_APPROVAL_DECISION_TABLE.c.approval_instance_id
                    == instance["approval_instance_id"],
                )
                .order_by(EOS_APPROVAL_STAGE_TABLE.c.stage_order)
            ).mappings()
        )
        if len(rows) != int(instance["stage_count"]) or any(
            row["decision"] != "APPROVE" for row in rows
        ):
            raise _conflict("Final approval proof requires every stage approval")
        chain = {
            "schema_version": "eos_approval_decision_chain.v1",
            "tenant_id": instance["tenant_id"],
            "approval_instance_id": str(instance["approval_instance_id"]),
            "decisions": [
                {
                    "stage_order": row["stage_order"],
                    "approval_stage_id": str(row["approval_stage_id"]),
                    "wc_decision_id": str(row["wc_decision_id"]),
                    "decision": row["decision"],
                    "decision_hash": row["decision_hash"],
                }
                for row in rows
            ],
        }
        chain_hash = semantic_sha256_hash_ref(chain)
        proof_id = str(
            uuid.uuid5(
                uuid.UUID(str(instance["approval_instance_id"])),
                "eos.approval-proof:v1",
            )
        )
        proof_binding = {
            "schema_version": "eos_approval_proof_binding.v1",
            "tenant_id": instance["tenant_id"],
            "approval_proof_id": proof_id,
            "approval_instance_id": str(instance["approval_instance_id"]),
            "business_operation_id": str(instance["business_operation_id"]),
            "final_approval_stage_id": str(final_stage["approval_stage_id"]),
            "final_wc_decision_id": str(final_decision["wc_decision_id"]),
            "approval_domain": "BUSINESS_FORMAL",
            "protected_operation_ref": instance["protected_operation_ref"],
            "payload_hash": instance["payload_hash"],
            "write_intent_hash": instance["write_intent_hash"],
            "policy_hash": instance["policy_hash"],
            "instance_binding_hash": instance["binding_hash"],
            "decision_chain_hash": chain_hash,
            "final_decision_hash": final_decision["decision_hash"],
            "proof_version": 1,
        }
        proof_hash = semantic_sha256_hash_ref(proof_binding)
        proof_binding.pop("schema_version")
        return {
            **proof_binding,
            "proof_hash": proof_hash,
            "issued_at": issued_at,
        }

    @staticmethod
    def _load_instance_for_update(
        session: Session, *, tenant_id: str, approval_instance_id: str
    ) -> dict[str, Any] | None:
        row = (
            session.execute(
                select(EOS_APPROVAL_INSTANCE_TABLE)
                .where(
                    EOS_APPROVAL_INSTANCE_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVAL_INSTANCE_TABLE.c.approval_instance_id
                    == approval_instance_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    @staticmethod
    def _load_stage_for_update(
        session: Session,
        *,
        tenant_id: str,
        approval_instance_id: str,
        approval_stage_id: str,
    ) -> dict[str, Any] | None:
        row = (
            session.execute(
                select(EOS_APPROVAL_STAGE_TABLE)
                .where(
                    EOS_APPROVAL_STAGE_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVAL_STAGE_TABLE.c.approval_instance_id
                    == approval_instance_id,
                    EOS_APPROVAL_STAGE_TABLE.c.approval_stage_id == approval_stage_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    @staticmethod
    def _load_wc_decision(
        session: Session,
        *,
        tenant_id: str,
        wc_decision_id: str,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        statement = select(EOS_APPROVAL_DECISION_TABLE).where(
            EOS_APPROVAL_DECISION_TABLE.c.tenant_id == tenant_id,
            EOS_APPROVAL_DECISION_TABLE.c.wc_decision_id == wc_decision_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = session.execute(statement).mappings().one_or_none()
        return dict(row) if row is not None else None

    def _get_wc_decision_projection(
        self, *, tenant_id: str, wc_decision_id: str
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = self._load_wc_decision(
                    session,
                    tenant_id=tenant_id,
                    wc_decision_id=wc_decision_id,
                )
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return _decision_projection(row) if row is not None else None


class EosBusinessApprovalTransitionService:
    def __init__(
        self,
        *,
        approval_instances: ApprovalInstanceSource,
        transitions: SqlAlchemyEosApprovalTransitionRepository,
    ) -> None:
        self._approval_instances = approval_instances
        self._transitions = transitions

    def advance_from_wc_decision(
        self,
        *,
        tenant_id: str,
        approval_instance_id: str,
        work_item: Mapping[str, Any],
        decision: Mapping[str, Any],
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        admitted_tenant = _scoped_id("tenant_id", tenant_id)
        admitted_instance_id = _uuid("approval_instance_id", approval_instance_id)
        instance = self._approval_instances.get_instance(
            tenant_id=admitted_tenant,
            approval_instance_id=admitted_instance_id,
        )
        if instance is None:
            raise EosApprovalTransitionError(
                "EOS_APPROVAL_INSTANCE_NOT_FOUND",
                "Approval instance does not exist in tenant scope",
                status_code=404,
            )
        stage = _stage_from_wc_source(instance=instance, work_item=work_item)
        if stage is None:
            raise _conflict("WC work item does not reference an EOS approval stage")
        item = _admit_wc_work_item(instance=instance, stage=stage, value=work_item)
        admitted_decision = _admit_wc_decision(item=item, value=decision)
        admitted_event = _admit_wc_event(
            item=item,
            decision=admitted_decision,
            value=event,
        )
        return self._transitions.apply_decision(
            ApprovalStageDecisionInput(
                tenant_id=admitted_tenant,
                approval_instance_id=admitted_instance_id,
                approval_stage_id=stage["approval_stage_id"],
                wc_approval_work_item_id=item["approval_work_item_id"],
                wc_work_item_semantic_hash=item["semantic_hash"],
                wc_decision_id=admitted_decision["decision_id"],
                wc_event_id=admitted_event["event_id"],
                decision=admitted_decision["decision"],
                decision_version=admitted_decision["decision_version"],
                decided_by_ref={
                    "type": "oa.user",
                    "id": admitted_decision["decided_by"],
                },
                decision_comment=admitted_decision["decision_comment"],
                authorized_by_oa=admitted_decision["authorized_by_oa"],
                oa_decision_ref=admitted_decision["oa_decision_ref"],
                authorization_revision_hash=admitted_decision[
                    "authorization_revision_hash"
                ],
                authorization_checked_at=_parse_timestamp(
                    "authorization_checked_at",
                    admitted_decision["authorization_checked_at"],
                ),
                decided_at=_parse_timestamp(
                    "decided_at", admitted_decision["decided_at"]
                ),
                correlation_id=admitted_event["correlation_id"],
                causation_id=admitted_event["causation_id"],
            )
        )


def _admit_wc_work_item(
    *,
    instance: Mapping[str, Any],
    stage: Mapping[str, Any],
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("work_item", "must be an object")
    item = dict(value)
    stage_ref = f"eos.approval-stage:{stage['approval_stage_id']}"
    expected = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": instance["tenant_id"],
        "approval_work_item_id": deterministic_business_formal_work_item_id(
            tenant_id=instance["tenant_id"],
            approval_stage_id=stage["approval_stage_id"],
        ),
        "approval_domain": "BUSINESS_FORMAL",
        "approval_provider_type": "EOS",
        "source_ref": stage_ref,
        "approval_target_ref": stage_ref,
        "target_role_ref": stage["position_type"],
        "target_org_scope_ref": instance["org_unit_ref"]["id"],
        "target_project_scope_ref": instance["project_ref"]["id"],
        "business_operation_id": instance["business_operation_id"],
        "protected_request_ref": instance["protected_operation_ref"],
        "resume_target_ref": (
            f"eos.approval-instance:{instance['approval_instance_id']}:"
            f"stage:{stage['stage_order']}"
        ),
    }
    for field, expected_value in expected.items():
        if item.get(field) != expected_value:
            raise _conflict(f"WC work item {field} does not match the EOS stage")
    terminal_state = item.get("state")
    if terminal_state not in {"APPROVED", "REJECTED"} or item.get("version") != 2:
        raise _conflict("WC work item is not at its immutable terminal version")
    item["semantic_hash"] = _hash_ref(
        "work_item.semantic_hash", item.get("semantic_hash")
    )
    item["approval_work_item_id"] = _uuid(
        "work_item.approval_work_item_id", item["approval_work_item_id"]
    )
    item["target_approver_ref"] = _scoped_id(
        "work_item.target_approver_ref", item.get("target_approver_ref")
    )
    created_at = _parse_timestamp("work_item.created_at", item.get("created_at"))
    if item.get("expires_at") is not None:
        expires_at = _parse_timestamp("work_item.expires_at", item["expires_at"])
        if expires_at <= created_at:
            raise _invalid("work_item.expires_at", "must follow created_at")
    return item


def _stage_from_wc_source(
    *, instance: Mapping[str, Any], work_item: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    source_ref = work_item.get("source_ref") if isinstance(work_item, Mapping) else None
    prefix = "eos.approval-stage:"
    if not isinstance(source_ref, str) or not source_ref.startswith(prefix):
        return None
    try:
        stage_id = _uuid("work_item.source_ref", source_ref.removeprefix(prefix))
    except EosApprovalTransitionError:
        return None
    for stage in instance.get("stages", ()):
        if stage.get("approval_stage_id") == stage_id:
            return stage
    return None


def _admit_wc_decision(
    *, item: Mapping[str, Any], value: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("decision", "must be an object")
    decision = dict(value)
    exact = {
        "schema_version": "wc_approval_decision.v1",
        "tenant_id": item["tenant_id"],
        "approval_work_item_id": item["approval_work_item_id"],
        "decision_version": 1,
        "authorized_by_oa": True,
    }
    for field, expected_value in exact.items():
        if decision.get(field) != expected_value:
            raise _conflict(f"WC decision {field} binding is invalid")
    decision["decision_id"] = _uuid("decision.decision_id", decision.get("decision_id"))
    if decision.get("decision") not in {"APPROVE", "REJECT"}:
        raise _invalid("decision.decision", "must be APPROVE or REJECT")
    expected_state = "APPROVED" if decision["decision"] == "APPROVE" else "REJECTED"
    if item["state"] != expected_state:
        raise _conflict("WC work item terminal state does not match its decision")
    decision["decided_by"] = _scoped_id(
        "decision.decided_by", decision.get("decided_by")
    )
    if decision["decided_by"] != item["target_approver_ref"]:
        raise _conflict("WC decision principal is not the resolved EOS approver")
    comment = decision.get("decision_comment")
    if comment is not None and (not isinstance(comment, str) or len(comment) > 2000):
        raise _invalid("decision.decision_comment", "is invalid")
    decision["oa_decision_ref"] = _scoped_id(
        "decision.oa_decision_ref", decision.get("oa_decision_ref")
    )
    decision["authorization_revision_hash"] = _hash_ref(
        "decision.authorization_revision_hash",
        decision.get("authorization_revision_hash"),
    )
    authorization_checked_at = _parse_timestamp(
        "decision.authorization_checked_at",
        decision.get("authorization_checked_at"),
    )
    decided_at = _parse_timestamp("decision.decided_at", decision.get("decided_at"))
    if abs(authorization_checked_at - decided_at) > _MAX_AUTHORIZATION_CLOCK_SKEW:
        raise _conflict("WC OA authorization is not fresh for the decision")
    created_at = _parse_timestamp("work_item.created_at", item.get("created_at"))
    if decided_at < created_at:
        raise _conflict("WC decision predates its work item")
    if item.get("expires_at") is not None and decided_at >= _parse_timestamp(
        "work_item.expires_at", item["expires_at"]
    ):
        raise _conflict("WC decision occurred after work item expiry")
    return decision


def _admit_wc_event(
    *,
    item: Mapping[str, Any],
    decision: Mapping[str, Any],
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("event", "must be an object")
    event = dict(value)
    exact = {
        "schema_version": "wc_approval_event.v1",
        "tenant_id": item["tenant_id"],
        "event_type": "BUSINESS_FORMAL_APPROVAL_DECIDED",
        "approval_work_item_id": item["approval_work_item_id"],
        "decision_id": decision["decision_id"],
        "approval_domain": "BUSINESS_FORMAL",
        "decision": decision["decision"],
        "decided_by": decision["decided_by"],
        "oa_decision_ref": decision["oa_decision_ref"],
        "occurred_at": decision["decided_at"],
    }
    for field, expected_value in exact.items():
        if event.get(field) != expected_value:
            raise _conflict(f"WC event {field} binding is invalid")
    event["event_id"] = _uuid("event.event_id", event.get("event_id"))
    event["correlation_id"] = _scoped_id(
        "event.correlation_id", event.get("correlation_id")
    )
    event["causation_id"] = _scoped_id("event.causation_id", event.get("causation_id"))
    return event


def _decision_record(value: ApprovalStageDecisionInput) -> dict[str, Any]:
    decided_by_type, decided_by_id = _entity_ref(
        "decided_by_ref", value.decided_by_ref, "oa.user"
    )
    decision = str(value.decision).strip().upper()
    if decision not in {"APPROVE", "REJECT"}:
        raise _invalid("decision", "must be APPROVE or REJECT")
    if value.decision_version != 1:
        raise _invalid("decision_version", "must be 1")
    if value.authorized_by_oa is not True:
        raise _invalid("authorized_by_oa", "must be true")
    if value.decision_comment is not None and (
        not isinstance(value.decision_comment, str)
        or len(value.decision_comment) > 2000
    ):
        raise _invalid("decision_comment", "is invalid")
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "approval_instance_id": _uuid(
            "approval_instance_id", value.approval_instance_id
        ),
        "approval_stage_id": _uuid("approval_stage_id", value.approval_stage_id),
        "wc_approval_work_item_id": _uuid(
            "wc_approval_work_item_id", value.wc_approval_work_item_id
        ),
        "wc_work_item_semantic_hash": _hash_ref(
            "wc_work_item_semantic_hash", value.wc_work_item_semantic_hash
        ),
        "wc_decision_id": _uuid("wc_decision_id", value.wc_decision_id),
        "wc_event_id": _uuid("wc_event_id", value.wc_event_id),
        "decision": decision,
        "decision_version": value.decision_version,
        "decided_by_ref_type": decided_by_type,
        "decided_by_id": decided_by_id,
        "decision_comment": value.decision_comment,
        "authorized_by_oa": value.authorized_by_oa,
        "oa_decision_ref": _scoped_id("oa_decision_ref", value.oa_decision_ref),
        "authorization_revision_hash": _hash_ref(
            "authorization_revision_hash", value.authorization_revision_hash
        ),
        "authorization_checked_at": _aware_datetime(
            "authorization_checked_at", value.authorization_checked_at
        ),
        "decided_at": _aware_datetime("decided_at", value.decided_at),
        "correlation_id": _scoped_id("correlation_id", value.correlation_id),
        "causation_id": _scoped_id("causation_id", value.causation_id),
    }


def _decision_hash(value: Mapping[str, Any]) -> str:
    return semantic_sha256_hash_ref(
        {
            "schema_version": "eos_approval_decision_binding.v1",
            **{
                field: (
                    _timestamp(value[field])
                    if field in {"authorization_checked_at", "decided_at"}
                    else value[field]
                )
                for field in (
                    "tenant_id",
                    "approval_instance_id",
                    "approval_stage_id",
                    "wc_approval_work_item_id",
                    "wc_work_item_semantic_hash",
                    "wc_decision_id",
                    "wc_event_id",
                    "decision",
                    "decision_version",
                    "decided_by_ref_type",
                    "decided_by_id",
                    "decision_comment",
                    "authorized_by_oa",
                    "oa_decision_ref",
                    "authorization_revision_hash",
                    "authorization_checked_at",
                    "decided_at",
                    "correlation_id",
                    "causation_id",
                )
            },
        }
    )


def _require_decision_time(value: Mapping[str, Any], *, recorded_at: datetime) -> None:
    if (
        value["decided_at"] > recorded_at
        or value["authorization_checked_at"] > recorded_at
    ):
        raise _conflict("WC decision or authorization timestamp is in the future")
    if (
        abs(value["authorization_checked_at"] - value["decided_at"])
        > _MAX_AUTHORIZATION_CLOCK_SKEW
    ):
        raise _conflict("WC OA authorization is not fresh for the decision")


def _require_transitionable_instance(
    instance: Mapping[str, Any], admitted: Mapping[str, Any]
) -> None:
    if instance["approval_domain"] != "BUSINESS_FORMAL":
        raise _conflict("Approval instance is not BUSINESS_FORMAL")
    if instance["state"] != "PENDING":
        raise _conflict("Approval instance is not pending")
    if (
        instance["expires_at"] is not None
        and _as_utc(instance["expires_at"]) <= admitted["decided_at"]
    ):
        raise _conflict("Approval instance expired before the WC decision")


def _require_active_stage(
    instance: Mapping[str, Any], stage: Mapping[str, Any]
) -> None:
    if (
        stage["state"] != "ACTIVE"
        or stage["stage_order"] != instance["active_stage_order"]
    ):
        raise _conflict("WC decision does not bind the active EOS stage")


def _decision_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "eos_approval_decision.v1",
        "tenant_id": value["tenant_id"],
        "approval_decision_id": str(value["approval_decision_id"]),
        "approval_instance_id": str(value["approval_instance_id"]),
        "approval_stage_id": str(value["approval_stage_id"]),
        "wc_approval_work_item_id": str(value["wc_approval_work_item_id"]),
        "wc_decision_id": str(value["wc_decision_id"]),
        "decision": value["decision"],
        "decision_version": value["decision_version"],
        "decided_by": {
            "type": value["decided_by_ref_type"],
            "id": value["decided_by_id"],
        },
        "decision_comment": value["decision_comment"],
        "authorized_by_oa": value["authorized_by_oa"],
        "oa_decision_ref": value["oa_decision_ref"],
        "authorization_revision_hash": value["authorization_revision_hash"],
        "authorization_checked_at": _timestamp(value["authorization_checked_at"]),
        "decided_at": _timestamp(value["decided_at"]),
        "decision_hash": value["decision_hash"],
        "recorded_at": _timestamp(value["recorded_at"]),
    }


def _proof_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    proof_id = str(value["approval_proof_id"])
    return {
        "schema_version": "eos_approval_proof.v1",
        "tenant_id": value["tenant_id"],
        "approval_proof_id": proof_id,
        "approval_proof_ref": f"eos.approval-proof:{proof_id}",
        "approval_instance_id": str(value["approval_instance_id"]),
        "business_operation_id": str(value["business_operation_id"]),
        "final_approval_stage_id": str(value["final_approval_stage_id"]),
        "final_wc_decision_id": str(value["final_wc_decision_id"]),
        "approval_domain": value["approval_domain"],
        "protected_operation_ref": value["protected_operation_ref"],
        "payload_hash": value["payload_hash"],
        "write_intent_hash": value["write_intent_hash"],
        "policy_hash": value["policy_hash"],
        "instance_binding_hash": value["instance_binding_hash"],
        "decision_chain_hash": value["decision_chain_hash"],
        "final_decision_hash": value["final_decision_hash"],
        "proof_version": value["proof_version"],
        "proof_hash": value["proof_hash"],
        "issued_at": _timestamp(value["issued_at"]),
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


def _aware_datetime(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(field_name, "must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _parse_timestamp(field_name: str, value: object) -> datetime:
    if not isinstance(value, str):
        raise _invalid(field_name, "must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(field_name, "must be an RFC 3339 timestamp") from exc
    return _aware_datetime(field_name, parsed)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _invalid(field_name: str, detail: str) -> EosApprovalTransitionError:
    return EosApprovalTransitionError(
        "EOS_APPROVAL_TRANSITION_INVALID",
        f"{field_name} {detail}",
        status_code=422,
    )


def _conflict(detail: str) -> EosApprovalTransitionError:
    return EosApprovalTransitionError(
        "EOS_APPROVAL_TRANSITION_CONFLICT",
        detail,
        status_code=409,
    )


def _persistence_error() -> EosApprovalTransitionError:
    return EosApprovalTransitionError(
        "EOS_APPROVAL_TRANSITION_PERSISTENCE_FAILED",
        "Approval transition persistence is unavailable",
        status_code=503,
        retryable=True,
    )
