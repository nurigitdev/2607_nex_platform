from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

EOS_APPROVAL_DOMAINS = frozenset(
    {"AGENT_FORMAL", "NSL_WRITE", "BUSINESS_FORMAL"}
)
EOS_APPROVAL_RISK_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})
EOS_DEFAULT_APPROVER_POLICY = "eos.approver.default.v1"
EOS_DEFAULT_RISK_POSITION_TYPES = {
    "LOW": "PART_LEAD",
    "MEDIUM": "TEAM_LEAD",
    "HIGH": "GROUP_LEAD",
    "CRITICAL": "CEO",
}

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class ApproverAssignmentRepository(Protocol):
    def resolve_active_approver_assignment(
        self,
        *,
        tenant_id: str,
        org_unit_id: str,
        position_type: str,
        effective_at: datetime,
    ) -> dict[str, Any] | None: ...


class EosApproverResolutionError(RuntimeError):
    def __init__(self, error_code: str, detail: str, *, status_code: int) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = status_code == 503
        super().__init__(detail)


class EosApproverResolutionService:
    def __init__(
        self,
        repository: ApproverAssignmentRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def resolve(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        request = _parse_request(payload, tenant_id=tenant_id)
        resolved_at = _aware_datetime("resolved_at", self._clock())
        position_type = EOS_DEFAULT_RISK_POSITION_TYPES[request["risk_level"]]
        try:
            assignment = self._repository.resolve_active_approver_assignment(
                tenant_id=request["tenant_id"],
                org_unit_id=request["org_unit_ref"]["id"],
                position_type=position_type,
                effective_at=resolved_at,
            )
        except EosApproverResolutionError:
            raise
        except Exception as exc:
            if getattr(exc, "status_code", None) == 503:
                raise EosApproverResolutionError(
                    "EOS_APPROVER_RESOLUTION_UNAVAILABLE",
                    "Organization assignment lookup is unavailable",
                    status_code=503,
                ) from exc
            raise
        if assignment is None:
            raise EosApproverResolutionError(
                "EOS_APPROVER_NOT_FOUND",
                "No effective approver assignment matches the requested policy",
                status_code=404,
            )

        principal_ref = {
            "type": assignment["principal_ref_type"],
            "id": assignment["principal_id"],
        }
        if principal_ref == request["requester_ref"]:
            raise EosApproverResolutionError(
                "EOS_APPROVER_SELF_ASSIGNMENT",
                "Default approver policy does not permit requester self-approval",
                status_code=409,
            )

        semantic = {
            **request,
            "position_type": assignment["position_type"],
            "position_ref": {
                "type": "eos.position",
                "id": assignment["position_id"],
            },
            "position_assignment_ref": {
                "type": "eos.position_assignment",
                "id": assignment["position_assignment_id"],
            },
            "position_assignment_version": assignment[
                "position_assignment_version"
            ],
            "org_unit_version": assignment["org_unit_version"],
            "principal_ref": principal_ref,
        }
        resolution_hash = semantic_sha256_hash_ref(semantic)
        return {
            "schema_version": "eos_approver_resolution.v1",
            "tenant_id": request["tenant_id"],
            "approval_domain": request["approval_domain"],
            "risk_level": request["risk_level"],
            "policy_ref": request["policy_ref"],
            "requester_ref": request["requester_ref"],
            "principal_ref": principal_ref,
            "position_type": assignment["position_type"],
            "position_ref": semantic["position_ref"],
            "position_assignment_ref": semantic["position_assignment_ref"],
            "org_unit_ref": request["org_unit_ref"],
            "project_ref": request["project_ref"],
            "resolution_ref": (
                "eos.approver-resolution:"
                + resolution_hash.removeprefix("sha256:")
            ),
            "resolution_hash": resolution_hash,
            "resolved_at": resolved_at.isoformat().replace("+00:00", "Z"),
            "security_authorization": False,
        }


def _parse_request(
    payload: Mapping[str, Any], *, tenant_id: str
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise _invalid("payload", "must be an object")
    allowed = {
        "schema_version",
        "requester_ref",
        "approval_domain",
        "risk_level",
        "org_unit_ref",
        "project_ref",
        "policy_ref",
    }
    if set(payload) != allowed:
        raise _invalid("payload", "must contain exactly the canonical fields")
    if payload.get("schema_version") != "eos_approver_resolution_request.v1":
        raise _invalid("schema_version", "is unsupported")
    policy_ref = _scoped_id("policy_ref", payload.get("policy_ref"))
    if policy_ref != EOS_DEFAULT_APPROVER_POLICY:
        raise _invalid("policy_ref", "is not an admitted policy")
    return {
        "schema_version": "eos_approver_resolution_request.v1",
        "tenant_id": _scoped_id("tenant_id", tenant_id),
        "requester_ref": _entity_ref(
            "requester_ref", payload.get("requester_ref"), "oa.user"
        ),
        "approval_domain": _choice(
            "approval_domain", payload.get("approval_domain"), EOS_APPROVAL_DOMAINS
        ),
        "risk_level": _choice(
            "risk_level", payload.get("risk_level"), EOS_APPROVAL_RISK_LEVELS
        ),
        "org_unit_ref": _entity_ref(
            "org_unit_ref", payload.get("org_unit_ref"), "eos.org_unit", uuid_id=True
        ),
        "project_ref": _optional_entity_ref(
            "project_ref", payload.get("project_ref"), "eos.project", uuid_id=True
        ),
        "policy_ref": policy_ref,
    }


def _entity_ref(
    field_name: str,
    value: object,
    expected_type: str,
    *,
    uuid_id: bool = False,
) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"type", "id"}:
        raise _invalid(field_name, "must contain exactly type and id")
    if value.get("type") != expected_type:
        raise _invalid(f"{field_name}.type", f"must be {expected_type}")
    identifier = (
        _uuid(f"{field_name}.id", value.get("id"))
        if uuid_id
        else _scoped_id(f"{field_name}.id", value.get("id"))
    )
    return {"type": expected_type, "id": identifier}


def _optional_entity_ref(
    field_name: str,
    value: object,
    expected_type: str,
    *,
    uuid_id: bool = False,
) -> dict[str, str] | None:
    if value is None:
        return None
    return _entity_ref(field_name, value, expected_type, uuid_id=uuid_id)


def _choice(field_name: str, value: object, allowed: frozenset[str]) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized not in allowed:
        raise _invalid(field_name, f"must be one of {sorted(allowed)}")
    return normalized


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _SCOPED_ID.fullmatch(normalized):
        raise _invalid(field_name, "has invalid stable-reference syntax")
    return normalized


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field_name, "must be a UUID") from exc


def _aware_datetime(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(field_name, "must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _invalid(field_name: str, detail: str) -> EosApproverResolutionError:
    return EosApproverResolutionError(
        "EOS_APPROVER_RESOLUTION_INVALID",
        f"{field_name} {detail}",
        status_code=422,
    )
