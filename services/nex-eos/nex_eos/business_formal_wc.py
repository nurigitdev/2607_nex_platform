from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx
from nex_runtime import SERVICE_SPECS
from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref

from .approval_instances import SqlAlchemyEosApprovalInstanceRepository

DEFAULT_WC_BASE_URL = f"http://127.0.0.1:{SERVICE_SPECS['nex-wc'].default_port}"


class EosBusinessFormalWcError(RuntimeError):
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


class WcApprovalWorkItemClient(Protocol):
    def create_or_get(self, work_item: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class HttpWcApprovalWorkItemClient:
    base_url: str = DEFAULT_WC_BASE_URL
    service_token: str = ""
    timeout_seconds: float = 15.0

    def create_or_get(self, work_item: Mapping[str, Any]) -> Mapping[str, Any]:
        token = self.service_token.strip()
        if not token:
            raise _unavailable("WC service trust is not configured")
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/api/v1/approval-work-items",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-NeX-Tenant-Id": str(work_item.get("tenant_id", "")),
                    "X-Service-ID": "nex-eos",
                },
                json=dict(work_item),
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise _unavailable("WC approval publication is unavailable") from exc
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EosBusinessFormalWcError(
                "EOS_BUSINESS_FORMAL_WC_RESPONSE_INVALID",
                "WC approval publication response is invalid",
                status_code=502,
                retryable=response.status_code >= 500,
            ) from exc
        if response.status_code >= 400:
            retryable = response.status_code >= 500
            if isinstance(payload, Mapping) and isinstance(
                payload.get("retryable"), bool
            ):
                retryable = payload["retryable"]
            raise EosBusinessFormalWcError(
                "EOS_BUSINESS_FORMAL_WC_REJECTED",
                f"WC approval publication failed with HTTP {response.status_code}",
                status_code=502 if retryable else 409,
                retryable=retryable,
            )
        return _wc_result(payload)


class EosBusinessFormalWcAdapter:
    def __init__(
        self,
        *,
        approval_instances: SqlAlchemyEosApprovalInstanceRepository,
        wc_client: WcApprovalWorkItemClient,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._approval_instances = approval_instances
        self._wc_client = wc_client
        self._clock = clock or (lambda: datetime.now(UTC))

    def project_active_stage(
        self, *, tenant_id: str, approval_instance_id: str
    ) -> dict[str, Any]:
        instance = self._approval_instances.get_instance(
            tenant_id=tenant_id,
            approval_instance_id=approval_instance_id,
        )
        if instance is None:
            raise EosBusinessFormalWcError(
                "EOS_APPROVAL_INSTANCE_NOT_FOUND",
                "Approval instance does not exist in tenant scope",
                status_code=404,
            )
        _require_projectable_instance(instance)
        stage = self._approval_instances.get_active_stage(
            tenant_id=tenant_id,
            approval_instance_id=approval_instance_id,
        )
        if stage is None:
            raise EosBusinessFormalWcError(
                "EOS_APPROVAL_ACTIVE_STAGE_MISSING",
                "Approval instance has no active stage",
                status_code=409,
            )
        _require_active_stage(instance, stage)
        created_at = _aware_time("created_at", self._clock())
        expires_at = _optional_time(instance.get("expires_at"))
        if expires_at is not None and expires_at <= created_at:
            raise EosBusinessFormalWcError(
                "EOS_APPROVAL_INSTANCE_EXPIRED",
                "Approval instance expired before WC publication",
                status_code=409,
            )
        work_item = _work_item(
            instance=instance,
            stage=stage,
            created_at=created_at,
            expires_at=expires_at,
        )
        try:
            published = _wc_result(self._wc_client.create_or_get(work_item))
        except EosBusinessFormalWcError:
            raise
        except Exception as exc:
            raise _unavailable("WC approval publication is unavailable") from exc
        _require_wc_lineage(published["work_item"], work_item)
        return {
            "schema_version": "eos_business_formal_wc_projection.v1",
            "tenant_id": instance["tenant_id"],
            "approval_instance_id": instance["approval_instance_id"],
            "approval_stage_id": stage["approval_stage_id"],
            "work_item": published["work_item"],
            "created": published["created"],
        }


def deterministic_business_formal_work_item_id(
    *, tenant_id: str, approval_stage_id: str
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/wc/business-formal/"
            f"{tenant_id}/{approval_stage_id}",
        )
    )


