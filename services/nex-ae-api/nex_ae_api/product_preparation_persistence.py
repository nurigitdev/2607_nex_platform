from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

WAIT_TYPES = frozenset({"WORK_RESULT", "NSL_APPROVAL", "PRODUCT_PREPARATION"})
RESUME_TARGET_KINDS = frozenset({"EXECUTABLE_STEP", "PRODUCT_COORDINATOR"})
EVENT_FAMILIES = frozenset({"WORK_RESULT", "NSL_APPROVAL", "PRODUCT_PREPARATION"})
PRODUCT_EVENT_TYPES = frozenset(
    {
        "PROPOSAL_REVIEW_SUBMITTED",
        "BUSINESS_APPROVAL_CHANGED",
        "VOUCHER_REVIEW_SUBMITTED",
        "ACCOUNTING_APPROVAL_CHANGED",
    }
)
PRODUCT_AUTHORITY_KINDS = frozenset(
    {
        "REQUESTER_PROPOSAL_REVIEW",
        "BUSINESS_FORMAL",
        "REQUESTER_VOUCHER_REVIEW",
        "ACCOUNTING_REVIEW",
    }
)
PRODUCT_CHECKPOINT_STAGE_KINDS = frozenset({"INITIAL", "WAITING", "READY", "TERMINAL"})
PRODUCT_PREPARATION_CHECKPOINT_SCHEMA_VERSION = "ae.product_preparation_checkpoint.v1"


