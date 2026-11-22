from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from nex_ae_api.service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)

AGENT_AUTHORITY_SYNC_MODE_ENV = "NEX_AE_AGENT_AUTHORITY_SYNC_MODE"
AGENT_AUTHORITY_SYNC_MODES = frozenset({"disabled", "required"})
DEFAULT_AGENT_AUTHORITY_TIMEOUT_SECONDS = 10.0

_AGENT_AUTHORITY_SCOPES = {
    "IA": ("work:claim", "work:delegate"),
    "CA": ("work:claim", "work:delegate", "work:result:submit"),
    "PA": ("work:claim", "work:delegate", "work:result:submit"),
    "EA": ("work:claim", "work:delegate", "work:result:submit"),
}

HttpRequester = Callable[..., httpx.Response]


@dataclass(frozen=True)
class AgentAuthoritySyncError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class AgentAuthoritySynchronizer(Protocol):
    def synchronize(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        agent_type: str,
        status: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class HttpOaAgentAuthoritySynchronizer:
    base_url: str
    service_token: str
    timeout_seconds: float = DEFAULT_AGENT_AUTHORITY_TIMEOUT_SECONDS
    requester: HttpRequester = httpx.request

    def synchronize(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        agent_type: str,
        status: str,
    ) -> dict[str, Any]:
        tenant = _text(tenant_id, "tenant_id")
        agent = _text(agent_id, "agent_id")
        kind = _agent_type(agent_type)
        target_status = "ACTIVE" if status in {"ACTIVE", "CLOSING"} else "DISABLED"
        token = self._token()
        membership = self._membership(token, tenant_id=tenant, agent_id=agent)
        authority_changed = False
        if membership is None:
            if target_status == "DISABLED":
                return _receipt(tenant, agent, kind, target_status, changed=False)
            membership = self._ensure(
                token, tenant_id=tenant, agent_id=agent, agent_type=kind
            )
            authority_changed = True

        record = _membership_record(membership, tenant_id=tenant, agent_id=agent)
        if not _authority_profile_matches(record, agent_type=kind):
            _require_managed_authority(record, agent_type=kind)
            membership = self._replace_authority(
                token,
                tenant_id=tenant,
                agent_id=agent,
                agent_type=kind,
                expected_revision=record["revision"],
            )
            record = _membership_record(
                membership,
                tenant_id=tenant,
                agent_id=agent,
            )
            _require_authority_profile(record, agent_type=kind)
            authority_changed = True
        current_status = str(record.get("status") or "")
        lifecycle_changed = current_status != target_status
        if lifecycle_changed:
            transition = self._transition(
                token,
                tenant_id=tenant,
                agent_id=agent,
                target_status=target_status,
                expected_revision=record.get("revision"),
            )
            if (
                transition.get("tenant_id") != tenant
                or transition.get("subject_id") != agent
                or transition.get("status") != target_status
                or not isinstance(transition.get("revision"), int)
            ):
                raise _invalid("OA Agent authority lifecycle response was not applied.")
        return _receipt(
            tenant,
            agent,
            kind,
            target_status,
            changed=authority_changed or lifecycle_changed,
        )

    def _membership(
        self, token: str, *, tenant_id: str, agent_id: str
    ) -> dict[str, Any] | None:
        response = self._request(
            "GET",
            "/internal/v1/identity/memberships/tenants/"
            f"{tenant_id}/subjects/{agent_id}",
            token=token,
        )
        if response.status_code == 404:
            return None
        return _response_object(response, operation="read")

    def _ensure(
        self, token: str, *, tenant_id: str, agent_id: str, agent_type: str
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/internal/v1/identity/memberships/ensure",
            token=token,
            json={
                "tenant_id": tenant_id,
                "subject_id": agent_id,
                "tenant_display_name": tenant_id,
                "subject_display_name": f"NeX {agent_type} Agent",
                "roles": _authority_roles(agent_type),
                "scopes": list(_AGENT_AUTHORITY_SCOPES[agent_type]),
                "membership_metadata": {
                    "source": "nex-ae-agent-identity",
                    "agent_type": agent_type,
                },
            },
        )
        return _response_object(response, operation="ensure")

    def _transition(
        self,
        token: str,
        *,
        tenant_id: str,
        agent_id: str,
        target_status: str,
        expected_revision: object,
    ) -> dict[str, Any]:
        response = self._request(
            "PATCH",
            f"/internal/v1/identity/tenants/{tenant_id}/memberships/{agent_id}/lifecycle",
            token=token,
            json={
                "target_status": target_status,
                "expected_revision": expected_revision,
                "reason_code": "ae.agent-lifecycle-sync",
            },
        )
        return _response_object(response, operation="lifecycle")

    def _replace_authority(
        self,
        token: str,
        *,
        tenant_id: str,
        agent_id: str,
        agent_type: str,
        expected_revision: object,
    ) -> dict[str, Any]:
        response = self._request(
            "PUT",
            "/internal/v1/identity/memberships/tenants/"
            f"{tenant_id}/subjects/{agent_id}/authority",
            token=token,
            json={
                "expected_revision": expected_revision,
                "roles": _authority_roles(agent_type),
                "scopes": list(_AGENT_AUTHORITY_SCOPES[agent_type]),
            },
        )
        return _response_object(response, operation="authority")

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        json: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            return self.requester(
                method,
                f"{self.base_url.rstrip('/')}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Service-ID": "nex-ae-api",
                },
                json=None if json is None else dict(json),
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise AgentAuthoritySyncError(
                "ae.agent_authority_sync_timeout",
                "OA Agent authority synchronization timed out.",
                True,
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentAuthoritySyncError(
                "ae.agent_authority_sync_unavailable",
                "OA Agent authority synchronization is unavailable.",
                True,
            ) from exc

    def _token(self) -> str:
        try:
            return resolve_ae_outbound_service_token(
                self.service_token,
                audience="nex-oa",
            )
        except AeOutboundServiceTokenError as exc:
            raise AgentAuthoritySyncError(
                "ae.agent_authority_token_unavailable",
                "AE-to-OA Agent authority token is unavailable.",
                True,
            ) from exc


def build_agent_authority_synchronizer(
    environ: Mapping[str, str] | None = None,
) -> AgentAuthoritySynchronizer | None:
    env = os.environ if environ is None else environ
    mode = str(env.get(AGENT_AUTHORITY_SYNC_MODE_ENV) or "disabled").strip().lower()
    if mode not in AGENT_AUTHORITY_SYNC_MODES:
        raise AgentAuthoritySyncError(
            "ae.agent_authority_sync_mode_invalid",
            f"{AGENT_AUTHORITY_SYNC_MODE_ENV} must be disabled or required.",
        )
    if mode == "disabled":
        return None
    base_url = str(env.get("NEX_OA_BASE_URL") or "").strip()
    token = str(env.get("NEX_AE_TO_OA_SERVICE_TOKEN") or "").strip()
    if not base_url or not token:
        raise AgentAuthoritySyncError(
            "ae.agent_authority_sync_configuration_missing",
            "Required OA Agent authority synchronization is not configured.",
        )
    return HttpOaAgentAuthoritySynchronizer(
        base_url=base_url,
        service_token=token,
        timeout_seconds=_positive_float(
            env.get("NEX_AE_AGENT_AUTHORITY_SYNC_TIMEOUT_SECONDS"),
            default=DEFAULT_AGENT_AUTHORITY_TIMEOUT_SECONDS,
        ),
    )


def _response_object(response: httpx.Response, *, operation: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise _invalid(
            f"OA Agent authority {operation} response was not JSON."
        ) from exc
    if not isinstance(body, dict):
        raise _invalid(f"OA Agent authority {operation} response was malformed.")
    if response.status_code >= 400:
        raise AgentAuthoritySyncError(
            str(body.get("error_code") or f"ae.agent_authority_{operation}_rejected"),
            f"OA Agent authority {operation} was rejected.",
            response.status_code >= 500,
        )
    return body


def _membership_record(
    value: Mapping[str, Any], *, tenant_id: str, agent_id: str
) -> dict[str, Any]:
    nested = value.get("membership")
    record = nested if isinstance(nested, Mapping) else value
    tenant_ref = record.get("tenant_ref")
    subject_ref = record.get("subject_ref")
    if (
        not isinstance(tenant_ref, Mapping)
        or tenant_ref.get("id") != tenant_id
        or not isinstance(subject_ref, Mapping)
        or subject_ref.get("id") != agent_id
    ):
        raise _invalid("OA Agent authority response identity binding was invalid.")
    if record.get("status") not in {"ACTIVE", "DISABLED"}:
        raise _invalid("OA Agent authority response status was invalid.")
    if not isinstance(record.get("revision"), int) or int(record["revision"]) < 1:
        raise _invalid("OA Agent authority response revision was invalid.")
    return dict(record)


def _authority_roles(agent_type: str) -> list[str]:
    return ["nex-agent", f"nex-agent-{agent_type.lower()}"]


def _authority_profile_matches(record: Mapping[str, Any], *, agent_type: str) -> bool:
    roles = record.get("roles")
    scopes = record.get("scopes")
    return (
        isinstance(roles, list)
        and all(isinstance(item, str) for item in roles)
        and set(roles) == set(_authority_roles(agent_type))
        and isinstance(scopes, list)
        and all(isinstance(item, str) for item in scopes)
        and set(scopes) == set(_AGENT_AUTHORITY_SCOPES[agent_type])
    )


def _require_managed_authority(record: Mapping[str, Any], *, agent_type: str) -> None:
    metadata = record.get("metadata")
    if (
        not isinstance(metadata, Mapping)
        or metadata.get("source") != "nex-ae-agent-identity"
        or metadata.get("agent_type") != agent_type
    ):
        raise AgentAuthoritySyncError(
            "ae.agent_authority_scope_drift",
            "OA Agent authority profile drift is not managed by AE.",
        )


def _require_authority_profile(record: Mapping[str, Any], *, agent_type: str) -> None:
    if not _authority_profile_matches(record, agent_type=agent_type):
        raise AgentAuthoritySyncError(
            "ae.agent_authority_scope_drift",
            "OA Agent authority profile does not match its admitted capability.",
        )


def _receipt(
    tenant_id: str,
    agent_id: str,
    agent_type: str,
    status: str,
    *,
    changed: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "ae.agent_authority_sync_receipt.v1",
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "agent_type": agent_type,
        "status": status,
        "changed": changed,
        "scopes": list(_AGENT_AUTHORITY_SCOPES[agent_type]),
    }


def _agent_type(value: object) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in _AGENT_AUTHORITY_SCOPES:
        raise _invalid("Agent authority type was invalid.")
    return normalized


def _text(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 200:
        raise _invalid(f"{field_name} was invalid.")
    return normalized


def _positive_float(value: object, *, default: float) -> float:
    try:
        parsed = default if value is None else float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise _invalid("Agent authority synchronization timeout was invalid.") from exc
    if parsed <= 0:
        raise _invalid("Agent authority synchronization timeout was invalid.")
    return parsed


def _invalid(detail: str) -> AgentAuthoritySyncError:
    return AgentAuthoritySyncError("ae.agent_authority_sync_invalid", detail)


__all__ = [
    "AGENT_AUTHORITY_SYNC_MODE_ENV",
    "AgentAuthoritySyncError",
    "AgentAuthoritySynchronizer",
    "HttpOaAgentAuthoritySynchronizer",
    "build_agent_authority_synchronizer",
]
