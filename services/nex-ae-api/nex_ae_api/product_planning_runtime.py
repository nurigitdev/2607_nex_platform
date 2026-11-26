from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.agent_context import SqlAlchemyAgentContextRepository
from nex_ae_api.agent_execution import SqlAlchemyAgentExecutionRepository
from nex_ae_api.agent_runtime_worker import AgentRuntimeAssignment
from nex_ae_api.planning_capabilities import SqlAlchemyCapabilitySnapshotRepository
from nex_ae_api.product_planning_coordinators import (
    ProductPlanningCoordinatorRegistration,
    ProductPlanningCoordinatorRegistry,
)
from nex_ae_api.product_planning_proposals import (
    validate_product_planning_proposal,
)
from nex_ae_api.product_preparation_persistence import (
    SqlAlchemyGeneralizedWaitEventRepository,
    SqlAlchemyProductPreparationCheckpointRepository,
)
from nex_ae_api.runtime_resume import ResumeRoute, SqlAlchemyResumeRouteSource
from nex_ae_api.work_intent import SqlAlchemyWorkIntentRepository

PRODUCT_PLANNING_ADMISSION_SCHEMA_VERSION = "ae.product_planning_admission.v1"
PRODUCT_COORDINATOR_ASSIGNMENT_SCHEMA_VERSION = "ae.product_coordinator_assignment.v1"
PRODUCT_COORDINATOR_RETRY_DELAY_SECONDS = 5
PRODUCT_COORDINATOR_MAX_ATTEMPTS = 3
PRODUCT_PLANNING_SOURCE_TYPES = frozenset({"CLAIMED_WORKITEM", "IA_PROMPT"})
_PRODUCT_ERROR_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")


@dataclass
class ProductPlanningRuntimeError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class ProductCoordinator(Protocol):
    registration: ProductPlanningCoordinatorRegistration

    def begin(self, **values: Any) -> Mapping[str, Any]: ...

    def accept_approval_notification(self, **values: Any) -> Mapping[str, Any]: ...

    def resume_approval(self, **values: Any) -> Mapping[str, Any]: ...


class ProductPlanActivation(Protocol):
    registration: ProductPlanningCoordinatorRegistration

    def activate(self, **values: Any) -> Mapping[str, Any]: ...


class ProductRuntimeJobSettlement(Protocol):
    def complete(self, **values: Any) -> Mapping[str, Any]: ...

    def fail(self, **values: Any) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class InstalledProductCoordinatorRuntime:
    """One coordinator implementation and its existing plan activation path."""

    registration: ProductPlanningCoordinatorRegistration
    coordinator: ProductCoordinator
    activation: ProductPlanActivation
    planning_source_types: tuple[str, ...] = ("CLAIMED_WORKITEM",)

    def __post_init__(self) -> None:
        source_types = tuple(self.planning_source_types)
        if (
            getattr(self.coordinator, "registration", None) != self.registration
            or getattr(self.activation, "registration", None) != self.registration
            or not callable(getattr(self.coordinator, "begin", None))
            or not callable(
                getattr(self.coordinator, "accept_approval_notification", None)
            )
            or not callable(getattr(self.coordinator, "resume_approval", None))
            or not callable(getattr(self.activation, "activate", None))
        ):
            raise _invalid("Product coordinator runtime dependencies differ.")
        if (
            not source_types
            or len(set(source_types)) != len(source_types)
            or any(item not in PRODUCT_PLANNING_SOURCE_TYPES for item in source_types)
        ):
            raise _invalid("Product coordinator planning source types are invalid.")
        object.__setattr__(self, "planning_source_types", tuple(sorted(source_types)))

    @property
    def identity(self) -> tuple[str, str]:
        return (
            self.registration.coordinator_id,
            self.registration.coordinator_version,
        )


