from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from .approval_contracts import (
    EOS_APPROVAL_DOMAINS,
    EOS_APPROVAL_LADDER,
    EOS_APPROVAL_RISK_LEVELS,
)

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
        assignment = self._resolve_assignment(
            tenant_id=request["tenant_id"],
            org_unit_id=request["org_unit_ref"]["id"],
            position_type=position_type,
            effective_at=resolved_at,
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
            "position_assignment_version": assignment["position_assignment_version"],
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
                "eos.approver-resolution:" + resolution_hash.removeprefix("sha256:")
            ),
            "resolution_hash": resolution_hash,
            "resolved_at": resolved_at.isoformat().replace("+00:00", "Z"),
            "security_authorization": False,
        }

    def resolve_active_stage(
        self,
        *,
        instance: Mapping[str, Any],
        stage: Mapping[str, Any],
    ) -> dict[str, Any]:
        request = _parse_active_stage(instance, stage)
        resolved_at = _aware_datetime("resolved_at", self._clock())
        assignment = self._resolve_assignment(
            tenant_id=request["tenant_id"],
            org_unit_id=request["org_unit_ref"]["id"],
            position_type=request["position_type"],
            effective_at=resolved_at,
        )
        _require_assignment_matches_stage(assignment, request)
        principal_ref = {
            "type": assignment["principal_ref_type"],
            "id": assignment["principal_id"],
        }
        if principal_ref == request["requester_ref"]:
            raise EosApproverResolutionError(
                "EOS_APPROVER_SELF_ASSIGNMENT",
                "Leadership policy does not permit requester self-approval",
                status_code=409,
            )

        position_ref = {
            "type": "eos.position",
            "id": assignment["position_id"],
        }
        assignment_ref = {
            "type": "eos.position_assignment",
            "id": assignment["position_assignment_id"],
        }
        semantic = {
            "schema_version": "eos_leadership_stage_resolution_binding.v1",
            **request,
            "principal_ref": principal_ref,
            "position_ref": position_ref,
            "position_assignment_ref": assignment_ref,
            "position_assignment_version": assignment["position_assignment_version"],
            "org_unit_version": assignment["org_unit_version"],
        }
        resolution_hash = semantic_sha256_hash_ref(semantic)
        return {
            "schema_version": "eos_leadership_stage_resolution.v1",
            "tenant_id": request["tenant_id"],
            "approval_instance_id": request["approval_instance_id"],
            "approval_stage_id": request["approval_stage_id"],
            "stage_order": request["stage_order"],
            "stage_count": request["stage_count"],
            "leadership_route": request["leadership_route"],
            "policy_ref": request["policy_ref"],
            "requester_ref": request["requester_ref"],
            "principal_ref": principal_ref,
            "position_type": request["position_type"],
            "position_ref": position_ref,
            "position_assignment_ref": assignment_ref,
            "position_assignment_version": assignment["position_assignment_version"],
            "org_unit_ref": request["org_unit_ref"],
            "org_unit_version": assignment["org_unit_version"],
            "project_ref": request["project_ref"],
            "resolution_ref": (
                "eos.leadership-stage-resolution:"
                + resolution_hash.removeprefix("sha256:")
            ),
            "resolution_hash": resolution_hash,
            "resolved_at": resolved_at.isoformat().replace("+00:00", "Z"),
            "security_authorization": False,
        }

    def _resolve_assignment(
        self,
        *,
        tenant_id: str,
        org_unit_id: str,
        position_type: str,
        effective_at: datetime,
    ) -> dict[str, Any]:
        try:
            assignment = self._repository.resolve_active_approver_assignment(
                tenant_id=tenant_id,
                org_unit_id=org_unit_id,
                position_type=position_type,
                effective_at=effective_at,
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
        return assignment


def _parse_active_stage(
    instance: Mapping[str, Any], stage: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(instance, Mapping) or not isinstance(stage, Mapping):
        raise _invalid("approval stage", "must be backed by object projections")
    tenant_id = _scoped_id("tenant_id", instance.get("tenant_id"))
    approval_instance_id = _uuid(
        "approval_instance_id", instance.get("approval_instance_id")
    )
    if (
        instance.get("approval_domain") != "BUSINESS_FORMAL"
        or instance.get("state") != "PENDING"
    ):
        raise _invalid("approval_instance", "must be a pending BUSINESS_FORMAL gate")
    requester_ref = _entity_ref(
        "requester_ref", instance.get("requester_ref"), "oa.user"
    )
    org_unit_ref = _entity_ref(
        "org_unit_ref", instance.get("org_unit_ref"), "eos.org_unit", uuid_id=True
    )
    project_ref = _entity_ref(
        "project_ref", instance.get("project_ref"), "eos.project", uuid_id=True
    )
    policy_ref = _policy_ref(instance.get("policy_ref"))
    binding_hash = _hash_ref("binding_hash", instance.get("binding_hash"))
    route = _leadership_route(instance.get("stages"))
    stage_count = _positive_int("stage_count", instance.get("stage_count"))
    if stage_count != len(route):
        raise _invalid("stage_count", "does not match the persisted leadership route")
    active_order = _positive_int(
        "active_stage_order", instance.get("active_stage_order")
    )
    if active_order > stage_count:
        raise _invalid("active_stage_order", "is outside the leadership route")

    stage_tenant = _scoped_id("stage.tenant_id", stage.get("tenant_id"))
    stage_instance = _uuid(
        "stage.approval_instance_id", stage.get("approval_instance_id")
    )
    stage_order = _positive_int("stage.stage_order", stage.get("stage_order"))
    position_type = _leadership_position(
        "stage.position_type", stage.get("position_type")
    )
    if (
        stage_tenant != tenant_id
        or stage_instance != approval_instance_id
        or stage.get("state") != "ACTIVE"
        or stage_order != active_order
        or route[stage_order - 1] != position_type
    ):
        raise _invalid("approval_stage", "does not match the active leadership stage")
    if (
        stage.get("separation_policy") != "REQUESTER_EXCLUDED"
        or stage.get("quorum_count") != 1
    ):
        raise _invalid("approval_stage", "uses an unsupported initial control profile")

    return {
        "tenant_id": tenant_id,
        "approval_instance_id": approval_instance_id,
        "approval_stage_id": _uuid(
            "stage.approval_stage_id", stage.get("approval_stage_id")
        ),
        "stage_order": stage_order,
        "stage_count": stage_count,
        "leadership_route": route,
        "position_type": position_type,
        "policy_ref": policy_ref,
        "binding_hash": binding_hash,
        "requester_ref": requester_ref,
        "org_unit_ref": org_unit_ref,
        "project_ref": project_ref,
    }


def _leadership_route(value: object) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("stages", "must contain a leadership route")
    if not 1 <= len(value) <= len(EOS_APPROVAL_LADDER):
        raise _invalid("stages", "must contain 1..5 leadership stages")
    route: list[str] = []
    for expected_order, stage in enumerate(value, start=1):
        if not isinstance(stage, Mapping):
            raise _invalid("stages", "must contain stage objects")
        if (
            _positive_int("stages.stage_order", stage.get("stage_order"))
            != expected_order
        ):
            raise _invalid("stages", "must be contiguous and ordered")
        route.append(
            _leadership_position("stages.position_type", stage.get("position_type"))
        )
    positions = [EOS_APPROVAL_LADDER.index(item) for item in route]
    if positions != sorted(set(positions)):
        raise _invalid("stages", "must be a unique ordered leadership subset")
    return route


def _leadership_position(field_name: str, value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized not in EOS_APPROVAL_LADDER:
        raise _invalid(field_name, "is not in the canonical leadership ladder")
    return normalized


def _policy_ref(value: object) -> dict[str, Any]:
    fields = {"approval_policy_id", "version", "policy_hash"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("policy_ref", "must contain the canonical fields")
    return {
        "approval_policy_id": _uuid(
            "policy_ref.approval_policy_id", value.get("approval_policy_id")
        ),
        "version": _positive_int("policy_ref.version", value.get("version")),
        "policy_hash": _hash_ref("policy_ref.policy_hash", value.get("policy_hash")),
    }


def _require_assignment_matches_stage(
    assignment: Mapping[str, Any], request: Mapping[str, Any]
) -> None:
    try:
        principal_type = assignment["principal_ref_type"]
        principal_id = assignment["principal_id"]
        position_type = assignment["position_type"]
        org_unit_id = str(assignment["org_unit_id"])
        _uuid("assignment.position_id", assignment["position_id"])
        _uuid(
            "assignment.position_assignment_id",
            assignment["position_assignment_id"],
        )
        _positive_int(
            "assignment.position_assignment_version",
            assignment["position_assignment_version"],
        )
        _positive_int("assignment.org_unit_version", assignment["org_unit_version"])
    except (KeyError, EosApproverResolutionError) as exc:
        raise EosApproverResolutionError(
            "EOS_APPROVER_RESOLUTION_INVALID_STATE",
            "Organization assignment projection is incomplete",
            status_code=409,
        ) from exc
    if (
        principal_type != "oa.user"
        or not _SCOPED_ID.fullmatch(str(principal_id))
        or position_type != request["position_type"]
        or org_unit_id != request["org_unit_ref"]["id"]
    ):
        raise EosApproverResolutionError(
            "EOS_APPROVER_RESOLUTION_INVALID_STATE",
            "Organization assignment does not match the active leadership stage",
            status_code=409,
        )


def _parse_request(payload: Mapping[str, Any], *, tenant_id: str) -> dict[str, Any]:
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


def _positive_int(field_name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _invalid(field_name, "must be a positive integer")
    return value


def _hash_ref(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", normalized):
        raise _invalid(field_name, "must be a sha256 hash reference")
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
