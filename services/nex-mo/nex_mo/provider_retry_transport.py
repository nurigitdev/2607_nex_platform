from __future__ import annotations

from typing import Any, Callable

from nex_mo.provider_retry import (
    ProviderRetryEvent,
    ProviderRetryPolicy,
    execute_with_provider_retry,
)
from nex_mo.provider_transport import (
    HttpRequester,
    RemoteRequestConfigView,
    execute_remote_json_request,
)


def execute_remote_json_request_with_retry(
    config: RemoteRequestConfigView,
    *,
    json_payload: dict[str, Any],
    requester: HttpRequester | None,
    error_code_prefix: str,
    retry_policy: ProviderRetryPolicy,
    sleeper: Callable[[float], None] | None = None,
    jitter: Callable[[], float] | None = None,
    on_retry: Callable[[ProviderRetryEvent], None] | None = None,
) -> Any:
    def attempt() -> Any:
        return execute_remote_json_request(
            config,
            json_payload=json_payload,
            requester=requester,
            error_code_prefix=error_code_prefix,
        )

    retry_kwargs: dict[str, Any] = {}
    if sleeper is not None:
        retry_kwargs["sleeper"] = sleeper
    if jitter is not None:
        retry_kwargs["jitter"] = jitter
    if on_retry is not None:
        retry_kwargs["on_retry"] = on_retry
    return execute_with_provider_retry(
        attempt,
        policy=retry_policy,
        **retry_kwargs,
    ).value