class InstalledProductCoordinatorRuntimeRegistry:
    """Exact runtime implementations for active immutable registrations."""

    def __init__(
        self,
        coordinator_registry: ProductPlanningCoordinatorRegistry,
        runtimes: Sequence[InstalledProductCoordinatorRuntime] = (),
    ) -> None:
        normalized = tuple(runtimes)
        identities = [runtime.identity for runtime in normalized]
        if len(set(identities)) != len(identities):
            raise _invalid("Product coordinator runtime identities are duplicated.")
        by_identity = {runtime.identity: runtime for runtime in normalized}
        for registration in coordinator_registry.registrations:
            runtime = by_identity.get(
                (registration.coordinator_id, registration.coordinator_version)
            )
            if registration.activation_status == "ACTIVE":
                if runtime is None or runtime.registration != registration:
                    raise _invalid(
                        "Every active Product coordinator requires one exact runtime."
                    )
            elif runtime is not None:
                raise _invalid(
                    "A contract-only Product coordinator cannot install a runtime."
                )
        self._runtimes = MappingProxyType(by_identity)

    @property
    def identities(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self._runtimes))

    def resolve_registration(
        self, registration: ProductPlanningCoordinatorRegistration
    ) -> InstalledProductCoordinatorRuntime:
        runtime = self._runtimes.get(
            (registration.coordinator_id, registration.coordinator_version)
        )
        if runtime is None or runtime.registration != registration:
            raise _unavailable("Product coordinator runtime is not installed.")
        return runtime

    def resolve_identity(
        self,
        *,
        coordinator_id: str,
        coordinator_version: str,
        coordinator_registration_hash: str,
    ) -> InstalledProductCoordinatorRuntime:
        runtime = self._runtimes.get(
            (
                _text(coordinator_id, "coordinator_id"),
                _text(coordinator_version, "coordinator_version"),
            )
        )
        if runtime is None:
            raise _unavailable("Product coordinator runtime is not installed.")
        if runtime.registration.registration_hash != coordinator_registration_hash:
            raise _conflict("Product coordinator registration has drifted.")
        return runtime

    def resolve_route(self, route: ResumeRoute) -> InstalledProductCoordinatorRuntime:
        context = route.product_context
        if route.resume_target_kind != "PRODUCT_COORDINATOR" or context is None:
            raise _invalid("Runtime assignment is not a Product coordinator resume.")
        identity = (
            _text(context.get("coordinator_id"), "coordinator_id"),
            _text(context.get("coordinator_version"), "coordinator_version"),
        )
        runtime = self._runtimes.get(identity)
        if runtime is None:
            raise _unavailable("Product coordinator runtime is not installed.")
        if context.get("coordinator_registration_hash") != (
            runtime.registration.registration_hash
        ):
            raise _conflict("Product coordinator resume registration has drifted.")
        return runtime


@dataclass(frozen=True)
class PublicProductPlanningRouter:
    """Select Product preparation by exact capability, never by scenario data."""

    coordinator_registry: ProductPlanningCoordinatorRegistry
    runtimes: InstalledProductCoordinatorRuntimeRegistry

    def begin_if_registered(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
        planning_source_type: str = "CLAIMED_WORKITEM",
        planning_proposal: Mapping[str, Any] | None = None,
        planning_fallback_ref: str | None = None,
    ) -> dict[str, Any] | None:
        registration = self.resolve_registration(
            work_intent=work_intent,
            capability_snapshot=capability_snapshot,
            planning_source_type=planning_source_type,
        )
        if registration is None:
            return None
        runtime = self.runtimes.resolve_registration(registration)
        proposal = _proposal_for_registration(
            planning_proposal,
            registration=registration,
            work_intent=work_intent,
            agent_context=agent_context,
        )
        fallback_ref = _fallback_for_registration(
            planning_fallback_ref,
            registration=registration,
            proposal=proposal,
        )
        result = _invoke_product_boundary(
            runtime.coordinator.begin,
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            execution=execution,
            planning_proposal=proposal,
            planning_fallback_ref=fallback_ref,
        )
        if result.get("ready"):
            _invoke_product_boundary(
                runtime.activation.activate,
                work_intent=work_intent,
                agent_context=agent_context,
                capability_snapshot=capability_snapshot,
                execution=execution,
            )
        return _admission_projection(
            result,
            registration=registration,
            planning_proposal_hash=(
                None if proposal is None else proposal["proposal_hash"]
            ),
            planning_fallback_ref=fallback_ref,
        )

    def replay_if_registered(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
        planning_source_type: str = "CLAIMED_WORKITEM",
    ) -> dict[str, Any] | None:
        registration = self.resolve_registration(
            work_intent=work_intent,
            capability_snapshot=capability_snapshot,
            planning_source_type=planning_source_type,
        )
        if registration is None:
            return None
        runtime = self.runtimes.resolve_registration(registration)
        replay = getattr(runtime.coordinator, "replay_begin", None)
        if replay is None:
            return None
        result = _call_product_boundary(
            replay,
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            execution=execution,
        )
        if result is None:
            return None
        if result.get("ready"):
            _invoke_product_boundary(
                runtime.activation.activate,
                work_intent=work_intent,
                agent_context=agent_context,
                capability_snapshot=capability_snapshot,
                execution=execution,
            )
        proposal_ref = result.get("planning_proposal_ref")
        return _admission_projection(
            result,
            registration=registration,
            planning_proposal_hash=(
                proposal_ref.get("proposal_hash")
                if isinstance(proposal_ref, Mapping)
                else None
            ),
            planning_fallback_ref=result.get("planning_fallback_ref"),
        )

    def resolve_registration(
        self,
        *,
        work_intent: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        planning_source_type: str = "CLAIMED_WORKITEM",
    ) -> ProductPlanningCoordinatorRegistration | None:
        if planning_source_type not in PRODUCT_PLANNING_SOURCE_TYPES:
            raise _invalid("Product planning source type is invalid.")
        registrations = self._matching_registrations(
            work_intent=work_intent,
            capability_snapshot=capability_snapshot,
        )
        if not registrations:
            return None
        if len(registrations) != 1:
            raise _conflict(
                "WorkIntent resolves to multiple Product coordinator registrations."
            )
        registration = registrations[0]
        if registration.activation_status != "ACTIVE":
            if planning_source_type != "CLAIMED_WORKITEM":
                return None
            raise _unavailable("Product planning coordinator is not active.")
        runtime = self.runtimes.resolve_registration(registration)
        if planning_source_type not in runtime.planning_source_types:
            return None
        return registration

    def _matching_registrations(
        self,
        *,
        work_intent: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
    ) -> tuple[ProductPlanningCoordinatorRegistration, ...]:
        hints = work_intent.get("required_capability_hints")
        capabilities = capability_snapshot.get("capabilities")
        if not isinstance(hints, list) or not isinstance(capabilities, list):
            raise _invalid("Product planning capability inputs are invalid.")
        versions = {
            str(item.get("capability_id")): str(item.get("capability_version"))
            for item in capabilities
            if isinstance(item, Mapping)
            and item.get("capability_id")
            and item.get("capability_version")
        }
        matches: list[ProductPlanningCoordinatorRegistration] = []
        for capability_id in hints:
            version = versions.get(str(capability_id))
            if version is None:
                continue
            registration = self.coordinator_registry.resolve(
                str(capability_id), version, required=False
            )
            if registration is not None and registration not in matches:
                matches.append(registration)
        return tuple(matches)