@dataclass
class ProductPreparationPersistenceError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def seal_product_preparation_checkpoint(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _exact_mapping(
        value,
        {
            "tenant_id",
            "checkpoint_id",
            "checkpoint_schema_version",
            "checkpoint_version",
            "previous_checkpoint_id",
            "previous_checkpoint_hash",
            "agent_execution_id",
            "requester_ref",
            "work_intent_id",
            "work_intent_revision",
            "work_intent_hash",
            "agent_context_id",
            "context_generation",
            "context_hash",
            "business_context_hash",
            "capability_id",
            "capability_version",
            "capability_release_ref",
            "capability_registration_hash",
            "coordinator_id",
            "coordinator_version",
            "coordinator_registration_hash",
            "preparation_adapter_source_identity",
            "materializer_source_identity",
            "stage",
            "stage_kind",
            "authority_refs",
            "idempotency_key",
            "correlation_id",
            "causation_id",
            "created_at",
        },
        "Product Preparation checkpoint",
    )
    normalized = {
        "tenant_id": _text(record["tenant_id"], "tenant_id", 128),
        "checkpoint_id": _uuid(record["checkpoint_id"], "checkpoint_id"),
        "checkpoint_schema_version": _text(
            record["checkpoint_schema_version"], "checkpoint_schema_version", 64
        ),
        "checkpoint_version": _positive_int(
            record["checkpoint_version"], "checkpoint_version"
        ),
        "previous_checkpoint_id": _nullable_uuid(
            record["previous_checkpoint_id"], "previous_checkpoint_id"
        ),
        "previous_checkpoint_hash": _nullable_hash(
            record["previous_checkpoint_hash"], "previous_checkpoint_hash"
        ),
        "agent_execution_id": _uuid(record["agent_execution_id"], "agent_execution_id"),
        "requester_ref": _text(record["requester_ref"], "requester_ref", 200),
        "work_intent_id": _uuid(record["work_intent_id"], "work_intent_id"),
        "work_intent_revision": _positive_int(
            record["work_intent_revision"], "work_intent_revision"
        ),
        "work_intent_hash": _hash(record["work_intent_hash"], "work_intent_hash"),
        "agent_context_id": _uuid(record["agent_context_id"], "agent_context_id"),
        "context_generation": _positive_int(
            record["context_generation"], "context_generation"
        ),
        "context_hash": _hash(record["context_hash"], "context_hash"),
        "business_context_hash": _hash(
            record["business_context_hash"], "business_context_hash"
        ),
        "capability_id": _text(record["capability_id"], "capability_id", 160),
        "capability_version": _text(
            record["capability_version"], "capability_version", 64
        ),
        "capability_release_ref": _text(
            record["capability_release_ref"], "capability_release_ref", 512
        ),
        "capability_registration_hash": _hash(
            record["capability_registration_hash"],
            "capability_registration_hash",
        ),
        "coordinator_id": _text(record["coordinator_id"], "coordinator_id", 160),
        "coordinator_version": _text(
            record["coordinator_version"], "coordinator_version", 64
        ),
        "coordinator_registration_hash": _hash(
            record["coordinator_registration_hash"],
            "coordinator_registration_hash",
        ),
        "preparation_adapter_source_identity": _text(
            record["preparation_adapter_source_identity"],
            "preparation_adapter_source_identity",
            512,
        ),
        "materializer_source_identity": _text(
            record["materializer_source_identity"],
            "materializer_source_identity",
            512,
        ),
        "stage": _text(record["stage"], "stage", 64),
        "stage_kind": _enum(
            record["stage_kind"], PRODUCT_CHECKPOINT_STAGE_KINDS, "stage_kind"
        ),
        "authority_refs": _array(record["authority_refs"], "authority_refs", 32),
        "idempotency_key": _text(record["idempotency_key"], "idempotency_key", 512),
        "correlation_id": _text(record["correlation_id"], "correlation_id", 256),
        "causation_id": _nullable_text(record["causation_id"], "causation_id", 256),
        "created_at": _time(record["created_at"], "created_at"),
    }
    _checkpoint_chain(normalized)
    projection = _checkpoint_semantic_projection(normalized)
    checkpoint_hash = semantic_sha256_hash_ref(projection)
    projection["checkpoint_hash"] = checkpoint_hash
    return {
        **normalized,
        "checkpoint_projection": projection,
        "checkpoint_hash": checkpoint_hash,
    }


def product_preparation_wait_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _exact_mapping(
        value,
        {
            "tenant_id",
            "wait_id",
            "agent_execution_id",
            "external_ref",
            "wait_contract_ref",
            "created_at",
        },
        "Product Preparation wait envelope",
    )
    return {
        "tenant_id": _text(record["tenant_id"], "tenant_id", 128),
        "wait_id": _uuid(record["wait_id"], "wait_id"),
        "agent_execution_id": _uuid(record["agent_execution_id"], "agent_execution_id"),
        "executable_step_id": None,
        "wait_type": "PRODUCT_PREPARATION",
        "external_ref": _text(record["external_ref"], "external_ref", 512),
        "result_contract_ref": None,
        "wait_contract_ref": _text(
            record["wait_contract_ref"], "wait_contract_ref", 512
        ),
        "resume_target_kind": "PRODUCT_COORDINATOR",
        "nsl_execution_id": None,
        "business_operation_id": None,
        "approval_request_id": None,
        "checkpoint_version": None,
        "created_at": _time(record["created_at"], "created_at"),
    }


def seal_product_preparation_wait_binding(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    record = _exact_mapping(
        value,
        {
            "tenant_id",
            "wait_id",
            "checkpoint_id",
            "checkpoint_hash",
            "coordinator_id",
            "coordinator_version",
            "coordinator_registration_hash",
            "expected_event_type",
            "authority_kind",
            "authority_ref",
            "agent_execution_id",
            "work_intent_id",
            "created_at",
        },
        "Product Preparation wait binding",
    )
    normalized = {
        "tenant_id": _text(record["tenant_id"], "tenant_id", 128),
        "wait_id": _uuid(record["wait_id"], "wait_id"),
        "checkpoint_id": _uuid(record["checkpoint_id"], "checkpoint_id"),
        "checkpoint_hash": _hash(record["checkpoint_hash"], "checkpoint_hash"),
        "coordinator_id": _text(record["coordinator_id"], "coordinator_id", 160),
        "coordinator_version": _text(
            record["coordinator_version"], "coordinator_version", 64
        ),
        "coordinator_registration_hash": _hash(
            record["coordinator_registration_hash"],
            "coordinator_registration_hash",
        ),
        "expected_event_type": _enum(
            record["expected_event_type"],
            PRODUCT_EVENT_TYPES,
            "expected_event_type",
        ),
        "authority_kind": _enum(
            record["authority_kind"], PRODUCT_AUTHORITY_KINDS, "authority_kind"
        ),
        "authority_ref": _text(record["authority_ref"], "authority_ref", 512),
        "agent_execution_id": _uuid(record["agent_execution_id"], "agent_execution_id"),
        "work_intent_id": _uuid(record["work_intent_id"], "work_intent_id"),
        "created_at": _time(record["created_at"], "created_at"),
    }
    _authority_pair(normalized)
    return {
        **normalized,
        "binding_hash": semantic_sha256_hash_ref(_without(normalized, "created_at")),
    }


def seal_product_preparation_event(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _exact_mapping(
        value,
        {
            "tenant_id",
            "event_id",
            "event_type",
            "external_ref",
            "event_payload",
            "received_at",
        },
        "Product Preparation event envelope",
    )
    normalized = {
        "tenant_id": _text(record["tenant_id"], "tenant_id", 128),
        "event_id": _text(record["event_id"], "event_id", 256),
        "event_family": "PRODUCT_PREPARATION",
        "event_type": _enum(record["event_type"], PRODUCT_EVENT_TYPES, "event_type"),
        "external_ref": _text(record["external_ref"], "external_ref", 512),
        "event_payload": _object(record["event_payload"], "event_payload"),
        "received_at": _time(record["received_at"], "received_at"),
        "result_id": None,
        "result_contract_ref": None,
        "approval_request_id": None,
        "approval_work_item_ref": None,
        "approval_evidence_ref": None,
        "evidence_integrity": None,
        "nsl_execution_id": None,
        "business_operation_id": None,
    }
    normalized["event_semantic_hash"] = semantic_sha256_hash_ref(
        {
            "event_family": normalized["event_family"],
            "event_type": normalized["event_type"],
            "external_ref": normalized["external_ref"],
            "event_payload": normalized["event_payload"],
        }
    )
    return normalized


def seal_product_preparation_event_binding(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    record = _exact_mapping(
        value,
        {
            "tenant_id",
            "event_id",
            "wait_id",
            "checkpoint_id",
            "checkpoint_hash",
            "coordinator_id",
            "coordinator_version",
            "coordinator_registration_hash",
            "authority_kind",
            "notification_ref",
            "agent_execution_id",
            "work_intent_id",
            "created_at",
        },
        "Product Preparation event binding",
    )
    normalized = {
        "tenant_id": _text(record["tenant_id"], "tenant_id", 128),
        "event_id": _text(record["event_id"], "event_id", 256),
        "wait_id": _uuid(record["wait_id"], "wait_id"),
        "checkpoint_id": _uuid(record["checkpoint_id"], "checkpoint_id"),
        "checkpoint_hash": _hash(record["checkpoint_hash"], "checkpoint_hash"),
        "coordinator_id": _text(record["coordinator_id"], "coordinator_id", 160),
        "coordinator_version": _text(
            record["coordinator_version"], "coordinator_version", 64
        ),
        "coordinator_registration_hash": _hash(
            record["coordinator_registration_hash"],
            "coordinator_registration_hash",
        ),
        "authority_kind": _enum(
            record["authority_kind"], PRODUCT_AUTHORITY_KINDS, "authority_kind"
        ),
        "notification_ref": _text(record["notification_ref"], "notification_ref", 512),
        "agent_execution_id": _uuid(record["agent_execution_id"], "agent_execution_id"),
        "work_intent_id": _uuid(record["work_intent_id"], "work_intent_id"),
        "created_at": _time(record["created_at"], "created_at"),
    }
    return {
        **normalized,
        "binding_hash": semantic_sha256_hash_ref(_without(normalized, "created_at")),
    }


class SqlAlchemyProductPreparationCheckpointRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def append(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _checkpoint(checkpoint)
        try:
            with self._sessions() as session:
                session.execute(
                    text(_checkpoint_insert_sql(session)),
                    _checkpoint_params(normalized),
                )
                saved = _load_checkpoint(
                    session,
                    tenant_id=normalized["tenant_id"],
                    checkpoint_id=normalized["checkpoint_id"],
                    idempotency_key=normalized["idempotency_key"],
                )
                if saved is None:
                    raise _conflict("Product Preparation checkpoint was not persisted.")
                if not _same(saved, normalized, _CHECKPOINT_REPLAY_FIELDS):
                    raise _conflict("Product Preparation checkpoint replay differs.")
                session.commit()
                return saved
        except ProductPreparationPersistenceError:
            raise
        except IntegrityError as exc:
            raise _rejected("Product Preparation checkpoint was rejected.") from exc
        except DBAPIError as exc:
            raise _database_error(exc)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get(self, *, tenant_id: str, checkpoint_id: str) -> dict[str, Any] | None:
        try:
            with self._sessions() as session:
                return _load_checkpoint(
                    session,
                    tenant_id=_text(tenant_id, "tenant_id", 128),
                    checkpoint_id=_uuid(checkpoint_id, "checkpoint_id"),
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def latest(
        self,
        *,
        tenant_id: str,
        agent_execution_id: str,
        coordinator_id: str,
        coordinator_version: str,
    ) -> dict[str, Any] | None:
        params = {
            "tenant_id": _text(tenant_id, "tenant_id", 128),
            "agent_execution_id": _uuid(agent_execution_id, "agent_execution_id"),
            "coordinator_id": _text(coordinator_id, "coordinator_id", 160),
            "coordinator_version": _text(
                coordinator_version, "coordinator_version", 64
            ),
        }
        try:
            with self._sessions() as session:
                row = (
                    session.execute(text(_LATEST_CHECKPOINT_SQL), params)
                    .mappings()
                    .first()
                )
                return None if row is None else _checkpoint_projection(row)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


class SqlAlchemyGeneralizedWaitEventRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def register_wait(
        self,
        wait: Mapping[str, Any],
        *,
        product_binding: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = _wait(wait)
        binding = _product_wait_binding(product_binding, wait=normalized)
        try:
            with self._sessions() as session:
                session.execute(text(_WAIT_INSERT_SQL), normalized)
                if binding is not None:
                    session.execute(text(_WAIT_BINDING_INSERT_SQL), binding)
                saved = _load_wait(session, normalized)
                saved_binding = (
                    None
                    if binding is None
                    else _load_wait_binding(
                        session,
                        tenant_id=normalized["tenant_id"],
                        wait_id=normalized["wait_id"],
                    )
                )
                if saved is None or not _same(saved, normalized, _WAIT_REPLAY_FIELDS):
                    raise _conflict("WaitRegistration replay differs.")
                if binding is not None and (
                    saved_binding is None
                    or not _same(saved_binding, binding, _WAIT_BINDING_REPLAY_FIELDS)
                ):
                    raise _conflict("Product Preparation wait binding replay differs.")
                session.commit()
                return {"wait": saved, "product_binding": saved_binding}
        except ProductPreparationPersistenceError:
            raise
        except IntegrityError as exc:
            raise _rejected("WaitRegistration was rejected.") from exc
        except DBAPIError as exc:
            raise _database_error(exc)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def accept_event(
        self,
        event: Mapping[str, Any],
        *,
        product_binding: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = _event(event)
        binding = _product_event_binding(product_binding, event=normalized)
        try:
            with self._sessions() as session:
                session.execute(
                    text(_event_insert_sql(session)), _event_params(normalized)
                )
                if binding is not None:
                    session.execute(text(_EVENT_BINDING_INSERT_SQL), binding)
                saved = _load_event(
                    session,
                    tenant_id=normalized["tenant_id"],
                    event_id=normalized["event_id"],
                )
                saved_binding = (
                    None
                    if binding is None
                    else _load_event_binding(
                        session,
                        tenant_id=normalized["tenant_id"],
                        event_id=normalized["event_id"],
                    )
                )
                if saved is None or not _same(saved, normalized, _EVENT_REPLAY_FIELDS):
                    raise _conflict("External event replay differs.")
                if binding is not None and (
                    saved_binding is None
                    or not _same(saved_binding, binding, _EVENT_BINDING_REPLAY_FIELDS)
                ):
                    raise _conflict("Product Preparation event binding replay differs.")
                session.commit()
                return {"event": saved, "product_binding": saved_binding}
        except ProductPreparationPersistenceError:
            raise
        except IntegrityError as exc:
            raise _rejected("External event was rejected.") from exc
        except DBAPIError as exc:
            raise _database_error(exc)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_wait(self, *, tenant_id: str, wait_id: str) -> dict[str, Any] | None:
        params = {
            "tenant_id": _text(tenant_id, "tenant_id", 128),
            "wait_id": _uuid(wait_id, "wait_id"),
        }
        try:
            with self._sessions() as session:
                row = session.execute(text(_WAIT_BY_ID_SQL), params).mappings().first()
                return None if row is None else _wait_projection(row)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_event(self, *, tenant_id: str, event_id: str) -> dict[str, Any] | None:
        try:
            with self._sessions() as session:
                return _load_event(
                    session,
                    tenant_id=_text(tenant_id, "tenant_id", 128),
                    event_id=_text(event_id, "event_id", 256),
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def load_product_wait_context(
        self, *, tenant_id: str, wait_id: str
    ) -> dict[str, Any] | None:
        params = {
            "tenant_id": _text(tenant_id, "tenant_id", 128),
            "wait_id": _uuid(wait_id, "wait_id"),
        }
        try:
            with self._sessions() as session:
                row = (
                    session.execute(text(_PRODUCT_WAIT_CONTEXT_SQL), params)
                    .mappings()
                    .first()
                )
                if row is None:
                    return None
                return {
                    "wait": _wait_projection(row),
                    "product_binding": _wait_binding_projection(row, prefix="binding_"),
                    "checkpoint": _checkpoint_projection(row, prefix="checkpoint_"),
                }
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def resolve_product_wait_context(
        self,
        *,
        tenant_id: str,
        authority_kind: str,
        authority_ref: str,
    ) -> dict[str, Any] | None:
        params = {
            "tenant_id": _text(tenant_id, "tenant_id", 128),
            "authority_kind": _text(authority_kind, "authority_kind", 64),
            "authority_ref": _text(authority_ref, "authority_ref", 512),
        }
        try:
            with self._sessions() as session:
                rows = (
                    session.execute(text(_PRODUCT_WAIT_BY_AUTHORITY_SQL), params)
                    .mappings()
                    .all()
                )
                if not rows:
                    return None
                if len(rows) != 1:
                    raise _conflict(
                        "Product Preparation authority resolves to multiple waits."
                    )
                row = rows[0]
                return {
                    "wait": _wait_projection(row),
                    "product_binding": _wait_binding_projection(row, prefix="binding_"),
                    "checkpoint": _checkpoint_projection(row, prefix="checkpoint_"),
                }
        except ProductPreparationPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def load_product_event_context(
        self, *, tenant_id: str, event_id: str
    ) -> dict[str, Any] | None:
        normalized_tenant = _text(tenant_id, "tenant_id", 128)
        normalized_event = _text(event_id, "event_id", 256)
        try:
            with self._sessions() as session:
                event = _load_event(
                    session,
                    tenant_id=normalized_tenant,
                    event_id=normalized_event,
                )
                if event is None:
                    return None
                if event["event_family"] != "PRODUCT_PREPARATION":
                    raise _conflict("Event is not a Product Preparation event.")
                event_binding = _load_event_binding(
                    session,
                    tenant_id=normalized_tenant,
                    event_id=normalized_event,
                )
                if event_binding is None:
                    raise _conflict("Product Preparation event binding is missing.")
                wait = _load_wait(session, event_binding)
                wait_binding = _load_wait_binding(
                    session,
                    tenant_id=normalized_tenant,
                    wait_id=event_binding["wait_id"],
                )
                checkpoint = _load_checkpoint(
                    session,
                    tenant_id=normalized_tenant,
                    checkpoint_id=event_binding["checkpoint_id"],
                )
                if wait is None or wait_binding is None or checkpoint is None:
                    raise _conflict(
                        "Product Preparation event resume lineage is incomplete."
                    )
                return {
                    "event": event,
                    "event_binding": event_binding,
                    "wait": wait,
                    "wait_binding": wait_binding,
                    "checkpoint": checkpoint,
                }
        except ProductPreparationPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def _checkpoint(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = seal_product_preparation_checkpoint(
        _without(value, "checkpoint_projection", "checkpoint_hash")
    )
    supplied = _exact_mapping(
        value,
        set(expected),
        "sealed Product Preparation checkpoint",
    )
    if supplied != expected:
        raise _invalid("Product Preparation checkpoint seal differs from content.")
    return expected


def _wait(value: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(value)
    required = {
        "tenant_id",
        "wait_id",
        "agent_execution_id",
        "executable_step_id",
        "wait_type",
        "external_ref",
        "result_contract_ref",
        "wait_contract_ref",
        "resume_target_kind",
        "nsl_execution_id",
        "business_operation_id",
        "approval_request_id",
        "checkpoint_version",
        "created_at",
    }
    _require_fields(record, required, "WaitRegistration envelope")
    normalized = {
        "tenant_id": _text(record["tenant_id"], "tenant_id", 128),
        "wait_id": _uuid(record["wait_id"], "wait_id"),
        "agent_execution_id": _uuid(record["agent_execution_id"], "agent_execution_id"),
        "executable_step_id": _nullable_uuid(
            record["executable_step_id"], "executable_step_id"
        ),
        "wait_type": _enum(record["wait_type"], WAIT_TYPES, "wait_type"),
        "external_ref": _text(record["external_ref"], "external_ref", 512),
        "result_contract_ref": _nullable_text(
            record["result_contract_ref"], "result_contract_ref", 512
        ),
        "wait_contract_ref": _text(
            record["wait_contract_ref"], "wait_contract_ref", 512
        ),
        "resume_target_kind": _enum(
            record["resume_target_kind"],
            RESUME_TARGET_KINDS,
            "resume_target_kind",
        ),
        "nsl_execution_id": _nullable_text(
            record["nsl_execution_id"], "nsl_execution_id", 256
        ),
        "business_operation_id": _nullable_text(
            record["business_operation_id"], "business_operation_id", 256
        ),
        "approval_request_id": _nullable_text(
            record["approval_request_id"], "approval_request_id", 256
        ),
        "checkpoint_version": _nullable_positive_int(
            record["checkpoint_version"], "checkpoint_version"
        ),
        "created_at": _time(record["created_at"], "created_at"),
    }
    _wait_shape(normalized)
    return normalized


def _event(value: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(value)
    required = {
        "tenant_id",
        "event_id",
        "event_family",
        "event_type",
        "event_semantic_hash",
        "external_ref",
        "event_payload",
        "received_at",
        "result_id",
        "result_contract_ref",
        "approval_request_id",
        "approval_work_item_ref",
        "approval_evidence_ref",
        "evidence_integrity",
        "nsl_execution_id",
        "business_operation_id",
    }
    _require_fields(record, required, "external event envelope")
    normalized = {
        "tenant_id": _text(record["tenant_id"], "tenant_id", 128),
        "event_id": _text(record["event_id"], "event_id", 256),
        "event_family": _enum(record["event_family"], EVENT_FAMILIES, "event_family"),
        "event_type": _text(record["event_type"], "event_type", 64),
        "event_semantic_hash": _hash(
            record["event_semantic_hash"], "event_semantic_hash"
        ),
        "external_ref": _text(record["external_ref"], "external_ref", 512),
        "event_payload": _object(record["event_payload"], "event_payload"),
        "received_at": _time(record["received_at"], "received_at"),
        "result_id": _nullable_text(record["result_id"], "result_id", 256),
        "result_contract_ref": _nullable_text(
            record["result_contract_ref"], "result_contract_ref", 512
        ),
        "approval_request_id": _nullable_text(
            record["approval_request_id"], "approval_request_id", 256
        ),
        "approval_work_item_ref": _nullable_text(
            record["approval_work_item_ref"], "approval_work_item_ref", 128
        ),
        "approval_evidence_ref": _nullable_text(
            record["approval_evidence_ref"], "approval_evidence_ref", 512
        ),
        "evidence_integrity": _nullable_hash(
            record["evidence_integrity"], "evidence_integrity"
        ),
        "nsl_execution_id": _nullable_text(
            record["nsl_execution_id"], "nsl_execution_id", 256
        ),
        "business_operation_id": _nullable_text(
            record["business_operation_id"], "business_operation_id", 256
        ),
    }
    _event_shape(normalized)
    return normalized


def _product_wait_binding(
    value: Mapping[str, Any] | None, *, wait: Mapping[str, Any]
) -> dict[str, Any] | None:
    if wait["wait_type"] != "PRODUCT_PREPARATION":
        if value is not None:
            raise _invalid("Legacy wait envelopes cannot carry a Product binding.")
        return None
    if value is None:
        raise _invalid("Product Preparation wait requires its typed binding.")
    expected = seal_product_preparation_wait_binding(_without(value, "binding_hash"))
    supplied = _exact_mapping(value, set(expected), "sealed Product wait binding")
    if supplied != expected:
        raise _invalid("Product Preparation wait binding seal differs from content.")
    for field in ("tenant_id", "wait_id", "agent_execution_id"):
        if expected[field] != wait[field]:
            raise _invalid("Product Preparation wait binding lineage differs.")
    if expected["authority_ref"] != wait["external_ref"]:
        raise _invalid("Product Preparation wait authority reference differs.")
    return expected


def _product_event_binding(
    value: Mapping[str, Any] | None, *, event: Mapping[str, Any]
) -> dict[str, Any] | None:
    if event["event_family"] != "PRODUCT_PREPARATION":
        if value is not None:
            raise _invalid("Legacy event envelopes cannot carry a Product binding.")
        return None
    if value is None:
        raise _invalid("Product Preparation event requires its typed binding.")
    expected = seal_product_preparation_event_binding(_without(value, "binding_hash"))
    supplied = _exact_mapping(value, set(expected), "sealed Product event binding")
    if supplied != expected:
        raise _invalid("Product Preparation event binding seal differs from content.")
    if (
        expected["tenant_id"] != event["tenant_id"]
        or expected["event_id"] != event["event_id"]
    ):
        raise _invalid("Product Preparation event binding lineage differs.")
    if expected["notification_ref"] != event["event_payload"].get("notification_ref"):
        raise _invalid("Product Preparation notification reference differs.")
    return expected


def _checkpoint_chain(value: Mapping[str, Any]) -> None:
    first = value["checkpoint_version"] == 1
    if first != (
        value["previous_checkpoint_id"] is None
        and value["previous_checkpoint_hash"] is None
    ):
        raise _invalid("Product Preparation checkpoint chain is invalid.")


def _wait_shape(value: Mapping[str, Any]) -> None:
    if value["wait_type"] == "PRODUCT_PREPARATION":
        if (
            value["resume_target_kind"] != "PRODUCT_COORDINATOR"
            or value["executable_step_id"] is not None
            or value["result_contract_ref"] is not None
            or any(
                value[field] is not None
                for field in (
                    "nsl_execution_id",
                    "business_operation_id",
                    "approval_request_id",
                    "checkpoint_version",
                )
            )
        ):
            raise _invalid("Product Preparation wait envelope is invalid.")
        return
    if (
        value["resume_target_kind"] != "EXECUTABLE_STEP"
        or value["executable_step_id"] is None
        or value["result_contract_ref"] != value["wait_contract_ref"]
    ):
        raise _invalid("Executable-step wait envelope is invalid.")
    lineage = (
        value["nsl_execution_id"],
        value["business_operation_id"],
        value["approval_request_id"],
        value["checkpoint_version"],
    )
    if value["wait_type"] == "WORK_RESULT" and any(
        item is not None for item in lineage
    ):
        raise _invalid("WorkResult wait cannot carry NSL lineage.")
    if value["wait_type"] == "NSL_APPROVAL" and (
        any(item is None for item in lineage)
        or value["external_ref"] != value["approval_request_id"]
    ):
        raise _invalid("NSL approval wait lineage is invalid.")


def _event_shape(value: Mapping[str, Any]) -> None:
    family = value["event_family"]
    if family == "PRODUCT_PREPARATION":
        expected_hash = semantic_sha256_hash_ref(
            {
                "event_family": family,
                "event_type": value["event_type"],
                "external_ref": value["external_ref"],
                "event_payload": value["event_payload"],
            }
        )
        legacy_fields = (
            "result_id",
            "result_contract_ref",
            "approval_request_id",
            "approval_work_item_ref",
            "approval_evidence_ref",
            "evidence_integrity",
            "nsl_execution_id",
            "business_operation_id",
        )
        if (
            value["event_type"] not in PRODUCT_EVENT_TYPES
            or value["event_semantic_hash"] != expected_hash
            or any(value[field] is not None for field in legacy_fields)
        ):
            raise _invalid("Product Preparation event envelope is invalid.")
        return
    expected = {
        "WORK_RESULT": "WORK_RESULT_SUBMITTED",
        "NSL_APPROVAL": "NSL_APPROVAL_DECIDED",
    }
    if value["event_type"] != expected.get(family):
        raise _invalid("Legacy event family and type differ.")
    if family == "WORK_RESULT":
        if value["result_id"] is None or any(
            value[field] is not None
            for field in (
                "approval_request_id",
                "approval_work_item_ref",
                "approval_evidence_ref",
                "evidence_integrity",
                "nsl_execution_id",
                "business_operation_id",
            )
        ):
            raise _invalid("WorkResult event lineage is invalid.")
        return
    if (
        value["result_id"] is not None
        or value["result_contract_ref"] is not None
        or any(
            value[field] is None
            for field in (
                "approval_request_id",
                "approval_work_item_ref",
                "approval_evidence_ref",
                "evidence_integrity",
                "nsl_execution_id",
                "business_operation_id",
            )
        )
        or value["external_ref"] != value["approval_request_id"]
    ):
        raise _invalid("NSL approval event lineage is invalid.")


def _authority_pair(value: Mapping[str, Any]) -> None:
    expected = {
        "REQUESTER_PROPOSAL_REVIEW": "PROPOSAL_REVIEW_SUBMITTED",
        "BUSINESS_FORMAL": "BUSINESS_APPROVAL_CHANGED",
        "REQUESTER_VOUCHER_REVIEW": "VOUCHER_REVIEW_SUBMITTED",
        "ACCOUNTING_REVIEW": "ACCOUNTING_APPROVAL_CHANGED",
    }
    if value["expected_event_type"] != expected[value["authority_kind"]]:
        raise _invalid("Product Preparation authority and event type differ.")


def _checkpoint_semantic_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": value["checkpoint_schema_version"],
        "checkpoint_id": value["checkpoint_id"],
        "checkpoint_version": value["checkpoint_version"],
        "previous_checkpoint_id": value["previous_checkpoint_id"],
        "previous_checkpoint_hash": value["previous_checkpoint_hash"],
        "tenant_id": value["tenant_id"],
        "agent_execution_id": value["agent_execution_id"],
        "requester_ref": value["requester_ref"],
        "work_intent_id": value["work_intent_id"],
        "work_intent_revision": value["work_intent_revision"],
        "work_intent_hash": value["work_intent_hash"],
        "agent_context_id": value["agent_context_id"],
        "context_generation": value["context_generation"],
        "context_hash": value["context_hash"],
        "business_context_hash": value["business_context_hash"],
        "capability_id": value["capability_id"],
        "capability_version": value["capability_version"],
        "capability_release_ref": value["capability_release_ref"],
        "capability_registration_hash": value["capability_registration_hash"],
        "coordinator_id": value["coordinator_id"],
        "coordinator_version": value["coordinator_version"],
        "coordinator_registration_hash": value["coordinator_registration_hash"],
        "preparation_adapter_source_identity": value[
            "preparation_adapter_source_identity"
        ],
        "materializer_source_identity": value["materializer_source_identity"],
        "stage": value["stage"],
        "stage_kind": value["stage_kind"],
        "authority_refs": copy.deepcopy(value["authority_refs"]),
        "idempotency_key": value["idempotency_key"],
        "correlation_id": value["correlation_id"],
        "causation_id": value["causation_id"],
    }


def _checkpoint_params(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **value,
        "authority_refs_json": json.dumps(value["authority_refs"], sort_keys=True),
        "checkpoint_projection_json": json.dumps(
            value["checkpoint_projection"], sort_keys=True
        ),
    }


def _event_params(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **value,
        "event_payload_json": json.dumps(value["event_payload"], sort_keys=True),
    }


def _load_checkpoint(
    session: Session,
    *,
    tenant_id: str,
    checkpoint_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any] | None:
    clauses = ["tenant_id = :tenant_id"]
    params: dict[str, Any] = {"tenant_id": tenant_id}
    if checkpoint_id is not None:
        clauses.append("checkpoint_id = :checkpoint_id")
        params["checkpoint_id"] = checkpoint_id
    if idempotency_key is not None:
        clauses.append("idempotency_key = :idempotency_key")
        params["idempotency_key"] = idempotency_key
    row = (
        session.execute(
            text(
                _CHECKPOINT_SELECT
                + " WHERE "
                + " OR ".join([clauses[0] + " AND " + clause for clause in clauses[1:]])
            ),
            params,
        )
        .mappings()
        .first()
    )
    return None if row is None else _checkpoint_projection(row)


def _load_wait(session: Session, expected: Mapping[str, Any]) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(_WAIT_BY_ID_SQL),
            {"tenant_id": expected["tenant_id"], "wait_id": expected["wait_id"]},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return _wait_projection(row)


def _load_event(
    session: Session, *, tenant_id: str, event_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(_EVENT_BY_ID_SQL),
            {"tenant_id": tenant_id, "event_id": event_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _event_projection(row)


def _load_wait_binding(
    session: Session, *, tenant_id: str, wait_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(_WAIT_BINDING_BY_ID_SQL),
            {"tenant_id": tenant_id, "wait_id": wait_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _wait_binding_projection(row)


def _load_event_binding(
    session: Session, *, tenant_id: str, event_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(_EVENT_BINDING_BY_ID_SQL),
            {"tenant_id": tenant_id, "event_id": event_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _event_binding_projection(row)


def _checkpoint_projection(
    row: Mapping[str, Any], *, prefix: str = ""
) -> dict[str, Any]:
    fields = _CHECKPOINT_FIELDS
    result = {field: row[prefix + field] for field in fields}
    for field in (
        "checkpoint_id",
        "previous_checkpoint_id",
        "agent_execution_id",
        "work_intent_id",
        "agent_context_id",
    ):
        result[field] = None if result[field] is None else str(result[field])
    result["authority_refs"] = _json(result["authority_refs"], "authority_refs")
    result["checkpoint_projection"] = _json(
        result["checkpoint_projection"], "checkpoint_projection"
    )
    result["created_at"] = _stored_time(result["created_at"])
    return result


def _wait_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    result = {field: row[field] for field in _WAIT_FIELDS}
    for field in ("wait_id", "agent_execution_id", "executable_step_id"):
        result[field] = None if result[field] is None else str(result[field])
    result["version"] = int(result["version"])
    result["created_at"] = _stored_time(result["created_at"])
    result["satisfied_at"] = _stored_nullable_time(result["satisfied_at"])
    result["updated_at"] = _stored_nullable_time(result["updated_at"])
    return result


def _event_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    result = {field: row[field] for field in _EVENT_FIELDS}
    result["event_payload"] = _json(result["event_payload"], "event_payload")
    result["received_at"] = _stored_time(result["received_at"])
    result["processed_at"] = _stored_nullable_time(result["processed_at"])
    return result


def _wait_binding_projection(
    row: Mapping[str, Any], *, prefix: str = ""
) -> dict[str, Any]:
    result = {field: row[prefix + field] for field in _WAIT_BINDING_FIELDS}
    for field in ("wait_id", "checkpoint_id", "agent_execution_id", "work_intent_id"):
        result[field] = str(result[field])
    result["created_at"] = _stored_time(result["created_at"])
    return result


def _event_binding_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    result = {field: row[field] for field in _EVENT_BINDING_FIELDS}
    for field in ("wait_id", "checkpoint_id", "agent_execution_id", "work_intent_id"):
        result[field] = str(result[field])
    result["created_at"] = _stored_time(result["created_at"])
    return result


def _same(
    saved: Mapping[str, Any], expected: Mapping[str, Any], fields: tuple[str, ...]
) -> bool:
    return all(saved.get(field) == expected.get(field) for field in fields)


def _json(value: object, field: str) -> Any:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise _invalid(f"{field} must be valid JSON.") from exc
    if not isinstance(parsed, (dict, list)):
        raise _invalid(f"{field} must be JSON object or array.")
    return copy.deepcopy(parsed)


def _object(value: object, field: str) -> dict[str, Any]:
    parsed = _json(value, field)
    if not isinstance(parsed, dict):
        raise _invalid(f"{field} must be an object.")
    return parsed


def _array(value: object, field: str, maximum: int) -> list[Any]:
    parsed = _json(value, field)
    if not isinstance(parsed, list) or len(parsed) > maximum:
        raise _invalid(f"{field} must be an array of at most {maximum} values.")
    return parsed


def _exact_mapping(
    value: Mapping[str, Any], fields: set[str], label: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid(f"{label} fields are invalid.")
    return dict(value)


def _require_fields(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise _invalid(f"{label} fields are invalid.")


def _without(value: Mapping[str, Any], *fields: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in fields}


def _uuid(value: object, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a UUID.") from exc


def _nullable_uuid(value: object, field: str) -> str | None:
    return None if value is None else _uuid(value, field)


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} must be a bounded non-empty string.")
    return value.strip()


def _nullable_text(value: object, field: str, maximum: int) -> str | None:
    return None if value is None else _text(value, field, maximum)


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _invalid(f"{field} must be a positive integer.")
    return value


def _nullable_positive_int(value: object, field: str) -> int | None:
    return None if value is None else _positive_int(value, field)


def _hash(value: object, field: str) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a SHA-256 hash reference.") from exc


def _nullable_hash(value: object, field: str) -> str | None:
    return None if value is None else _hash(value, field)


def _enum(value: object, allowed: frozenset[str], field: str) -> str:
    normalized = _text(value, field, 64)
    if normalized not in allowed:
        raise _invalid(f"{field} is not admitted.")
    return normalized


def _time(value: object, field: str) -> str:
    text_value = _text(value, field, 64)
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC3339 timestamp.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} must include a timezone.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _stored_time(value: object) -> str:
    if isinstance(value, datetime):
        parsed = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return _time(str(value), "stored timestamp")


def _stored_nullable_time(value: object) -> str | None:
    return None if value is None else _stored_time(value)


def _invalid(detail: str) -> ProductPreparationPersistenceError:
    return ProductPreparationPersistenceError(
        "ae.product_preparation_persistence_invalid", detail
    )


def _conflict(detail: str) -> ProductPreparationPersistenceError:
    return ProductPreparationPersistenceError(
        "ae.product_preparation_persistence_conflict", detail
    )


def _rejected(detail: str) -> ProductPreparationPersistenceError:
    return ProductPreparationPersistenceError(
        "ae.product_preparation_persistence_rejected", detail
    )


def _unavailable() -> ProductPreparationPersistenceError:
    return ProductPreparationPersistenceError(
        "ae.product_preparation_persistence_unavailable",
        "Product Preparation persistence is unavailable.",
        True,
    )


def _database_error(exc: DBAPIError) -> ProductPreparationPersistenceError:
    return (
        _unavailable()
        if exc.connection_invalidated
        else _rejected("Product Preparation persistence was rejected.")
    )


def _checkpoint_insert_sql(session: Session) -> str:
    array_value = (
        "CAST(:authority_refs_json AS JSONB)"
        if session.get_bind().dialect.name == "postgresql"
        else ":authority_refs_json"
    )
    object_value = (
        "CAST(:checkpoint_projection_json AS JSONB)"
        if session.get_bind().dialect.name == "postgresql"
        else ":checkpoint_projection_json"
    )
    return _CHECKPOINT_INSERT_SQL.replace(":authority_refs_value", array_value).replace(
        ":checkpoint_projection_value", object_value
    )


def _event_insert_sql(session: Session) -> str:
    value = (
        "CAST(:event_payload_json AS JSONB)"
        if session.get_bind().dialect.name == "postgresql"
        else ":event_payload_json"
    )
    return _EVENT_INSERT_SQL.replace(":event_payload_value", value)


_CHECKPOINT_FIELDS = (
    "tenant_id",
    "checkpoint_id",
    "checkpoint_schema_version",
    "checkpoint_version",
    "previous_checkpoint_id",
    "previous_checkpoint_hash",
    "agent_execution_id",
    "requester_ref",
    "work_intent_id",
    "work_intent_revision",
    "work_intent_hash",
    "agent_context_id",
    "context_generation",
    "context_hash",
    "business_context_hash",
    "capability_id",
    "capability_version",
    "capability_release_ref",
    "capability_registration_hash",
    "coordinator_id",
    "coordinator_version",
    "coordinator_registration_hash",
    "preparation_adapter_source_identity",
    "materializer_source_identity",
    "stage",
    "stage_kind",
    "authority_refs",
    "idempotency_key",
    "correlation_id",
    "causation_id",
    "checkpoint_projection",
    "checkpoint_hash",
    "created_at",
)
_CHECKPOINT_REPLAY_FIELDS = tuple(
    field for field in _CHECKPOINT_FIELDS if field != "created_at"
)
_WAIT_FIELDS = (
    "wait_id",
    "tenant_id",
    "agent_execution_id",
    "executable_step_id",
    "wait_type",
    "external_ref",
    "result_contract_ref",
    "wait_contract_ref",
    "resume_target_kind",
    "state",
    "version",
    "created_at",
    "satisfied_at",
    "matched_event_id",
    "resume_runtime_job_id",
    "updated_at",
    "nsl_execution_id",
    "business_operation_id",
    "approval_request_id",
    "checkpoint_version",
)
_WAIT_REPLAY_FIELDS = (
    "wait_id",
    "tenant_id",
    "agent_execution_id",
    "executable_step_id",
    "wait_type",
    "external_ref",
    "result_contract_ref",
    "wait_contract_ref",
    "resume_target_kind",
    "nsl_execution_id",
    "business_operation_id",
    "approval_request_id",
    "checkpoint_version",
)
_EVENT_FIELDS = (
    "tenant_id",
    "event_id",
    "event_family",
    "event_type",
    "event_semantic_hash",
    "external_ref",
    "result_id",
    "result_contract_ref",
    "event_payload",
    "state",
    "rejection_reason",
    "received_at",
    "processed_at",
    "approval_request_id",
    "approval_work_item_ref",
    "approval_evidence_ref",
    "evidence_integrity",
    "nsl_execution_id",
    "business_operation_id",
)
_EVENT_REPLAY_FIELDS = tuple(
    field
    for field in _EVENT_FIELDS
    if field not in {"state", "rejection_reason", "received_at", "processed_at"}
)
_WAIT_BINDING_FIELDS = (
    "tenant_id",
    "wait_id",
    "checkpoint_id",
    "checkpoint_hash",
    "coordinator_id",
    "coordinator_version",
    "coordinator_registration_hash",
    "expected_event_type",
    "authority_kind",
    "authority_ref",
    "agent_execution_id",
    "work_intent_id",
    "binding_hash",
    "created_at",
)
_WAIT_BINDING_REPLAY_FIELDS = tuple(
    field for field in _WAIT_BINDING_FIELDS if field != "created_at"
)
_EVENT_BINDING_FIELDS = (
    "tenant_id",
    "event_id",
    "wait_id",
    "checkpoint_id",
    "checkpoint_hash",
    "coordinator_id",
    "coordinator_version",
    "coordinator_registration_hash",
    "authority_kind",
    "notification_ref",
    "agent_execution_id",
    "work_intent_id",
    "binding_hash",
    "created_at",
)
_EVENT_BINDING_REPLAY_FIELDS = tuple(
    field for field in _EVENT_BINDING_FIELDS if field != "created_at"
)

_CHECKPOINT_SELECT = (
    "SELECT " + ", ".join(_CHECKPOINT_FIELDS) + " FROM ae_product_prep_checkpoint"
)
_LATEST_CHECKPOINT_SQL = (
    _CHECKPOINT_SELECT
    + " WHERE tenant_id = :tenant_id AND agent_execution_id = :agent_execution_id "
    "AND coordinator_id = :coordinator_id AND coordinator_version = :coordinator_version "
    "ORDER BY checkpoint_version DESC LIMIT 1"
)
_WAIT_BY_ID_SQL = (
    "SELECT " + ", ".join(_WAIT_FIELDS) + " FROM ae_wait_registration "
    "WHERE tenant_id = :tenant_id AND wait_id = :wait_id"
)
_EVENT_BY_ID_SQL = (
    "SELECT " + ", ".join(_EVENT_FIELDS) + " FROM ae_external_event_inbox "
    "WHERE tenant_id = :tenant_id AND event_id = :event_id"
)
_WAIT_BINDING_BY_ID_SQL = (
    "SELECT " + ", ".join(_WAIT_BINDING_FIELDS) + " FROM ae_product_prep_wait_binding "
    "WHERE tenant_id = :tenant_id AND wait_id = :wait_id"
)
_EVENT_BINDING_BY_ID_SQL = (
    "SELECT "
    + ", ".join(_EVENT_BINDING_FIELDS)
    + " FROM ae_product_prep_event_binding "
    "WHERE tenant_id = :tenant_id AND event_id = :event_id"
)

_CHECKPOINT_INSERT_SQL = """
INSERT INTO ae_product_prep_checkpoint (
    tenant_id, checkpoint_id, checkpoint_schema_version, checkpoint_version,
    previous_checkpoint_id, previous_checkpoint_hash, agent_execution_id,
    requester_ref, work_intent_id, work_intent_revision, work_intent_hash,
    agent_context_id, context_generation, context_hash, business_context_hash,
    capability_id, capability_version, capability_release_ref,
    capability_registration_hash, coordinator_id, coordinator_version,
    coordinator_registration_hash, preparation_adapter_source_identity,
    materializer_source_identity, stage, stage_kind, authority_refs,
    idempotency_key, correlation_id, causation_id, checkpoint_projection,
    checkpoint_hash, created_at
) VALUES (
    :tenant_id, :checkpoint_id, :checkpoint_schema_version, :checkpoint_version,
    :previous_checkpoint_id, :previous_checkpoint_hash, :agent_execution_id,
    :requester_ref, :work_intent_id, :work_intent_revision, :work_intent_hash,
    :agent_context_id, :context_generation, :context_hash, :business_context_hash,
    :capability_id, :capability_version, :capability_release_ref,
    :capability_registration_hash, :coordinator_id, :coordinator_version,
    :coordinator_registration_hash, :preparation_adapter_source_identity,
    :materializer_source_identity, :stage, :stage_kind, :authority_refs_value,
    :idempotency_key, :correlation_id, :causation_id, :checkpoint_projection_value,
    :checkpoint_hash, :created_at
) ON CONFLICT DO NOTHING
"""

_WAIT_INSERT_SQL = """
INSERT INTO ae_wait_registration (
    wait_id, tenant_id, agent_execution_id, executable_step_id, wait_type,
    external_ref, result_contract_ref, wait_contract_ref, resume_target_kind,
    state, version, created_at, satisfied_at, matched_event_id,
    resume_runtime_job_id, updated_at, nsl_execution_id, business_operation_id,
    approval_request_id, checkpoint_version
) VALUES (
    :wait_id, :tenant_id, :agent_execution_id, :executable_step_id, :wait_type,
    :external_ref, :result_contract_ref, :wait_contract_ref, :resume_target_kind,
    'PENDING', 1, :created_at, NULL, NULL, NULL, :created_at,
    :nsl_execution_id, :business_operation_id, :approval_request_id,
    :checkpoint_version
) ON CONFLICT DO NOTHING
"""

_WAIT_BINDING_INSERT_SQL = """
INSERT INTO ae_product_prep_wait_binding (
    tenant_id, wait_id, checkpoint_id, checkpoint_hash, coordinator_id,
    coordinator_version, coordinator_registration_hash, expected_event_type,
    authority_kind, authority_ref, agent_execution_id, work_intent_id,
    binding_hash, created_at
) VALUES (
    :tenant_id, :wait_id, :checkpoint_id, :checkpoint_hash, :coordinator_id,
    :coordinator_version, :coordinator_registration_hash, :expected_event_type,
    :authority_kind, :authority_ref, :agent_execution_id, :work_intent_id,
    :binding_hash, :created_at
) ON CONFLICT DO NOTHING
"""

_EVENT_INSERT_SQL = """
INSERT INTO ae_external_event_inbox (
    tenant_id, event_id, event_family, event_type, event_semantic_hash,
    external_ref, result_id, result_contract_ref, event_payload, state,
    rejection_reason, received_at, processed_at, approval_request_id,
    approval_work_item_ref, approval_evidence_ref, evidence_integrity,
    nsl_execution_id, business_operation_id
) VALUES (
    :tenant_id, :event_id, :event_family, :event_type, :event_semantic_hash,
    :external_ref, :result_id, :result_contract_ref, :event_payload_value,
    'RECEIVED', NULL, :received_at, NULL, :approval_request_id,
    :approval_work_item_ref, :approval_evidence_ref, :evidence_integrity,
    :nsl_execution_id, :business_operation_id
) ON CONFLICT DO NOTHING
"""

_EVENT_BINDING_INSERT_SQL = """
INSERT INTO ae_product_prep_event_binding (
    tenant_id, event_id, wait_id, checkpoint_id, checkpoint_hash,
    coordinator_id, coordinator_version, coordinator_registration_hash,
    authority_kind, notification_ref, agent_execution_id, work_intent_id,
    binding_hash, created_at
) VALUES (
    :tenant_id, :event_id, :wait_id, :checkpoint_id, :checkpoint_hash,
    :coordinator_id, :coordinator_version, :coordinator_registration_hash,
    :authority_kind, :notification_ref, :agent_execution_id, :work_intent_id,
    :binding_hash, :created_at
) ON CONFLICT DO NOTHING
"""

_PRODUCT_WAIT_CONTEXT_SQL = """
SELECT
    wait.wait_id, wait.tenant_id, wait.agent_execution_id,
    wait.executable_step_id, wait.wait_type, wait.external_ref,
    wait.result_contract_ref, wait.wait_contract_ref, wait.resume_target_kind,
    wait.state, wait.version, wait.created_at, wait.satisfied_at,
    wait.matched_event_id, wait.resume_runtime_job_id, wait.updated_at,
    wait.nsl_execution_id, wait.business_operation_id,
    wait.approval_request_id, wait.checkpoint_version,
    binding.tenant_id AS binding_tenant_id,
    binding.wait_id AS binding_wait_id,
    binding.checkpoint_id AS binding_checkpoint_id,
    binding.checkpoint_hash AS binding_checkpoint_hash,
    binding.coordinator_id AS binding_coordinator_id,
    binding.coordinator_version AS binding_coordinator_version,
    binding.coordinator_registration_hash AS binding_coordinator_registration_hash,
    binding.expected_event_type AS binding_expected_event_type,
    binding.authority_kind AS binding_authority_kind,
    binding.authority_ref AS binding_authority_ref,
    binding.agent_execution_id AS binding_agent_execution_id,
    binding.work_intent_id AS binding_work_intent_id,
    binding.binding_hash AS binding_binding_hash,
    binding.created_at AS binding_created_at,
    checkpoint.tenant_id AS checkpoint_tenant_id,
    checkpoint.checkpoint_id AS checkpoint_checkpoint_id,
    checkpoint.checkpoint_schema_version AS checkpoint_checkpoint_schema_version,
    checkpoint.checkpoint_version AS checkpoint_checkpoint_version,
    checkpoint.previous_checkpoint_id AS checkpoint_previous_checkpoint_id,
    checkpoint.previous_checkpoint_hash AS checkpoint_previous_checkpoint_hash,
    checkpoint.agent_execution_id AS checkpoint_agent_execution_id,
    checkpoint.requester_ref AS checkpoint_requester_ref,
    checkpoint.work_intent_id AS checkpoint_work_intent_id,
    checkpoint.work_intent_revision AS checkpoint_work_intent_revision,
    checkpoint.work_intent_hash AS checkpoint_work_intent_hash,
    checkpoint.agent_context_id AS checkpoint_agent_context_id,
    checkpoint.context_generation AS checkpoint_context_generation,
    checkpoint.context_hash AS checkpoint_context_hash,
    checkpoint.business_context_hash AS checkpoint_business_context_hash,
    checkpoint.capability_id AS checkpoint_capability_id,
    checkpoint.capability_version AS checkpoint_capability_version,
    checkpoint.capability_release_ref AS checkpoint_capability_release_ref,
    checkpoint.capability_registration_hash AS checkpoint_capability_registration_hash,
    checkpoint.coordinator_id AS checkpoint_coordinator_id,
    checkpoint.coordinator_version AS checkpoint_coordinator_version,
    checkpoint.coordinator_registration_hash AS checkpoint_coordinator_registration_hash,
    checkpoint.preparation_adapter_source_identity AS checkpoint_preparation_adapter_source_identity,
    checkpoint.materializer_source_identity AS checkpoint_materializer_source_identity,
    checkpoint.stage AS checkpoint_stage,
    checkpoint.stage_kind AS checkpoint_stage_kind,
    checkpoint.authority_refs AS checkpoint_authority_refs,
    checkpoint.idempotency_key AS checkpoint_idempotency_key,
    checkpoint.correlation_id AS checkpoint_correlation_id,
    checkpoint.causation_id AS checkpoint_causation_id,
    checkpoint.checkpoint_projection AS checkpoint_checkpoint_projection,
    checkpoint.checkpoint_hash AS checkpoint_checkpoint_hash,
    checkpoint.created_at AS checkpoint_created_at
FROM ae_wait_registration AS wait
JOIN ae_product_prep_wait_binding AS binding
  ON binding.tenant_id = wait.tenant_id AND binding.wait_id = wait.wait_id
JOIN ae_product_prep_checkpoint AS checkpoint
  ON checkpoint.tenant_id = binding.tenant_id
 AND checkpoint.checkpoint_id = binding.checkpoint_id
WHERE wait.tenant_id = :tenant_id AND wait.wait_id = :wait_id
"""

_PRODUCT_WAIT_BY_AUTHORITY_SQL = f"""
{_PRODUCT_WAIT_CONTEXT_SQL.partition("WHERE wait.tenant_id")[0]}
WHERE wait.tenant_id = :tenant_id
  AND wait.state = 'PENDING'
  AND binding.authority_kind = :authority_kind
  AND binding.authority_ref = :authority_ref
ORDER BY wait.created_at, wait.wait_id
LIMIT 2
"""