def _work_item(
    *,
    instance: Mapping[str, Any],
    stage: Mapping[str, Any],
    created_at: datetime,
    expires_at: datetime | None,
) -> dict[str, Any]:
    stage_ref = f"eos.approval-stage:{stage['approval_stage_id']}"
    target_role = str(stage["position_type"])
    target_org = str(instance["org_unit_ref"]["id"])
    target_project = str(instance["project_ref"]["id"])
    semantic = {
        "schema_version": "eos_business_formal_wc_binding.v1",
        "tenant_id": instance["tenant_id"],
        "approval_instance_id": instance["approval_instance_id"],
        "approval_stage_id": stage["approval_stage_id"],
        "stage_order": stage["stage_order"],
        "position_type": target_role,
        "quorum_count": stage["quorum_count"],
        "separation_policy": stage["separation_policy"],
        "policy_ref": instance["policy_ref"],
        "business_operation_id": instance["business_operation_id"],
        "operation": instance["operation"],
        "protected_operation_ref": instance["protected_operation_ref"],
        "payload_hash": instance["payload_hash"],
        "write_intent_hash": instance["write_intent_hash"],
        "requester_ref": instance["requester_ref"],
        "org_unit_ref": instance["org_unit_ref"],
        "project_ref": instance["project_ref"],
        "target_role_ref": target_role,
        "target_org_scope_ref": target_org,
        "target_project_scope_ref": target_project,
    }
    summary = canonical_json(
        {
            "operation": instance["operation"],
            "stage_order": stage["stage_order"],
            "stage_count": instance["stage_count"],
            "position_type": target_role,
            "org_unit_id": target_org,
            "project_id": target_project,
        }
    )
    return {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": instance["tenant_id"],
        "approval_work_item_id": deterministic_business_formal_work_item_id(
            tenant_id=instance["tenant_id"],
            approval_stage_id=stage["approval_stage_id"],
        ),
        "approval_domain": "BUSINESS_FORMAL",
        "source_ref": stage_ref,
        "semantic_hash": semantic_sha256_hash_ref(semantic),
        "title": f"Approve business operation: {instance['operation']}",
        "display_safe_summary": summary,
        "approval_provider_type": "EOS",
        "approval_target_ref": stage_ref,
        "target_approver_ref": None,
        "target_role_ref": target_role,
        "target_org_scope_ref": target_org,
        "target_project_scope_ref": target_project,
        "agent_execution_id": None,
        "executable_step_id": None,
        "nsl_execution_id": None,
        "business_operation_id": instance["business_operation_id"],
        "approval_request_id": None,
        "protected_request_ref": instance["protected_operation_ref"],
        "resume_target_ref": (
            f"eos.approval-instance:{instance['approval_instance_id']}:"
            f"stage:{stage['stage_order']}"
        ),
        "state": "PENDING",
        "created_at": _timestamp(created_at),
        "expires_at": _timestamp(expires_at) if expires_at is not None else None,
        "version": 1,
    }


def _require_projectable_instance(instance: Mapping[str, Any]) -> None:
    if (
        instance.get("approval_domain") != "BUSINESS_FORMAL"
        or instance.get("state") != "PENDING"
    ):
        raise EosBusinessFormalWcError(
            "EOS_APPROVAL_INSTANCE_NOT_PROJECTABLE",
            "Approval instance is not a pending BUSINESS_FORMAL gate",
            status_code=409,
        )


def _require_active_stage(
    instance: Mapping[str, Any], stage: Mapping[str, Any]
) -> None:
    if (
        stage.get("tenant_id") != instance.get("tenant_id")
        or stage.get("approval_instance_id") != instance.get("approval_instance_id")
        or stage.get("state") != "ACTIVE"
        or stage.get("stage_order") != instance.get("active_stage_order")
    ):
        raise EosBusinessFormalWcError(
            "EOS_APPROVAL_ACTIVE_STAGE_MISMATCH",
            "Active stage lineage does not match the approval instance",
            status_code=409,
        )


def _require_wc_lineage(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    fields = (
        "tenant_id",
        "approval_work_item_id",
        "approval_domain",
        "source_ref",
        "semantic_hash",
        "approval_provider_type",
        "approval_target_ref",
        "target_role_ref",
        "target_org_scope_ref",
        "target_project_scope_ref",
        "business_operation_id",
        "protected_request_ref",
        "resume_target_ref",
    )
    if any(actual.get(field) != expected.get(field) for field in fields):
        raise EosBusinessFormalWcError(
            "EOS_BUSINESS_FORMAL_WC_RESPONSE_INVALID",
            "WC approval publication response lineage is invalid",
            status_code=502,
        )


def _wc_result(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EosBusinessFormalWcError(
            "EOS_BUSINESS_FORMAL_WC_RESPONSE_INVALID",
            "WC approval publication response is invalid",
            status_code=502,
        )
    work_item = value.get("work_item")
    created = value.get("created")
    if not isinstance(work_item, Mapping) or not isinstance(created, bool):
        raise EosBusinessFormalWcError(
            "EOS_BUSINESS_FORMAL_WC_RESPONSE_INVALID",
            "WC approval publication response is invalid",
            status_code=502,
        )
    return {"work_item": dict(work_item), "created": created}


def _aware_time(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EosBusinessFormalWcError(
            "EOS_BUSINESS_FORMAL_WC_CLOCK_INVALID",
            f"{field_name} must be timezone-aware",
            status_code=500,
        )
    return value.astimezone(UTC)


def _optional_time(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EosBusinessFormalWcError(
            "EOS_APPROVAL_INSTANCE_INVALID",
            "Approval instance expiry is invalid",
            status_code=409,
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EosBusinessFormalWcError(
            "EOS_APPROVAL_INSTANCE_INVALID",
            "Approval instance expiry is invalid",
            status_code=409,
        ) from exc
    return _aware_time("expires_at", parsed)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _unavailable(detail: str) -> EosBusinessFormalWcError:
    return EosBusinessFormalWcError(
        "EOS_BUSINESS_FORMAL_WC_UNAVAILABLE",
        detail,
        status_code=503,
        retryable=True,
    )
