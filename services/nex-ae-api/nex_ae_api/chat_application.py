from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar


ChatApplicationOperation = Literal[
    "create",
    "refresh",
    "cancel",
    "recovery",
    "retry",
]
ChatInvocationState = Literal["READY", "INVOKING", "COMPLETED", "FAILED"]
ResultT = TypeVar("ResultT")

SUPPORTED_OPERATIONS = frozenset(
    {"create", "refresh", "cancel", "recovery", "retry"}
)


@dataclass(frozen=True)
class ChatApplicationInvocationError(RuntimeError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass
class ChatApplicationInvocation:
    operation: ChatApplicationOperation
    state: ChatInvocationState = "READY"
    call_count: int = 0
    failure_type: str | None = None

    def invoke(self, callback: Callable[[], ResultT]) -> ResultT:
        if self.state != "READY":
            raise ChatApplicationInvocationError(
                "ae.chat_application.already_invoked",
                "Chat application invocation has already started.",
            )
        self.state = "INVOKING"
        self.call_count += 1
        try:
            result = callback()
        except Exception as exc:
            self.state = "FAILED"
            self.failure_type = type(exc).__name__
            raise
        self.state = "COMPLETED"
        return result


@dataclass(frozen=True)
class ChatApplicationService:
    supported_operations: frozenset[str] = field(
        default=SUPPORTED_OPERATIONS,
        init=False,
    )

    def new_invocation(
        self,
        operation: ChatApplicationOperation,
    ) -> ChatApplicationInvocation:
        self._validate_operation(operation)
        return ChatApplicationInvocation(operation=operation)

    def execute(
        self,
        operation: ChatApplicationOperation,
        callback: Callable[[], ResultT],
        *,
        invocation: ChatApplicationInvocation | None = None,
    ) -> ResultT:
        self._validate_operation(operation)
        current = invocation or self.new_invocation(operation)
        if current.operation != operation:
            raise ChatApplicationInvocationError(
                "ae.chat_application.operation_mismatch",
                "Chat application invocation operation does not match the request.",
            )
        return current.invoke(callback)

    def create(
        self,
        callback: Callable[[], ResultT],
        *,
        invocation: ChatApplicationInvocation | None = None,
    ) -> ResultT:
        return self.execute("create", callback, invocation=invocation)

    def refresh(
        self,
        callback: Callable[[], ResultT],
        *,
        invocation: ChatApplicationInvocation | None = None,
    ) -> ResultT:
        return self.execute("refresh", callback, invocation=invocation)

    def cancel(
        self,
        callback: Callable[[], ResultT],
        *,
        invocation: ChatApplicationInvocation | None = None,
    ) -> ResultT:
        return self.execute("cancel", callback, invocation=invocation)

    def recovery(
        self,
        callback: Callable[[], ResultT],
        *,
        invocation: ChatApplicationInvocation | None = None,
    ) -> ResultT:
        return self.execute("recovery", callback, invocation=invocation)

    def retry(
        self,
        callback: Callable[[], ResultT],
        *,
        invocation: ChatApplicationInvocation | None = None,
    ) -> ResultT:
        return self.execute("retry", callback, invocation=invocation)

    def _validate_operation(self, operation: str) -> None:
        if operation not in self.supported_operations:
            raise ChatApplicationInvocationError(
                "ae.chat_application.operation_unsupported",
                f"Unsupported chat application operation: {operation}",
            )