def _admission_projection(
    result: Mapping[str, Any],
    *,
    registration: ProductPlanningCoordinatorRegistration,
    planning_proposal_hash: str | None,
    planning_fallback_ref: str | None,
) -> dict[str, Any]:
    checkpoint = _mapping(result.get("checkpoint"), "Product checkpoint")
    projection = {
        "schema_version": PRODUCT_PLANNING_ADMISSION_SCHEMA_VERSION,
        "coordinator_id": registration.coordinator_id,
        "coordinator_version": registration.coordinator_version,
        "coordinator_registration_hash": registration.registration_hash,
        "capability_id": registration.capability_id,
        "capability_version": registration.capability_version,
        "checkpoint_id": checkpoint.get("checkpoint_id"),
        "checkpoint_hash": checkpoint.get("checkpoint_hash"),
        "stage": checkpoint.get("stage"),
        "ready": bool(result.get("ready")),
        "replayed": bool(result.get("replayed")),
        "provider_plan_authoritative": False,
        "planning_mode": registration.planning_policy.mode,
        "planning_proposal_hash": planning_proposal_hash,
        "planning_fallback_ref": planning_fallback_ref,
        "content_included": False,
    }
    projection["admission_hash"] = semantic_sha256_hash_ref(projection)
    return projection


class SqlAlchemyProductPlanningLineageSource:
    """Reload immutable Product inputs through their existing repositories."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._checkpoints = SqlAlchemyProductPreparationCheckpointRepository(sessions)
        self._work_intents = SqlAlchemyWorkIntentRepository(sessions)
        self._contexts = SqlAlchemyAgentContextRepository(sessions)
        self._capabilities = SqlAlchemyCapabilitySnapshotRepository(sessions)
        self._executions = SqlAlchemyAgentExecutionRepository(sessions)

    def load(self, route: ResumeRoute) -> dict[str, Mapping[str, Any]]:
        context = route.product_context
        if context is None:
            raise _invalid("Product resume binding is unavailable.")
        checkpoint = self._checkpoints.get(
            tenant_id=route.tenant_id,
            checkpoint_id=_text(context.get("checkpoint_id"), "checkpoint_id"),
        )
        if checkpoint is None:
            raise _conflict("Product checkpoint was not found.")
        if (
            checkpoint.get("checkpoint_hash") != context.get("checkpoint_hash")
            or checkpoint.get("agent_execution_id") != route.execution_id
            or checkpoint.get("work_intent_id") != context.get("work_intent_id")
        ):
            raise _conflict("Product resume checkpoint lineage differs.")
        work_intent = self._work_intents.get(
            tenant_id=route.tenant_id,
            work_intent_id=str(checkpoint["work_intent_id"]),
        )
        agent_context = self._contexts.get(
            tenant_id=route.tenant_id,
            context_id=str(checkpoint["agent_context_id"]),
        )
        capability_snapshot = self._capabilities.get_latest(tenant_id=route.tenant_id)
        stored_execution = self._executions.get(route.tenant_id, route.execution_id)
        if any(
            item is None
            for item in (
                work_intent,
                agent_context,
                capability_snapshot,
                stored_execution,
            )
        ):
            raise _conflict("Product planning resume lineage is incomplete.")
        if (
            work_intent.get("intent_hash") != checkpoint.get("work_intent_hash")
            or agent_context.get("context_hash") != checkpoint.get("context_hash")
            or capability_snapshot.get("tenant_id") != route.tenant_id
        ):
            raise _conflict("Product planning resume authority has drifted.")
        return {
            "work_intent": work_intent,
            "agent_context": agent_context,
            "capability_snapshot": capability_snapshot,
            "execution": {
                **stored_execution,
                "execution_id": stored_execution["agent_execution_id"],
            },
        }

    def close_terminal_execution(
        self,
        *,
        route: ResumeRoute,
        execution: Mapping[str, Any],
        terminal_stage: str,
    ) -> dict[str, Any]:
        target_state = "CANCELLED" if "CANCEL" in terminal_stage.upper() else "FAILED"
        if execution.get("state") == target_state:
            return dict(execution)
        if execution.get("state") != "WAITING_APPROVAL":
            raise _conflict("Product terminal execution is not waiting for approval.")
        return self._executions.transition(
            tenant_id=route.tenant_id,
            agent_execution_id=route.execution_id,
            expected_version=int(execution["version"]),
            state=target_state,
            phase="PLAN_BUILD",
            updated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )


class InstalledProductCoordinatorAssignmentHandler:
    """Resume one durable Product wait and activate READY plans in-place."""

    def __init__(
        self,
        *,
        route_source: SqlAlchemyResumeRouteSource,
        lineage_source: SqlAlchemyProductPlanningLineageSource,
        runtimes: InstalledProductCoordinatorRuntimeRegistry,
        runtime_jobs: ProductRuntimeJobSettlement,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._routes = route_source
        self._lineage = lineage_source
        self._runtimes = runtimes
        if not callable(getattr(runtime_jobs, "complete", None)) or not callable(
            getattr(runtime_jobs, "fail", None)
        ):
            raise _invalid("Product RuntimeJob settlement authority is unavailable.")
        self._runtime_jobs = runtime_jobs
        self._clock = clock or (lambda: datetime.now(UTC))

    def __call__(self, assignment: AgentRuntimeAssignment) -> Mapping[str, Any]:
        if assignment.assignment_kind != "PRODUCT_COORDINATOR":
            raise _invalid("Product handler received another assignment kind.")
        try:
            result = self._execute(assignment)
        except Exception as exc:
            self._settle_failure(assignment, exc)
            raise
        settled = self._runtime_jobs.complete(
            tenant_id=assignment.tenant_id,
            runtime_job_id=assignment.runtime_job_id,
            worker_id=assignment.claim.job["lease_owner"],
            lease_token=assignment.claim.job["lease_token"],
            now=self._now(),
        )
        return {
            **result,
            "runtime_job_state": settled["state"],
            "runtime_job_attempt_no": settled["attempt_no"],
        }

    def _execute(self, assignment: AgentRuntimeAssignment) -> dict[str, Any]:
        route = self._routes.resolve(
            tenant_id=assignment.tenant_id,
            runtime_job_id=assignment.runtime_job_id,
        )
        runtime = self._runtimes.resolve_route(route)
        inputs = self._lineage.load(route)
        resumed = _invoke_product_boundary(
            runtime.coordinator.resume_approval,
            event_id=route.event_id,
            runtime_job_id=route.runtime_job_id,
            **inputs,
        )
        activation = (
            _invoke_product_boundary(runtime.activation.activate, **inputs)
            if resumed.get("ready")
            else None
        )
        checkpoint = _mapping(resumed.get("checkpoint"), "Product checkpoint")
        terminal_execution = (
            self._lineage.close_terminal_execution(
                route=route,
                execution=inputs["execution"],
                terminal_stage=_text(checkpoint.get("stage"), "terminal_stage"),
            )
            if resumed.get("terminal")
            else None
        )
        return {
            "schema_version": PRODUCT_COORDINATOR_ASSIGNMENT_SCHEMA_VERSION,
            "runtime_job_id": route.runtime_job_id,
            "coordinator_id": runtime.registration.coordinator_id,
            "coordinator_version": runtime.registration.coordinator_version,
            "checkpoint_id": checkpoint.get("checkpoint_id"),
            "checkpoint_hash": checkpoint.get("checkpoint_hash"),
            "stage": checkpoint.get("stage"),
            "ready": bool(resumed.get("ready")),
            "terminal": bool(resumed.get("terminal")),
            "terminal_execution_state": (
                None if terminal_execution is None else terminal_execution["state"]
            ),
            "replayed": bool(resumed.get("replayed")),
            "activation": None if activation is None else dict(activation),
            "content_included": False,
        }

    def _settle_failure(
        self, assignment: AgentRuntimeAssignment, error: Exception
    ) -> None:
        observed_at = self._clock().astimezone(UTC)
        retryable = bool(getattr(error, "retryable", False))
        error_code = _typed_product_error_code(error) or (
            "ae.product_coordinator_assignment_failed"
        )
        self._runtime_jobs.fail(
            tenant_id=assignment.tenant_id,
            runtime_job_id=assignment.runtime_job_id,
            worker_id=assignment.claim.job["lease_owner"],
            lease_token=assignment.claim.job["lease_token"],
            now=_datetime_timestamp(observed_at),
            error_ref=error_code,
            retry_at=(
                _datetime_timestamp(
                    observed_at
                    + timedelta(seconds=PRODUCT_COORDINATOR_RETRY_DELAY_SECONDS)
                )
                if retryable
                else None
            ),
            retry_disposition_ref=(
                "ae.product_coordinator.retryable" if retryable else None
            ),
            max_attempts=PRODUCT_COORDINATOR_MAX_ATTEMPTS,
        )

    def _now(self) -> str:
        return _datetime_timestamp(self._clock())


class InstalledProductPlanningEventAdmission:
    """Persist an owner notification and schedule its generalized resume job."""

    _REQUIRED_FIELDS = frozenset(
        {
            "tenant_id",
            "coordinator_id",
            "coordinator_version",
            "coordinator_registration_hash",
            "checkpoint_id",
            "event_id",
            "notification_ref",
            "authority_evidence_ref",
            "received_at",
        }
    )
    _OPTIONAL_FIELDS = frozenset({"authority_state"})

    def __init__(self, *, runtimes: Any, resume_service: Any) -> None:
        self._runtimes = runtimes
        self._resume = resume_service

    def ingest(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if (
            not isinstance(payload, Mapping)
            or not self._REQUIRED_FIELDS.issubset(payload)
            or not set(payload).issubset(self._REQUIRED_FIELDS | self._OPTIONAL_FIELDS)
        ):
            raise _invalid("Product planning event fields are invalid.")
        runtime = self._runtimes.resolve_identity(
            coordinator_id=payload["coordinator_id"],
            coordinator_version=payload["coordinator_version"],
            coordinator_registration_hash=payload["coordinator_registration_hash"],
        )
        tenant_id = _text(payload["tenant_id"], "tenant_id")
        event_id = _text(payload["event_id"], "event_id")
        accepted = _invoke_product_boundary(
            runtime.coordinator.accept_approval_notification,
            tenant_id=tenant_id,
            checkpoint_id=_text(payload["checkpoint_id"], "checkpoint_id"),
            event_id=event_id,
            notification_ref=_text(payload["notification_ref"], "notification_ref"),
            authority_evidence_ref=_text(
                payload["authority_evidence_ref"], "authority_evidence_ref"
            ),
            authority_state=_authority_state(
                payload.get("authority_state", "APPROVED")
            ),
            received_at=_text(payload["received_at"], "received_at"),
        )
        resumed = _invoke_product_boundary(
            self._resume.reconcile,
            tenant_id=tenant_id,
            event_id=event_id,
        )
        return {
            "schema_version": "ae.product_planning_event_receipt.v1",
            "tenant_id": tenant_id,
            "event_id": event_id,
            "coordinator_id": runtime.registration.coordinator_id,
            "coordinator_version": runtime.registration.coordinator_version,
            "event_state": resumed["event_state"],
            "wait_state": resumed["wait_state"],
            "authority_state": _authority_state(
                payload.get("authority_state", "APPROVED")
            ),
            "resume_runtime_job_id": resumed["resume_runtime_job_id"],
            "event_replayed": bool(accepted.get("replayed")),
            "content_included": False,
        }


class InstalledProductRequesterReviewAdmission:
    """Match an authoritative browser submission to an existing Product wait."""

    _KINDS = frozenset(
        {"REQUESTER_PROPOSAL_REVIEW", "REQUESTER_VOUCHER_REVIEW"}
    )

    def __init__(
        self,
        *,
        runtimes: InstalledProductCoordinatorRuntimeRegistry,
        wait_events: SqlAlchemyGeneralizedWaitEventRepository,
        resume_service: Any,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._runtimes = runtimes
        self._wait_events = wait_events
        self._resume = resume_service
        self._clock = clock or (lambda: datetime.now(UTC))

    def ingest(
        self,
        *,
        tenant_id: str,
        requester_ref: str,
        authority_kind: str,
        authority_ref: str,
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized_kind = _text(authority_kind, "authority_kind")
        if normalized_kind not in self._KINDS:
            raise _invalid("Requester review authority kind is invalid.")
        normalized_tenant = _text(tenant_id, "tenant_id")
        normalized_requester = _text(requester_ref, "requester_ref")
        normalized_ref = _text(authority_ref, "authority_ref")
        context = self._wait_events.resolve_product_wait_context(
            tenant_id=normalized_tenant,
            authority_kind=normalized_kind,
            authority_ref=normalized_ref,
        )
        if context is None:
            return {
                "schema_version": "ae.product_requester_review_receipt.v1",
                "matched": False,
                "tenant_id": normalized_tenant,
                "authority_kind": normalized_kind,
                "authority_ref": normalized_ref,
                "content_included": False,
            }
        checkpoint = context["checkpoint"]
        binding = context["product_binding"]
        if checkpoint.get("requester_ref") != normalized_requester:
            raise _conflict("Requester review owner differs from the Product wait.")
        runtime = self._runtimes.resolve_identity(
            coordinator_id=binding["coordinator_id"],
            coordinator_version=binding["coordinator_version"],
            coordinator_registration_hash=binding[
                "coordinator_registration_hash"
            ],
        )
        receipt_hash = semantic_sha256_hash_ref(
            {
                "schema_version": "ae.product_requester_review_identity.v1",
                "tenant_id": normalized_tenant,
                "requester_ref": normalized_requester,
                "authority_kind": normalized_kind,
                "authority_ref": normalized_ref,
                "receipt": dict(receipt),
            }
        )
        notification_ref = (
            f"product-review:{normalized_kind.lower()}:{receipt_hash}"
        )
        event_id = f"product-review:{receipt_hash.removeprefix('sha256:')}"
        received_at = _datetime_timestamp(self._clock())
        accepted = _invoke_product_boundary(
            runtime.coordinator.accept_approval_notification,
            tenant_id=normalized_tenant,
            checkpoint_id=checkpoint["checkpoint_id"],
            event_id=event_id,
            notification_ref=notification_ref,
            authority_evidence_ref=notification_ref,
            authority_state="APPROVED",
            received_at=received_at,
        )
        resumed = _invoke_product_boundary(
            self._resume.reconcile,
            tenant_id=normalized_tenant,
            event_id=event_id,
        )
        return {
            "schema_version": "ae.product_requester_review_receipt.v1",
            "matched": True,
            "tenant_id": normalized_tenant,
            "authority_kind": normalized_kind,
            "authority_ref": normalized_ref,
            "event_id": event_id,
            "event_state": resumed["event_state"],
            "wait_state": resumed["wait_state"],
            "resume_runtime_job_id": resumed["resume_runtime_job_id"],
            "event_replayed": bool(accepted.get("replayed")),
            "receipt_hash": receipt_hash,
            "content_included": False,
        }


@dataclass(frozen=True)
class InstalledProductPlanningComposition:
    coordinator_registry: ProductPlanningCoordinatorRegistry
    runtime_registry: InstalledProductCoordinatorRuntimeRegistry
    public_router: PublicProductPlanningRouter
    assignment_handler: InstalledProductCoordinatorAssignmentHandler | None
    event_admission: InstalledProductPlanningEventAdmission | None
    requester_review_admission: InstalledProductRequesterReviewAdmission | None


def build_installed_product_planning_composition(
    *,
    sessions: sessionmaker[Session],
    coordinator_registry: ProductPlanningCoordinatorRegistry,
    runtimes: Sequence[InstalledProductCoordinatorRuntime] = (),
) -> InstalledProductPlanningComposition:
    from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue

    runtime_registry = InstalledProductCoordinatorRuntimeRegistry(
        coordinator_registry, runtimes
    )
    router = PublicProductPlanningRouter(coordinator_registry, runtime_registry)
    runtime_jobs = SqlAlchemyRuntimeJobQueue(sessions)
    handler = (
        InstalledProductCoordinatorAssignmentHandler(
            route_source=SqlAlchemyResumeRouteSource(sessions),
            lineage_source=SqlAlchemyProductPlanningLineageSource(sessions),
            runtimes=runtime_registry,
            runtime_jobs=runtime_jobs,
        )
        if runtime_registry.identities
        else None
    )
    event_admission = None
    requester_review_admission = None
    if runtime_registry.identities:
        from nex_ae_api.runtime_resume import SqlAlchemyProductPreparationResumeService

        wait_events = SqlAlchemyGeneralizedWaitEventRepository(sessions)
        resume_service = SqlAlchemyProductPreparationResumeService(
            sessions,
            runtime_jobs=runtime_jobs,
        )
        event_admission = InstalledProductPlanningEventAdmission(
            runtimes=runtime_registry,
            resume_service=resume_service,
        )
        requester_review_admission = InstalledProductRequesterReviewAdmission(
            runtimes=runtime_registry,
            wait_events=wait_events,
            resume_service=resume_service,
        )
    return InstalledProductPlanningComposition(
        coordinator_registry=coordinator_registry,
        runtime_registry=runtime_registry,
        public_router=router,
        assignment_handler=handler,
        event_admission=event_admission,
        requester_review_admission=requester_review_admission,
    )


def build_installed_m1_product_coordinator_runtime(
    *,
    sessions: sessionmaker[Session],
    registration: ProductPlanningCoordinatorRegistration,
    transaction_preparation: Any,
    authority_source: Any,
    materializer: Any,
) -> InstalledProductCoordinatorRuntime:
    """Assemble M1 over existing Product, plan, execution, and job stores."""

    from nex_ae_api.agent_plans import SqlAlchemyAgentPlanRepository
    from nex_ae_api.executable_plans import SqlAlchemyExecutablePlanRepository
    from nex_ae_api.m1_plan_activation import InstalledM1PlanActivation
    from nex_ae_api.m1_product_preparation_coordinator import (
        InstalledM1ProductPlanningCoordinator,
    )
    from nex_ae_api.multi_step_engine import SqlAlchemyMultiStepEngine
    from nex_ae_api.plan_validation import SqlAlchemyPlanValidationRepository
    from nex_ae_api.product_preparation_persistence import (
        SqlAlchemyGeneralizedWaitEventRepository,
    )
    from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue

    coordinator = InstalledM1ProductPlanningCoordinator(
        registration=registration,
        transaction_preparation=transaction_preparation,
        authority_source=authority_source,
        checkpoints=SqlAlchemyProductPreparationCheckpointRepository(sessions),
        wait_events=SqlAlchemyGeneralizedWaitEventRepository(sessions),
    )
    jobs = SqlAlchemyRuntimeJobQueue(sessions)
    activation = InstalledM1PlanActivation(
        registration=registration,
        ready_checkpoints=coordinator,
        materializer=materializer,
        agent_plans=SqlAlchemyAgentPlanRepository(sessions),
        validations=SqlAlchemyPlanValidationRepository(sessions),
        executable_plans=SqlAlchemyExecutablePlanRepository(sessions),
        executions=SqlAlchemyAgentExecutionRepository(sessions),
        scheduler=SqlAlchemyMultiStepEngine(sessions, jobs),
    )
    return InstalledProductCoordinatorRuntime(
        registration=registration,
        coordinator=coordinator,
        activation=activation,
        planning_source_types=("CLAIMED_WORKITEM",),
    )


def build_installed_accounting_allocation_coordinator_runtime(
    *,
    sessions: sessionmaker[Session],
    registration: ProductPlanningCoordinatorRegistration,
    materializer: Any,
) -> InstalledProductCoordinatorRuntime:
    """Assemble allocation admission over the common Product and job stores."""

    from nex_ae_api.accounting_allocation_plan import (
        build_installed_accounting_allocation_plan_activation,
    )
    from nex_ae_api.accounting_allocation_product_coordinator import (
        InstalledAccountingAllocationProductCoordinator,
        InstalledAccountingAllocationProductPlanActivation,
    )

    coordinator = InstalledAccountingAllocationProductCoordinator(
        registration=registration,
        checkpoints=SqlAlchemyProductPreparationCheckpointRepository(sessions),
    )
    activation = InstalledAccountingAllocationProductPlanActivation(
        registration=registration,
        activation=build_installed_accounting_allocation_plan_activation(
            sessions,
            materializer=materializer,
        ),
    )
    return InstalledProductCoordinatorRuntime(
        registration=registration,
        coordinator=coordinator,
        activation=activation,
        planning_source_types=("IA_PROMPT",),
    )


def build_contract_m1_product_planning_composition(
    *,
    sessions: sessionmaker[Session],
    product_capabilities: Any,
) -> InstalledProductPlanningComposition:
    """Build the shared contract-only API/worker view before activation lock."""

    from mybee_ax.orchestration import load_m1_transaction_preparation_registration

    from nex_ae_api.m1_product_planning_coordinator import (
        build_m1_product_planning_coordinator_registry,
    )

    registry = build_m1_product_planning_coordinator_registry(
        product_capabilities=product_capabilities,
        preparation_registration=load_m1_transaction_preparation_registration(),
    )
    return build_installed_product_planning_composition(
        sessions=sessions,
        coordinator_registry=registry,
    )


def _proposal_for_registration(
    value: Mapping[str, Any] | None,
    *,
    registration: ProductPlanningCoordinatorRegistration,
    work_intent: Mapping[str, Any],
    agent_context: Mapping[str, Any],
) -> dict[str, Any] | None:
    mode = registration.planning_policy.mode
    if value is None:
        if mode == "PROVIDER_ASSISTED_REQUIRED":
            raise _unavailable("Product planning proposal is required but unavailable.")
        return None
    if mode == "DETERMINISTIC_ONLY":
        raise _invalid("Deterministic-only Product planning rejects a proposal.")
    try:
        proposal = validate_product_planning_proposal(value)
    except ValueError as exc:
        raise _conflict("Product planning proposal is invalid or drifted.") from exc
    coordinator = proposal["coordinator_ref"]
    work_ref = proposal["work_intent_ref"]
    context_ref = proposal["agent_context_ref"]
    if (
        coordinator.get("coordinator_id") != registration.coordinator_id
        or coordinator.get("coordinator_version") != registration.coordinator_version
        or coordinator.get("coordinator_registration_hash")
        != registration.registration_hash
        or proposal.get("planning_policy") != registration.planning_policy.projection()
        or work_ref.get("work_intent_id") != work_intent.get("work_intent_id")
        or work_ref.get("intent_hash") != work_intent.get("intent_hash")
        or context_ref.get("context_id") != agent_context.get("context_id")
        or context_ref.get("context_hash") != agent_context.get("context_hash")
    ):
        raise _conflict("Product planning proposal lineage has drifted.")
    return proposal


def _fallback_for_registration(
    value: str | None,
    *,
    registration: ProductPlanningCoordinatorRegistration,
    proposal: Mapping[str, Any] | None,
) -> str | None:
    policy = registration.planning_policy
    if policy.mode != "PROVIDER_ASSISTED_OPTIONAL":
        if value is not None:
            raise _invalid("Product planning fallback is not admitted.")
        return None
    if proposal is not None:
        if value is not None:
            raise _invalid("Product planning selection is ambiguous.")
        return None
    if value != policy.deterministic_fallback_ref:
        raise _unavailable("Product planning fallback is unavailable or drifted.")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{label} is unavailable.")
    return value


def _invoke_product_boundary(operation: Any, **values: Any) -> Mapping[str, Any]:
    return _mapping(
        _call_product_boundary(operation, **values),
        "Product runtime result",
    )


def _call_product_boundary(operation: Any, **values: Any) -> Any:
    try:
        return operation(**values)
    except ProductPlanningRuntimeError:
        raise
    except Exception as exc:
        error_code = _typed_product_error_code(exc)
        detail = getattr(exc, "detail", None)
        if error_code is not None and isinstance(detail, str):
            raise ProductPlanningRuntimeError(
                error_code=error_code,
                detail=detail,
                retryable=bool(getattr(exc, "retryable", False)),
            ) from exc
        raise


def _typed_product_error_code(error: object) -> str | None:
    for attribute in ("error_code", "code"):
        value = getattr(error, attribute, None)
        if isinstance(value, str):
            candidate = value.strip()
            if _PRODUCT_ERROR_CODE.fullmatch(candidate):
                return candidate
    return None


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} is required.")
    return value.strip()


def _datetime_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid("Product RuntimeJob settlement clock must be timezone-aware.")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _authority_state(value: object) -> str:
    admitted = _text(value, "authority_state")
    if admitted not in {"APPROVED", "REJECTED"}:
        raise _invalid("Product authority state is invalid.")
    return admitted


def _invalid(detail: str) -> ProductPlanningRuntimeError:
    return ProductPlanningRuntimeError("ae.product_planning_runtime_invalid", detail)


def _conflict(detail: str) -> ProductPlanningRuntimeError:
    return ProductPlanningRuntimeError("ae.product_planning_runtime_conflict", detail)


def _unavailable(detail: str) -> ProductPlanningRuntimeError:
    return ProductPlanningRuntimeError(
        "ae.product_planning_runtime_unavailable", detail, True
    )


__all__ = [
    "PRODUCT_COORDINATOR_ASSIGNMENT_SCHEMA_VERSION",
    "PRODUCT_PLANNING_ADMISSION_SCHEMA_VERSION",
    "InstalledProductCoordinatorAssignmentHandler",
    "InstalledProductCoordinatorRuntime",
    "InstalledProductCoordinatorRuntimeRegistry",
    "InstalledProductPlanningComposition",
    "InstalledProductPlanningEventAdmission",
    "InstalledProductRequesterReviewAdmission",
    "ProductPlanningRuntimeError",
    "PublicProductPlanningRouter",
    "SqlAlchemyProductPlanningLineageSource",
    "build_contract_m1_product_planning_composition",
    "build_installed_accounting_allocation_coordinator_runtime",
    "build_installed_m1_product_coordinator_runtime",
    "build_installed_product_planning_composition",
]
