from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .nsl_v02_public_api import NslV02PublicApiAdapter


@dataclass(frozen=True)
class NslControlledWriteIntegrationError(RuntimeError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class NslControlledWriteRequest:
    intent: Any
    context: Any
    contract: Any
    contract_evidence: Any
    execution_evidence: Any
    business_preconditions: Any
    approval_evidence: Any
    approval_request_id: Any
    provider_idempotency_evidence: Any
    invocation_id: str
    trace_refs: tuple[str, ...]
    evaluated_at: datetime
    required_until: datetime
    requested_at: datetime

    def __post_init__(self) -> None:
        _required_text("invocation_id", self.invocation_id)
        if (
            not isinstance(self.trace_refs, tuple)
            or not self.trace_refs
            or not all(
                isinstance(item, str) and bool(item.strip()) for item in self.trace_refs
            )
        ):
            raise _invalid("trace_refs must be a non-empty tuple of strings.")
        evaluated_at = _utc("evaluated_at", self.evaluated_at)
        required_until = _utc("required_until", self.required_until)
        requested_at = _utc("requested_at", self.requested_at)
        if required_until <= evaluated_at:
            raise _invalid("required_until must be later than evaluated_at.")
        if requested_at < evaluated_at:
            raise _invalid("requested_at cannot predate evaluated_at.")


@dataclass(frozen=True)
class NslControlledWriteResult:
    decision: Any
    reservation: Any
    write_request: Any
    outcome: Any
    verification: Any | None


class NslControlledWriteIntegration:
    """Compose admitted NSL WRITE semantics over Platform-owned ports."""

    def __init__(
        self,
        *,
        public_api: NslV02PublicApiAdapter,
        policy_port: Any,
        idempotency_port: Any,
        write_evidence_port: Any,
        write_port: Any,
        verification_port: Any,
    ) -> None:
        if not isinstance(public_api, NslV02PublicApiAdapter):
            raise _invalid("Controlled WRITE requires the admitted NSL public API.")
        for name in (
            "idempotency_coordinator",
            "provider_idempotency_evidence",
            "write_guard",
            "write_guard_request",
            "write_policy_request_factory",
            "write_call_request_builder",
            "write_execution_coordinator",
            "post_write_verifier",
            "verification_result",
        ):
            if not callable(getattr(public_api, name, None)):
                raise _invalid(f"Admitted NSL {name} is unavailable.")
        for port, method, label in (
            (policy_port, "authorize_write", "runtime policy"),
            (idempotency_port, "reserve", "idempotency evidence"),
            (write_evidence_port, "record_requested", "WRITE_REQUESTED evidence"),
            (write_port, "execute", "WRITE execution"),
            (verification_port, "read", "post-WRITE verification"),
        ):
            if not callable(getattr(port, method, None)):
                raise _invalid(f"Controlled WRITE {label} port is unavailable.")
        self._public_api = public_api
        self._policy_port = policy_port
        self._idempotency_port = idempotency_port
        self._write_evidence_port = write_evidence_port
        self._write_port = write_port
        self._verification_port = verification_port

    async def execute(
        self,
        request: NslControlledWriteRequest,
    ) -> NslControlledWriteResult:
        if not isinstance(request, NslControlledWriteRequest):
            raise _invalid("Controlled WRITE request is invalid.")
        require_approval = getattr(
            request.intent,
            "require_approval_identity",
            None,
        )
        if not callable(require_approval):
            raise _invalid("NSL WriteIntent approval binding is unavailable.")
        require_approval(request.approval_evidence)

        policy_request = self._public_api.write_policy_request_factory(
            request.intent,
            request.context,
            request.contract_evidence,
        )
        policy_decision = self._policy_port.authorize_write(policy_request)
        guard_request = self._public_api.write_guard_request(
            intent=request.intent,
            context=request.context,
            contract_evidence=request.contract_evidence,
            execution_evidence=request.execution_evidence,
            policy_decision=policy_decision,
            business_preconditions=request.business_preconditions,
        )
        decision = self._public_api.write_guard().evaluate(
            guard_request,
            now=request.evaluated_at,
        )

        reservation = await self._public_api.idempotency_coordinator(
            self._idempotency_port
        ).reserve(
            intent=request.intent,
            context=request.context,
            contract=request.contract,
            provider_evidence=request.provider_idempotency_evidence,
            now=request.evaluated_at,
            required_until=request.required_until,
        )
        write_request = self._public_api.write_call_request_builder().build(
            intent=request.intent,
            context=request.context,
            contract_evidence=request.contract_evidence,
            reservation=reservation,
            approval_request_id=request.approval_request_id,
            invocation_id=request.invocation_id,
            business_preconditions=request.business_preconditions,
            trace_refs=request.trace_refs,
        )
        outcome = await self._public_api.write_execution_coordinator(
            self._write_port,
            self._write_evidence_port,
        ).execute(
            request=write_request,
            decision=decision,
            context=request.context,
            requested_at=request.requested_at,
        )
        allowed_outcomes = (
            self._public_api.write_committed,
            self._public_api.write_not_committed,
            self._public_api.write_commit_unknown,
        )
        if not isinstance(outcome, allowed_outcomes):
            raise _invalid("NSL WRITE execution returned an invalid outcome.")

        verification = None
        if isinstance(outcome, self._public_api.write_committed):
            verification = await self._public_api.post_write_verifier().verify(
                outcome.result,
                request.contract,
                request.context,
                self._verification_port,
            )
            if not isinstance(verification, self._public_api.verification_result):
                raise _invalid("NSL post-WRITE verification result is invalid.")
        return NslControlledWriteResult(
            decision=decision,
            reservation=reservation,
            write_request=write_request,
            outcome=outcome,
            verification=verification,
        )


def _required_text(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise _invalid(f"{field} must be a bounded non-empty string.")
    return value


def _utc(field: str, value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise _invalid(f"{field} must use timezone-aware UTC.")
    return value


def _invalid(detail: str) -> NslControlledWriteIntegrationError:
    return NslControlledWriteIntegrationError(
        "ae.nsl_controlled_write_integration_invalid",
        detail,
    )
