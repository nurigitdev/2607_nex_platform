from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from nex_runtime import build_unit_of_work
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .project_entitlement_state import (
    EosProjectEntitlementStateError,
    append_authoritative_project_entitlement_snapshot,
    authoritative_project_entitlement_projection,
    projection_semantics,
)


class EosProjectEntitlementReconciliationError(RuntimeError):
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


class OaProjectEntitlementProjectionSource(Protocol):
    def resolve(
        self, *, tenant_id: str, project_code: str, correlation_id: str
    ) -> Mapping[str, Any]: ...


class HttpOaProjectEntitlementProjectionSource:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float = 10.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        if not base_url.strip() or not service_token.strip():
            raise ValueError("OA Project entitlement projection transport is incomplete")
        if not 0 < timeout_seconds <= 120:
            raise ValueError("OA Project entitlement projection timeout is invalid")
        self._url = (
            f"{base_url.rstrip('/')}"
            "/internal/v1/auth/project-entitlement-projections:resolve"
        )
        self._service_token = service_token
        self._timeout_seconds = float(timeout_seconds)
        self._opener = opener

    def resolve(
        self, *, tenant_id: str, project_code: str, correlation_id: str
    ) -> Mapping[str, Any]:
        request_payload = {
            "tenant_id": tenant_id,
            "project_code": project_code,
            "correlation_id": correlation_id,
        }
        request = Request(
            self._url,
            method="POST",
            data=json.dumps(request_payload, sort_keys=True).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                value = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise _unavailable(
                f"OA Project entitlement projection failed with HTTP {exc.code}"
            ) from exc
        except (
            URLError,
            TimeoutError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise _unavailable("OA Project entitlement projection is unavailable") from exc
        return _admit_projection(value, expected=request_payload)


class EosProjectEntitlementReconciliationService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        projection_source: OaProjectEntitlementProjectionSource,
    ) -> None:
        self._session_factory = session_factory
        self._projection_source = projection_source

    def reconcile(
        self,
        *,
        tenant_id: str,
        project_id: str,
        correlation_id: str,
        repair: bool = False,
    ) -> dict[str, Any]:
        source = self._source_projection(tenant_id=tenant_id, project_id=project_id)
        if source.get("origin") != "APPROVED_APPLICATION":
            raise EosProjectEntitlementReconciliationError(
                "EOS_PROJECT_ENTITLEMENT_IMPORT_REQUIRED",
                "Legacy Project entitlement requires an explicit audited import",
                status_code=409,
            )
        observed = self._projection_source.resolve(
            tenant_id=tenant_id,
            project_code=str(source["project_code"]),
            correlation_id=correlation_id,
        )
        reasons = _drift_reasons(source, observed)
        if not reasons and source["authorization_sync_state"] == "IN_SYNC":
            return _result("IN_SYNC", source, observed, (), repair_scheduled=False)
        if source["authorization_sync_state"] != "IN_SYNC":
            reasons.append(
                f"EOS_SYNC_STATE_{source['authorization_sync_state']}"
            )
        if not repair:
            return _result("DRIFT", source, observed, reasons, repair_scheduled=False)
        if not _requires_snapshot_repair(reasons):
            return _result(
                "ACK_PENDING", source, observed, reasons, repair_scheduled=False
            )
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                repair_snapshot = append_authoritative_project_entitlement_snapshot(
                    transaction.db,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    correlation_id=correlation_id,
                    causation_id=f"reconcile:{correlation_id}",
                    occurred_at=datetime.now(UTC),
                )
        except EosProjectEntitlementStateError as exc:
            raise EosProjectEntitlementReconciliationError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable("EOS Project entitlement repair is unavailable") from exc
        result = _result(
            "REPAIR_PENDING", source, observed, reasons, repair_scheduled=True
        )
        result["repair_snapshot"] = repair_snapshot
        return result

    def _source_projection(
        self, *, tenant_id: str, project_id: str
    ) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                source = authoritative_project_entitlement_projection(
                    session, tenant_id=tenant_id, project_id=project_id
                )
        except SQLAlchemyError as exc:
            raise _unavailable("EOS Project entitlement source is unavailable") from exc
        if source is None:
            raise EosProjectEntitlementReconciliationError(
                "EOS_PROJECT_NOT_FOUND",
                "Project was not found in tenant scope",
                status_code=404,
            )
        return source


def _admit_projection(
    value: object, *, expected: Mapping[str, str]
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _malformed()
    semantics = {
        key: item
        for key, item in value.items()
        if key not in {"schema_version", "projection_hash"}
    }
    if (
        value.get("schema_version") != "oa_project_entitlement_projection.v1"
        or value.get("tenant_id") != expected["tenant_id"]
        or value.get("project_code") != expected["project_code"]
        or value.get("correlation_id") != expected["correlation_id"]
        or value.get("projection_hash") != semantic_sha256_hash_ref(semantics)
        or not isinstance(value.get("members"), list)
    ):
        raise _malformed()
    return value


def _drift_reasons(
    source: Mapping[str, Any], observed: Mapping[str, Any]
) -> list[str]:
    if not observed.get("found"):
        return ["OA_PROJECTION_MISSING"]
    reasons: list[str] = []
    if observed.get("source_project_id") != source.get("project_id"):
        reasons.append("PROJECT_ID_MISMATCH")
    if observed.get("project_code") != source.get("project_code"):
        reasons.append("PROJECT_CODE_MISMATCH")
    if observed.get("project_status") != source.get("project_status"):
        reasons.append("PROJECT_STATUS_MISMATCH")
    if observed.get("source_version") != source.get("source_version"):
        reasons.append("SOURCE_VERSION_MISMATCH")
    observed_projection = {
        "project_id": observed.get("source_project_id"),
        "project_code": observed.get("project_code"),
        "project_status": observed.get("project_status"),
        "source_version": observed.get("source_version"),
        "members": observed.get("members"),
    }
    if (
        projection_semantics(source) != projection_semantics(observed_projection)
        and "SOURCE_VERSION_MISMATCH" not in reasons
    ):
        reasons.append("MEMBERSHIP_MISMATCH")
    return reasons


def _requires_snapshot_repair(reasons: list[str]) -> bool:
    return any(not reason.startswith("EOS_SYNC_STATE_") for reason in reasons)


def _result(
    state: str,
    source: Mapping[str, Any],
    observed: Mapping[str, Any],
    reasons: list[str] | tuple[str, ...],
    *,
    repair_scheduled: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "eos.project_entitlement_reconciliation.v1",
        "state": state,
        "tenant_id": source["tenant_id"],
        "project_id": source["project_id"],
        "project_code": source["project_code"],
        "source_version": source["source_version"],
        "observed_source_version": observed.get("source_version", 0),
        "drift_reasons": list(dict.fromkeys(reasons)),
        "repair_scheduled": repair_scheduled,
    }


def _unavailable(detail: str) -> EosProjectEntitlementReconciliationError:
    return EosProjectEntitlementReconciliationError(
        "EOS_PROJECT_ENTITLEMENT_RECONCILIATION_UNAVAILABLE",
        detail,
        status_code=503,
        retryable=True,
    )


def _malformed() -> EosProjectEntitlementReconciliationError:
    return EosProjectEntitlementReconciliationError(
        "EOS_PROJECT_ENTITLEMENT_PROJECTION_MALFORMED",
        "OA Project entitlement projection is malformed or tampered",
        status_code=502,
    )
