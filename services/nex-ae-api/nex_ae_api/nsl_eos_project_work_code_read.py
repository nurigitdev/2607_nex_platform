from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from nex_ae_api.service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)

EOS_PROJECT_WORK_CODE_GET_OPERATION = "PROJECT.WORK_CODE_SET.GET"
EOS_PROJECT_WORK_CODE_PATH = "/internal/v2/projects/{project_id}/work-code-set"
_INPUT_FIELDS = frozenset(
    {"tenant_id", "requester_subject_id", "project_id", "effective_on"}
)
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class EosProjectWorkCodeReadError(RuntimeError):
    error_code: str
    detail: str
    retryable: bool = False
    status_code: int | None = None

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class HttpEosProjectWorkCodeReadAdapter:
    base_url: str
    service_token: str | None = None
    timeout_seconds: float = 15.0
    transport: httpx.BaseTransport | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        url = httpx.URL(self.base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or bool(url.username)
            or bool(url.password)
            or url.query
            or url.fragment
        ):
            raise ValueError("EOS Project WorkCode base URL is invalid")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("EOS Project WorkCode timeout must be positive")

    def __call__(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        values = _arguments(arguments)
        try:
            token = resolve_ae_outbound_service_token(
                self.service_token, audience="nex-eos"
            )
        except AeOutboundServiceTokenError as exc:
            raise EosProjectWorkCodeReadError(
                "ae.nsl_eos_project_work_code.service_token_unavailable",
                "EOS Project WorkCode authentication is unavailable.",
            ) from exc
        params = (
            {}
            if values["effective_on"] is None
            else {"effective_on": values["effective_on"]}
        )
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = client.get(
                    self.base_url.rstrip("/")
                    + EOS_PROJECT_WORK_CODE_PATH.format(
                        project_id=values["project_id"]
                    ),
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Cache-Control": "no-store, max-age=0",
                        "X-NeX-Tenant-Id": values["tenant_id"],
                        "X-NeX-Subject-Id": values["requester_subject_id"],
                        "X-Service-ID": "nex-ae-api",
                    },
                )
        except httpx.TimeoutException as exc:
            raise EosProjectWorkCodeReadError(
                "ae.nsl_eos_project_work_code.timeout",
                "EOS Project WorkCode read timed out.",
                True,
            ) from exc
        except httpx.NetworkError as exc:
            raise EosProjectWorkCodeReadError(
                "ae.nsl_eos_project_work_code.connection_lost",
                "EOS Project WorkCode connection was lost.",
                True,
            ) from exc
        payload = _payload(response)
        if response.status_code != 200:
            raise EosProjectWorkCodeReadError(
                "ae.nsl_eos_project_work_code.rejected",
                "EOS rejected the Project WorkCode read.",
                response.status_code >= 500,
                response.status_code,
            )
        return _result(payload, values)


def _arguments(value: Mapping[str, Any]) -> dict[str, str | None]:
    if not isinstance(value, Mapping) or set(value) != _INPUT_FIELDS:
        raise EosProjectWorkCodeReadError(
            "ae.nsl_eos_project_work_code.arguments_invalid",
            "Project WorkCode arguments do not match the admitted contract.",
        )
    tenant_id = _scoped("tenant_id", value.get("tenant_id"))
    requester = _scoped("requester_subject_id", value.get("requester_subject_id"))
    project_id = str(value.get("project_id") or "")
    if _UUID.fullmatch(project_id) is None:
        raise EosProjectWorkCodeReadError(
            "ae.nsl_eos_project_work_code.arguments_invalid",
            "Project WorkCode project_id is invalid.",
        )
    effective = value.get("effective_on")
    if effective is not None:
        try:
            effective = date.fromisoformat(str(effective)).isoformat()
        except ValueError as exc:
            raise EosProjectWorkCodeReadError(
                "ae.nsl_eos_project_work_code.arguments_invalid",
                "Project WorkCode effective_on is invalid.",
            ) from exc
    return {
        "tenant_id": tenant_id,
        "requester_subject_id": requester,
        "project_id": project_id,
        "effective_on": effective,
    }


def _payload(response: httpx.Response) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise EosProjectWorkCodeReadError(
            "ae.nsl_eos_project_work_code.response_invalid",
            "EOS Project WorkCode response is not JSON.",
            status_code=response.status_code,
        ) from exc
    if not isinstance(payload, Mapping):
        raise EosProjectWorkCodeReadError(
            "ae.nsl_eos_project_work_code.response_invalid",
            "EOS Project WorkCode response is not an object.",
            status_code=response.status_code,
        )
    return payload


def _result(
    value: Mapping[str, Any], request: Mapping[str, str | None]
) -> dict[str, Any]:
    revision = value.get("revision")
    state = value.get("state")
    work_set_hash = value.get("work_set_hash")
    if (
        value.get("tenant_id") != request["tenant_id"]
        or value.get("project_id") != request["project_id"]
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or state != "APPROVED"
        or not isinstance(work_set_hash, str)
        or _HASH_REF.fullmatch(work_set_hash) is None
    ):
        raise EosProjectWorkCodeReadError(
            "ae.nsl_eos_project_work_code.response_invalid",
            "EOS Project WorkCode response lineage is invalid.",
        )
    return {
        "project_id": value["project_id"],
        "revision": revision,
        "state": state,
        "work_set_hash": work_set_hash,
    }


def _scoped(name: str, value: object) -> str:
    text = str(value or "")
    if _SCOPED_ID.fullmatch(text) is None:
        raise EosProjectWorkCodeReadError(
            "ae.nsl_eos_project_work_code.arguments_invalid",
            f"Project WorkCode {name} is invalid.",
        )
    return text
