from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from nex_wc.authorization import AuthorizationSubjectDenied

_OA_SUBJECT_DENIAL_CODES = frozenset(
    {
        "oa.authorization_membership_inactive",
        "oa.authorization_membership_not_found",
    }
)


class HttpAgentCandidateSource:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def list_agents(self, *, tenant_id: str, agent_type: str, project_id: str):
        query = urlencode(
            {"agent_type": agent_type, "status": "ACTIVE", "project_id": project_id}
        )
        payload = self._get(
            f"/internal/v1/tenants/{quote(tenant_id, safe='')}/agents?{query}"
        )
        agents = payload.get("agents")
        if not isinstance(agents, list):
            raise RuntimeError("AE Agent Registry response is invalid")
        return agents

    def get_agent(self, *, tenant_id: str, agent_id: str):
        try:
            return self._get(
                f"/internal/v1/tenants/{quote(tenant_id, safe='')}/agents/"
                f"{quote(agent_id, safe='')}"
            )
        except HttpSourceNotFound:
            return None

    def _get(self, path: str) -> dict[str, Any]:
        return _get_json(
            f"{self._base_url}{path}",
            service_token=self._service_token,
            timeout_seconds=self._timeout_seconds,
        )


class HttpAuthorizationSource:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        payload = _get_json(
            f"{self._base_url}/internal/v1/auth/tenants/"
            f"{quote(tenant_id, safe='')}/subjects/{quote(subject_id, safe='')}/authorization",
            service_token=self._service_token,
            timeout_seconds=self._timeout_seconds,
            subject_denial_codes=_OA_SUBJECT_DENIAL_CODES,
        )
        authorization = payload.get("authorization")
        if not isinstance(authorization, dict):
            raise AuthorizationSubjectDenied("OA authorization response is malformed.")
        return {**authorization, "active": True}


class HttpSourceNotFound(RuntimeError):
    pass


def _get_json(
    url: str,
    *,
    service_token: str,
    timeout_seconds: float,
    subject_denial_codes: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if not service_token.strip():
        raise RuntimeError("service token is not configured")
    request = Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {service_token}",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_code = _http_problem_error_code(exc)
        if error_code in subject_denial_codes:
            raise AuthorizationSubjectDenied(
                "OA denied the subject authorization request."
            ) from exc
        if exc.code == 404:
            raise HttpSourceNotFound("source record was not found") from exc
        raise RuntimeError(f"source request failed with HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("source request failed") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("source response must be an object")
    return payload


def _http_problem_error_code(exc: HTTPError) -> str | None:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    error_code = payload.get("error_code")
    return error_code if isinstance(error_code, str) else None
