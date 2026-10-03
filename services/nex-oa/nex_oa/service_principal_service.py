from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nex_oa.service_principal_repository import OaServicePrincipalRepository
from nex_oa.service_principals import (
    OaServicePrincipalError,
    normalize_service_principal_id,
    plan_service_principal_upsert,
)


OA_SERVICE_PRINCIPAL_RESPONSE_SCHEMA_VERSION = "oa_service_principal_response.v1"
_PUBLIC_PRINCIPAL_FIELDS = (
    "principal_schema_version",
    "principal_id",
    "service_id",
    "display_name",
    "status",
    "allowed_audiences",
    "allowed_scopes",
    "revision",
    "created_at",
    "updated_at",
)


@dataclass
class OaServicePrincipalService:
    repository: OaServicePrincipalRepository

    def upsert_principal(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        principal_id = normalize_service_principal_id(payload.get("principal_id"))
        current = self.repository.get_principal(principal_id)
        planned = plan_service_principal_upsert(payload, current=current)
        stored = self.repository.save_principal(planned)
        return _principal_response(stored)

    def set_principal_status(
        self,
        principal_id: str,
        *,
        target_status: object,
        expected_revision: object,
    ) -> dict[str, Any]:
        normalized = normalize_service_principal_id(principal_id)
        current = self.repository.get_principal(normalized)
        if current is None:
            raise _not_found()
        planned = plan_service_principal_upsert(
            {
                **current,
                "status": target_status,
                "expected_revision": expected_revision,
            },
            current=current,
        )
        stored = self.repository.save_principal(planned)
        return _principal_response(stored)

    def get_principal(self, principal_id: str) -> dict[str, Any]:
        record = self.repository.get_principal(
            normalize_service_principal_id(principal_id)
        )
        if record is None:
            raise _not_found()
        return _principal_response(record)

    def list_principals(
        self, *, service_id: str | None = None
    ) -> dict[str, Any]:
        records = self.repository.list_principals(service_id=service_id)
        return {
            "response_schema_version": OA_SERVICE_PRINCIPAL_RESPONSE_SCHEMA_VERSION,
            "items": [_principal_wire(item) for item in records],
            "count": len(records),
        }


def _principal_response(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "response_schema_version": OA_SERVICE_PRINCIPAL_RESPONSE_SCHEMA_VERSION,
        "principal": _principal_wire(record),
    }


def _principal_wire(record: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        field: record[field]
        for field in _PUBLIC_PRINCIPAL_FIELDS
        if field in record
    }
    for field in ("allowed_audiences", "allowed_scopes"):
        if field in result:
            result[field] = list(result[field])
    return result


def _not_found() -> OaServicePrincipalError:
    return OaServicePrincipalError(
        status_code=404,
        error_code="oa.service_principal_not_found",
        detail="service principal was not found.",
    )
