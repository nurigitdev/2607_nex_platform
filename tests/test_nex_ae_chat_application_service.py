from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nex_ae_api.chat import register_chat_routes
from nex_ae_api.chat_application import (
    ChatApplicationInvocationError,
    ChatApplicationService,
)
from nex_runtime import SERVICE_SPECS, build_service_app


def test_invocation_executes_callback_exactly_once() -> None:
    service = ChatApplicationService()
    invocation = service.new_invocation("create")
    calls: list[str] = []

    result = service.create(
        lambda: calls.append("called") or {"status": "ok"},
        invocation=invocation,
    )

    assert result == {"status": "ok"}
    assert calls == ["called"]
    assert invocation.state == "COMPLETED"
    assert invocation.call_count == 1
    assert invocation.failure_type is None

    with pytest.raises(ChatApplicationInvocationError) as exc_info:
        service.create(lambda: calls.append("duplicate"), invocation=invocation)
    assert exc_info.value.error_code == "ae.chat_application.already_invoked"
    assert str(exc_info.value) == "Chat application invocation has already started."
    assert calls == ["called"]


def test_failed_invocation_cannot_replay_chat_operation() -> None:
    service = ChatApplicationService()
    invocation = service.new_invocation("create")
    calls = 0

    def fail_after_start() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("provider failed after invocation")

    with pytest.raises(ValueError, match="provider failed"):
        service.create(fail_after_start, invocation=invocation)

    assert invocation.state == "FAILED"
    assert invocation.call_count == 1
    assert invocation.failure_type == "ValueError"
    with pytest.raises(ChatApplicationInvocationError):
        service.create(fail_after_start, invocation=invocation)
    assert calls == 1


def test_pre_invocation_failure_leaves_token_available_for_one_fallback() -> None:
    service = ChatApplicationService()
    invocation = service.new_invocation("create")

    assert invocation.state == "READY"
    assert service.create(lambda: "legacy-result", invocation=invocation) == (
        "legacy-result"
    )
    assert invocation.state == "COMPLETED"


def test_operation_mismatch_and_unknown_operation_fail_closed() -> None:
    service = ChatApplicationService()
    invocation = service.new_invocation("refresh")

    with pytest.raises(ChatApplicationInvocationError) as mismatch:
        service.cancel(lambda: None, invocation=invocation)
    assert mismatch.value.error_code == "ae.chat_application.operation_mismatch"
    assert invocation.state == "READY"

    with pytest.raises(ChatApplicationInvocationError) as unsupported:
        service.execute("delete", lambda: None)  # type: ignore[arg-type]
    assert unsupported.value.error_code == (
        "ae.chat_application.operation_unsupported"
    )


@pytest.mark.parametrize(
    ("method_name", "expected"),
    [
        ("refresh", "refresh"),
        ("cancel", "cancel"),
        ("recovery", "recovery"),
        ("retry", "retry"),
    ],
)
def test_named_application_operations_use_the_common_seam(
    method_name: str,
    expected: str,
) -> None:
    service = ChatApplicationService()
    method = getattr(service, method_name)

    assert method(lambda: expected) == expected


class _RecordingApplicationService:
    def __init__(self) -> None:
        self.delegate = ChatApplicationService()
        self.operations: list[str] = []

    def create(self, callback, **kwargs):
        self.operations.append("create")
        return self.delegate.create(callback, **kwargs)

    def refresh(self, callback, **kwargs):
        self.operations.append("refresh")
        return self.delegate.refresh(callback, **kwargs)

    def cancel(self, callback, **kwargs):
        self.operations.append("cancel")
        return self.delegate.cancel(callback, **kwargs)

    def recovery(self, callback, **kwargs):
        self.operations.append("recovery")
        return self.delegate.recovery(callback, **kwargs)

    def retry(self, callback, **kwargs):
        self.operations.append("retry")
        return self.delegate.retry(callback, **kwargs)


def test_chat_routes_are_adapters_over_the_injected_application_service() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    application_service = _RecordingApplicationService()
    register_chat_routes(
        app,
        application_service=application_service,  # type: ignore[arg-type]
    )
    client = TestClient(app)

    responses = (
        client.post("/api/v1/chat/interactions", json={}),
        client.post("/api/v1/chat/interactions/missing/refresh"),
        client.post("/api/v1/chat/interactions/missing/cancel"),
        client.get("/api/v1/chat/interactions/missing/recovery"),
        client.post("/api/v1/chat/interactions/missing/retry", json={}),
    )

    assert {response.status_code for response in responses} == {401}
    assert application_service.operations == [
        "create",
        "refresh",
        "cancel",
        "recovery",
        "retry",
    ]
    assert app.state.ae_chat_application_service is application_service
