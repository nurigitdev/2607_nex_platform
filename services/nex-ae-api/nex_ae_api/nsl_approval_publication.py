from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx
from nex_runtime import SERVICE_SPECS
from nex_runtime.semantic_hashes import canonical_json

from nex_ae_api.delegated_work import (
    DelegatedWorkError,
    deterministic_nsl_approval_wait_id,
)
from nex_ae_api.nsl_approval_requests import (
    ProtectedApprovalRequestError,
    canonical_approval_request_data,
)
from nex_ae_api.service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)

DEFAULT_WC_BASE_URL = f"http://127.0.0.1:{SERVICE_SPECS['nex-wc'].default_port}"
NSL_APPROVAL_RESUME_CONTRACT_REF = "urn:nex:approval-resume:p8:v1"


@dataclass(frozen=True)
class ApprovalPublicationError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class ApprovalCheckpointBindingSource(Protocol):
    def resolve(self, approval_request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class ProtectedApprovalRequestStore(Protocol):
    def persist(self, approval_request: object) -> Mapping[str, Any]: ...


class ApprovalWaitRepository(Protocol):
    def register(self, **values: Any) -> Mapping[str, Any]: ...


class WcApprovalWorkItemClient(Protocol):
    def create_or_get(self, work_item: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class HttpWcApprovalWorkItemClient:
    base_url: str = DEFAULT_WC_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = 15.0

    def create_or_get(self, work_item: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            token = resolve_ae_outbound_service_token(
                self.service_token,
                audience="nex-wc",
            )
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/api/v1/approval-work-items",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-NeX-Tenant-Id": str(work_item.get("tenant_id", "")),
                    "X-Service-ID": "nex-ae-api",
                },
                json=dict(work_item),
                timeout=self.timeout_seconds,
            )
        except (httpx.HTTPError, AeOutboundServiceTokenError) as exc:
            raise ApprovalPublicationError(
                "ae.nsl_approval_wc_unavailable",
                "WC approval publication is unavailable.",
                True,
            ) from exc
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApprovalPublicationError(
                "ae.nsl_approval_wc_response_invalid",
                "WC approval publication response is invalid.",
                response.status_code >= 500,
            ) from exc
        if response.status_code >= 400:
            retryable = response.status_code >= 500
            if isinstance(payload, Mapping) and isinstance(
                payload.get("retryable"), bool
            ):
                retryable = bool(payload["retryable"])
            raise ApprovalPublicationError(
                "ae.nsl_approval_wc_rejected",
                f"WC approval publication failed with HTTP {response.status_code}.",
                retryable,
            )
        return _wc_result(payload)


class P8NSLApprovalPort:
    """NSL v0.2 ApprovalPort with durable AE-before-WC publication ordering."""

    def __init__(
        self,
        *,
        binding_source: ApprovalCheckpointBindingSource,
        request_store: ProtectedApprovalRequestStore,
        wait_repository: ApprovalWaitRepository,
        wc_client: WcApprovalWorkItemClient,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._binding_source = binding_source
        self._request_store = request_store
        self._wait_repository = wait_repository
        self._wc_client = wc_client
        self._clock = clock or (lambda: datetime.now(UTC))

    async def publish(self, request: object) -> None:
        approval_request = canonical_approval_request_data(request)
        binding = _binding(self._binding_source, approval_request)
        try:
            protected = dict(self._request_store.persist(request))
            _require_protected_lineage(protected, approval_request)
            wait_id = deterministic_nsl_approval_wait_id(
                tenant_id=approval_request["tenant_id"],
                agent_execution_id=binding["agent_execution_id"],
                executable_step_id=binding["executable_step_id"],
                approval_request_id=approval_request["approval_request_id"],
                checkpoint_version=binding["checkpoint_version"],
            )
            wait = dict(
                self._wait_repository.register(
                    wait_id=wait_id,
                    tenant_id=approval_request["tenant_id"],
                    agent_execution_id=binding["agent_execution_id"],
                    executable_step_id=binding["executable_step_id"],
                    external_ref=approval_request["approval_request_id"],
                    result_contract_ref=NSL_APPROVAL_RESUME_CONTRACT_REF,
                    created_at=_time(self._clock()),
                    wait_type="NSL_APPROVAL",
                    nsl_execution_id=approval_request["execution_id"],
                    business_operation_id=approval_request["business_operation_id"],
                    approval_request_id=approval_request["approval_request_id"],
                    checkpoint_version=binding["checkpoint_version"],
                )
            )
            work_item = _work_item(
                approval_request=approval_request,
                protected=protected,
                binding=binding,
                wait=wait,
                created_at=_time(self._clock()),
            )
            published = _wc_result(self._wc_client.create_or_get(work_item))
            _require_wc_lineage(published["work_item"], work_item)
        except ApprovalPublicationError:
            raise
        except ProtectedApprovalRequestError as exc:
            raise ApprovalPublicationError(
                exc.error_code, exc.detail, exc.retryable
            ) from exc
        except DelegatedWorkError as exc:
            raise ApprovalPublicationError(
                exc.error_code, exc.detail, exc.retryable
            ) from exc


def deterministic_approval_work_item_id(
    *, tenant_id: str, approval_request_id: str
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/wc/approval-work-items/"
            f"{tenant_id}/{approval_request_id}",
        )
    )


def build_default_wc_approval_work_item_client() -> HttpWcApprovalWorkItemClient:
    return HttpWcApprovalWorkItemClient(
        base_url=os.getenv("NEX_WC_BASE_URL", DEFAULT_WC_BASE_URL),
        service_token=os.getenv("NEX_AE_TO_WC_SERVICE_TOKEN"),
    )


def _binding(
    source: ApprovalCheckpointBindingSource,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        raw = source.resolve(request)
    except Exception as exc:
        raise ApprovalPublicationError(
            "ae.nsl_approval_checkpoint_unavailable",
            "Persisted NSL approval checkpoint binding is unavailable.",
            True,
        ) from exc
    if not isinstance(raw, Mapping):
        raise _invalid("NSL approval checkpoint binding must be an object.")
    result = dict(raw)
    for field in (
        "tenant_id",
        "agent_execution_id",
        "executable_step_id",
        "nsl_execution_id",
        "business_operation_id",
    ):
        result[field] = _required(field, result.get(field), 256)
    version = result.get("checkpoint_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _invalid("checkpoint_version must be a positive integer.")
    result["checkpoint_version"] = version
    if (
        result["tenant_id"] != request["tenant_id"]
        or result["nsl_execution_id"] != request["execution_id"]
        or result["business_operation_id"] != request["business_operation_id"]
    ):
        raise _invalid("Persisted checkpoint and ApprovalRequest lineage differ.")
    targets = (
        "target_approver_ref",
        "target_role_ref",
        "target_org_scope_ref",
        "target_project_scope_ref",
    )
    for field in targets:
        value = result.get(field)
        result[field] = None if value is None else _required(field, value, 128)
    if not any(result[field] is not None for field in targets):
        raise _invalid("NSL approval publication requires a decision target.")
    return result


def _work_item(
    *,
    approval_request: Mapping[str, Any],
    protected: Mapping[str, Any],
    binding: Mapping[str, Any],
    wait: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    summary = canonical_json(approval_request["display_safe_summary"])
    if len(summary) > 2000:
        raise _invalid("Approval display-safe summary exceeds the WC boundary.")
    approval_id = _required("approval_id", approval_request["approval_id"], 256)
    title = f"Approve NSL WRITE: {approval_id}"
    return {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": approval_request["tenant_id"],
        "approval_work_item_id": deterministic_approval_work_item_id(
            tenant_id=approval_request["tenant_id"],
            approval_request_id=approval_request["approval_request_id"],
        ),
        "approval_domain": "NSL_WRITE",
        "source_ref": approval_request["approval_request_id"],
        "semantic_hash": protected["approval_request_hash"],
        "title": title,
        "display_safe_summary": summary,
        "approval_provider_type": "NSL",
        "approval_target_ref": approval_request["approval_request_id"],
        "target_approver_ref": binding["target_approver_ref"],
        "target_role_ref": binding["target_role_ref"],
        "target_org_scope_ref": binding["target_org_scope_ref"],
        "target_project_scope_ref": binding["target_project_scope_ref"],
        "agent_execution_id": binding["agent_execution_id"],
        "executable_step_id": binding["executable_step_id"],
        "nsl_execution_id": approval_request["execution_id"],
        "business_operation_id": approval_request["business_operation_id"],
        "approval_request_id": approval_request["approval_request_id"],
        "protected_request_ref": protected["protected_request_ref"],
        "resume_target_ref": f"ae-wait:{wait['wait_id']}",
        "state": "PENDING",
        "created_at": created_at,
        "expires_at": _optional_time(approval_request["expires_at"]),
        "version": 1,
    }


def _require_protected_lineage(
    protected: Mapping[str, Any], request: Mapping[str, Any]
) -> None:
    expected = {
        "tenant_id": request["tenant_id"],
        "approval_request_id": request["approval_request_id"],
        "nsl_execution_id": request["execution_id"],
        "business_operation_id": request["business_operation_id"],
    }
    if any(protected.get(field) != value for field, value in expected.items()):
        raise _invalid("Protected ApprovalRequest lineage is invalid.")
    for field in ("protected_request_ref", "approval_request_hash"):
        _required(field, protected.get(field), 512)


def _require_wc_lineage(
    actual: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    fields = (
        "tenant_id",
        "approval_work_item_id",
        "source_ref",
        "semantic_hash",
        "approval_request_id",
        "nsl_execution_id",
        "business_operation_id",
        "resume_target_ref",
    )
    if any(actual.get(field) != expected.get(field) for field in fields):
        raise ApprovalPublicationError(
            "ae.nsl_approval_wc_response_invalid",
            "WC approval publication response lineage is invalid.",
        )


def _wc_result(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ApprovalPublicationError(
            "ae.nsl_approval_wc_response_invalid",
            "WC approval publication response is invalid.",
        )
    work_item = value.get("work_item")
    created = value.get("created")
    if not isinstance(work_item, Mapping) or not isinstance(created, bool):
        raise ApprovalPublicationError(
            "ae.nsl_approval_wc_response_invalid",
            "WC approval publication response is invalid.",
        )
    return {"work_item": dict(work_item), "created": created}


def _required(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} must be a bounded non-empty string.")
    return value.strip()


def _time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise _invalid("Approval publication clock must be timezone-aware.")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _optional_time(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid("Approval expiration must be an RFC3339 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("Approval expiration must be an RFC3339 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid("Approval expiration must include a timezone.")
    return _time(parsed)


def _invalid(detail: str) -> ApprovalPublicationError:
    return ApprovalPublicationError("ae.nsl_approval_publication_invalid", detail)
