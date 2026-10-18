from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.executable_plans import (
    ExecutablePlanError,
    validate_compiled_delegation,
)


@dataclass(frozen=True)
class DelegatedWorkError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class WcWorkItemClient(Protocol):
    def create_work_item(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


class SqlAlchemyDelegationRuntimeRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def load(
        self,
        *,
        tenant_id: str,
        agent_execution_id: str,
        executable_plan_id: str,
        executable_step_id: str,
    ) -> dict[str, Any]:
        params = {
            "tenant_id": _required("tenant_id", tenant_id, 128),
            "execution_id": _uuid("agent_execution_id", agent_execution_id),
            "plan_id": _uuid("executable_plan_id", executable_plan_id),
            "step_id": _uuid("executable_step_id", executable_step_id),
        }
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            "SELECT execution.agent_id, execution.agent_type, "
                            "execution.principal_id, execution.requester_ref, "
                            "execution.correlation_id, execution.causation_id, "
                            "execution.state, execution.phase, plan.plan_json "
                            "FROM ae_agent_execution AS execution "
                            "JOIN ae_executable_plan AS plan "
                            "ON plan.tenant_id = execution.tenant_id "
                            "AND plan.agent_execution_id = execution.agent_execution_id "
                            "WHERE execution.tenant_id = :tenant_id "
                            "AND execution.agent_execution_id = :execution_id "
                            "AND plan.executable_plan_id = :plan_id"
                        ),
                        params,
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise DelegatedWorkError(
                        "ae.delegate_runtime_not_found",
                        "Delegated work runtime lineage was not found.",
                    )
                plan = _json_object(row["plan_json"], "plan_json")
                if plan.get("execution_id") != params["execution_id"]:
                    raise _invalid("Delegated work plan execution lineage is invalid.")
                step = next(
                    (
                        item
                        for item in plan.get("steps", ())
                        if isinstance(item, Mapping)
                        and item.get("executable_step_id") == params["step_id"]
                    ),
                    None,
                )
                if step is None or step.get("executor_kind") != "WC_DELEGATE_WORK":
                    raise _invalid("Delegated work compiled step lineage is invalid.")
                if row["state"] != "RUNNING" or row["phase"] != "STEP_EXECUTION":
                    raise _invalid("Delegated work requires active execution authority.")
                requester_ref = row["requester_ref"] or row["principal_id"]
                return {
                    "tenant_id": params["tenant_id"],
                    "agent_execution_id": params["execution_id"],
                    "executable_plan_id": params["plan_id"],
                    "executable_step_id": params["step_id"],
                    "agent_id": _required("agent_id", str(row["agent_id"]), 128),
                    "agent_type": _required(
                        "agent_type", str(row["agent_type"]), 16
                    ),
                    "requester_ref": _required(
                        "requester_ref", requester_ref, 160
                    ),
                    "correlation_id": _required(
                        "correlation_id", row["correlation_id"], 128
                    ),
                    "causation_id": (
                        None
                        if row["causation_id"] is None
                        else _required("causation_id", row["causation_id"], 128)
                    ),
                    "delegation": validate_compiled_delegation(
                        step.get("delegation")
                    ),
                }
        except DelegatedWorkError:
            raise
        except ExecutablePlanError as exc:
            raise _invalid(exc.detail) from exc
        except SQLAlchemyError as exc:
            raise DelegatedWorkError(
                "ae.delegate_runtime_store_unavailable",
                "Delegated work runtime persistence is unavailable.",
                True,
            ) from exc


class SqlAlchemyWaitRegistrationRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def register(
        self,
        *,
        wait_id: str,
        tenant_id: str,
        agent_execution_id: str,
        executable_step_id: str,
        external_ref: str,
        result_contract_ref: str,
        created_at: str,
    ) -> dict[str, Any]:
        record = {
            "wait_id": _uuid("wait_id", wait_id),
            "tenant_id": _required("tenant_id", tenant_id, 128),
            "agent_execution_id": _uuid("agent_execution_id", agent_execution_id),
            "executable_step_id": _uuid("executable_step_id", executable_step_id),
            "wait_type": "WORK_RESULT",
            "external_ref": _uuid("external_ref", external_ref),
            "result_contract_ref": _required(
                "result_contract_ref", result_contract_ref, 256
            ),
            "state": "PENDING",
            "version": 1,
            "created_at": _required("created_at", created_at, 64),
            "satisfied_at": None,
        }
        try:
            with self._session_factory() as session:
                session.execute(text(_WAIT_INSERT_SQL), record)
                saved = _load_wait(
                    session,
                    tenant_id=record["tenant_id"],
                    agent_execution_id=record["agent_execution_id"],
                    executable_step_id=record["executable_step_id"],
                )
                if saved is None:
                    raise DelegatedWorkError(
                        "ae.wait_registration_write_conflict",
                        "WaitRegistration could not be reloaded.",
                        True,
                    )
                if not _same_wait_registration(saved, record):
                    raise DelegatedWorkError(
                        "ae.wait_registration_immutable_conflict",
                        "Delegated step already has a different WaitRegistration.",
                    )
                session.commit()
                return saved
        except DelegatedWorkError:
            raise
        except SQLAlchemyError as exc:
            raise DelegatedWorkError(
                "ae.wait_registration_store_unavailable",
                "WaitRegistration persistence is unavailable.",
                True,
            ) from exc

    def get(
        self, *, tenant_id: str, agent_execution_id: str, executable_step_id: str
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_wait(
                    session,
                    tenant_id=_required("tenant_id", tenant_id, 128),
                    agent_execution_id=_uuid(
                        "agent_execution_id", agent_execution_id
                    ),
                    executable_step_id=_uuid(
                        "executable_step_id", executable_step_id
                    ),
                )
        except SQLAlchemyError as exc:
            raise DelegatedWorkError(
                "ae.wait_registration_store_unavailable",
                "WaitRegistration persistence is unavailable.",
                True,
            ) from exc


class HttpWcWorkItemClient:
    def __init__(
        self, *, base_url: str, service_token: str, timeout_seconds: float = 15.0
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/api/v1/work-items"
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def create_work_item(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self._service_token.strip():
            raise DelegatedWorkError(
                "ae.wc_service_token_missing",
                "WC service token is not configured.",
            )
        request = Request(
            self._url,
            method="POST",
            data=json.dumps(dict(payload), sort_keys=True).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise DelegatedWorkError(
                "ae.wc_work_item_http_failed",
                f"WC WorkItem creation failed with HTTP {exc.code}.",
                exc.code >= 500,
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise DelegatedWorkError(
                "ae.wc_work_item_unavailable",
                "WC WorkItem creation is unavailable.",
                True,
            ) from exc
        if not isinstance(result, Mapping) or not isinstance(
            result.get("work_item"), Mapping
        ):
            raise _invalid("WC WorkItem response is invalid.")
        return result


def delegation_dispatch(
    runtime: Mapping[str, Any], *, created_at: str
) -> dict[str, Any]:
    delegation = validate_compiled_delegation(runtime.get("delegation"))
    tenant_id = _required("tenant_id", runtime.get("tenant_id"), 128)
    execution_id = _uuid(
        "agent_execution_id", runtime.get("agent_execution_id")
    )
    plan_id = _uuid("executable_plan_id", runtime.get("executable_plan_id"))
    step_id = _uuid("executable_step_id", runtime.get("executable_step_id"))
    work_item_id = deterministic_work_item_id(
        tenant_id=tenant_id,
        delegation_id=delegation["delegation_id"],
        delegation_revision=delegation["delegation_revision"],
    )
    spec = {
        **delegation,
        "tenant_id": tenant_id,
        "parent_agent_execution_id": execution_id,
        "parent_executable_plan_id": plan_id,
        "parent_executable_step_id": step_id,
        "correlation_id": _required(
            "correlation_id", runtime.get("correlation_id"), 128
        ),
        "causation_id": step_id,
    }
    wait_id = deterministic_wait_id(
        tenant_id=tenant_id,
        agent_execution_id=execution_id,
        executable_step_id=step_id,
    )
    return {
        "wait": {
            "wait_id": wait_id,
            "tenant_id": tenant_id,
            "agent_execution_id": execution_id,
            "executable_step_id": step_id,
            "external_ref": work_item_id,
            "result_contract_ref": delegation["result_contract_ref"],
            "created_at": _required("created_at", created_at, 64),
        },
        "work_item_request": {
            "work_item_id": work_item_id,
            "delegation_spec": spec,
            "requester": {
                "entity_type": "AGENT",
                "entity_id": _required("agent_id", runtime.get("agent_id"), 128),
            },
            "accountable_owner": {
                "entity_type": "USER",
                "entity_id": _required(
                    "requester_ref", runtime.get("requester_ref"), 160
                ),
            },
        },
    }


def deterministic_work_item_id(
    *, tenant_id: str, delegation_id: str, delegation_revision: int
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/wc/work-items/"
            f"{tenant_id}/{delegation_id}/{delegation_revision}",
        )
    )


def deterministic_wait_id(
    *, tenant_id: str, agent_execution_id: str, executable_step_id: str
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/ae/waits/"
            f"{tenant_id}/{agent_execution_id}/{executable_step_id}/WORK_RESULT",
        )
    )


def _load_wait(
    session: Session,
    *,
    tenant_id: str,
    agent_execution_id: str,
    executable_step_id: str,
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT wait_id, tenant_id, agent_execution_id, "
                "executable_step_id, wait_type, external_ref, "
                "result_contract_ref, state, version, created_at, satisfied_at "
                "FROM ae_wait_registration WHERE tenant_id = :tenant_id "
                "AND agent_execution_id = :agent_execution_id "
                "AND executable_step_id = :executable_step_id "
                "AND wait_type = 'WORK_RESULT'"
            ),
            {
                "tenant_id": tenant_id,
                "agent_execution_id": agent_execution_id,
                "executable_step_id": executable_step_id,
            },
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return {
        "wait_id": str(row["wait_id"]),
        "tenant_id": row["tenant_id"],
        "agent_execution_id": str(row["agent_execution_id"]),
        "executable_step_id": str(row["executable_step_id"]),
        "wait_type": row["wait_type"],
        "external_ref": str(row["external_ref"]),
        "result_contract_ref": row["result_contract_ref"],
        "state": row["state"],
        "version": int(row["version"]),
        "created_at": _timestamp(row["created_at"]),
        "satisfied_at": (
            None if row["satisfied_at"] is None else _timestamp(row["satisfied_at"])
        ),
    }


def _json_object(value: object, field: str) -> dict[str, Any]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, Mapping):
        raise _invalid(f"{field} must be an object.")
    return dict(parsed)


def _timestamp(value: object) -> str:
    if isinstance(value, datetime):
        normalized = value.astimezone(UTC) if value.tzinfo is not None else value
        return normalized.isoformat().replace("+00:00", "Z")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _same_wait_registration(
    saved: Mapping[str, Any], proposed: Mapping[str, Any]
) -> bool:
    immutable_fields = (
        "wait_id",
        "tenant_id",
        "agent_execution_id",
        "executable_step_id",
        "wait_type",
        "external_ref",
        "result_contract_ref",
        "state",
        "version",
        "satisfied_at",
    )
    return all(saved.get(field) == proposed.get(field) for field in immutable_fields)


def _uuid(field: str, value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a UUID.") from exc


def _required(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} must be a bounded non-empty string.")
    return value.strip()


def _invalid(detail: str) -> DelegatedWorkError:
    return DelegatedWorkError("ae.delegate_work_invalid", detail)


_WAIT_INSERT_SQL = """
    INSERT INTO ae_wait_registration (
        wait_id, tenant_id, agent_execution_id, executable_step_id,
        wait_type, external_ref, result_contract_ref, state, version,
        created_at, satisfied_at
    ) VALUES (
        :wait_id, :tenant_id, :agent_execution_id, :executable_step_id,
        :wait_type, :external_ref, :result_contract_ref, :state, :version,
        :created_at, :satisfied_at
    ) ON CONFLICT (tenant_id, agent_execution_id, executable_step_id, wait_type)
    DO NOTHING
"""
