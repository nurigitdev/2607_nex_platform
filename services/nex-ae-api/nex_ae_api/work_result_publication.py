from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref


@dataclass
class WorkResultPublicationError(Exception):
    error_code: str
    detail: str
    retryable: bool = True

    def __str__(self) -> str:
        return self.detail


class HttpWcWorkResultClient:
    """Thin authenticated boundary used by the S7 ResultDelivery publisher."""

    def __init__(
        self, *, base_url: str, service_token: str, timeout_seconds: float = 15.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def submit(
        self, *, expected_version: int, work_result: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not self._service_token.strip():
            raise WorkResultPublicationError(
                "ae.wc_work_result_service_token_missing",
                "WC WorkResult service token is not configured.",
                False,
            )
        work_item_id = _required(work_result, "work_item_id")
        result_id = _required(work_result, "result_id")
        expected_hash = semantic_sha256_hash_ref(work_result)
        request = Request(
            f"{self._base_url}/api/v1/work-items/{work_item_id}/results",
            method="POST",
            data=json.dumps(
                {
                    "expected_version": expected_version,
                    "work_result": dict(work_result),
                },
                sort_keys=True,
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise WorkResultPublicationError(
                "ae.wc_work_result_http_failed",
                f"WC WorkResult submission failed with HTTP {exc.code}.",
                exc.code >= 500 or exc.code in {408, 429},
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise WorkResultPublicationError(
                "ae.wc_work_result_unavailable",
                "WC WorkResult submission is unavailable.",
            ) from exc
        if not isinstance(payload, Mapping):
            raise _invalid_response()
        if (
            payload.get("work_item_id") != work_item_id
            or payload.get("result_id") != result_id
            or payload.get("result_hash") != expected_hash
        ):
            raise _invalid_response()
        return dict(payload)


def _required(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise WorkResultPublicationError(
            "ae.wc_work_result_invalid",
            f"{field} must be a non-empty string.",
            False,
        )
    return item.strip()


def _invalid_response() -> WorkResultPublicationError:
    return WorkResultPublicationError(
        "ae.wc_work_result_ack_invalid",
        "WC did not acknowledge the exact WorkResult identity and hash.",
        False,
    )
