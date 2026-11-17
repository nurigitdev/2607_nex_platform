from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

PRODUCT_PLANNING_COORDINATOR_REGISTRY_SCHEMA_VERSION = (
    "ae.product_planning_coordinator_registry.v1"
)
PRODUCT_PLANNING_COORDINATOR_REGISTRATION_SCHEMA_VERSION = (
    "ae.product_planning_coordinator_registration.v1"
)
PRODUCT_COORDINATOR_ACTIVATION_STATUSES = frozenset({"CONTRACT_ONLY", "ACTIVE"})


@dataclass(frozen=True)
class ProductPlanningCoordinatorError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class ProductPlanningCapabilityBinding:
    capability_id: str
    capability_version: str
    capability_registration_hash: str

    def projection(self) -> dict[str, str]:
        return {
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
            "capability_registration_hash": self.capability_registration_hash,
        }


@dataclass(frozen=True)
class ProductPlanningCoordinatorRegistration:
    coordinator_id: str
    coordinator_version: str
    activation_status: str
    implementation_ref: str
    trigger_capability: ProductPlanningCapabilityBinding
    required_capabilities: tuple[ProductPlanningCapabilityBinding, ...]
    preparation_adapter_source_identity: str
    materializer_source_identity: str
    initial_state: str
    waiting_states: tuple[str, ...]
    ready_state: str
    terminal_states: tuple[str, ...]
    required_operations: tuple[str, ...]
    registration_hash: str

    @property
    def capability_id(self) -> str:
        return self.trigger_capability.capability_id

    @property
    def capability_version(self) -> str:
        return self.trigger_capability.capability_version

    def projection(self) -> dict[str, Any]:
        return {
            "schema_version": (
                PRODUCT_PLANNING_COORDINATOR_REGISTRATION_SCHEMA_VERSION
            ),
            "coordinator_id": self.coordinator_id,
            "coordinator_version": self.coordinator_version,
            "activation_status": self.activation_status,
            "implementation_ref": self.implementation_ref,
            "trigger_capability": self.trigger_capability.projection(),
            "required_capabilities": [
                item.projection() for item in self.required_capabilities
            ],
            "preparation_adapter_source_identity": (
                self.preparation_adapter_source_identity
            ),
            "materializer_source_identity": self.materializer_source_identity,
            "initial_state": self.initial_state,
            "waiting_states": list(self.waiting_states),
            "ready_state": self.ready_state,
            "terminal_states": list(self.terminal_states),
            "required_operations": list(self.required_operations),
            "registration_hash": self.registration_hash,
        }


class ProductPlanningCoordinator(Protocol):
    @property
    def registration(self) -> ProductPlanningCoordinatorRegistration: ...

    def begin(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    def resume(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
        checkpoint: Mapping[str, Any],
        authority_reference: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    def materialize(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        checkpoint: Mapping[str, Any],
    ) -> Any: ...


class ProductPlanningCoordinatorRegistry:
    """Immutable exact-capability registry for product planning coordinators."""

    def __init__(
        self,
        registrations: Sequence[ProductPlanningCoordinatorRegistration] = (),
        *,
        registry_id: str = "empty",
        registry_version: int = 0,
    ) -> None:
        normalized = tuple(registrations)
        if any(
            not isinstance(item, ProductPlanningCoordinatorRegistration)
            for item in normalized
        ):
            raise _invalid("Product coordinator registrations are invalid.")
        for item in normalized:
            projection = item.projection()
            supplied_hash = projection.pop("registration_hash")
            try:
                supplied_hash = validate_hash_ref(supplied_hash)
            except ValueError as exc:
                raise _invalid(
                    "Product coordinator registration hash is invalid."
                ) from exc
            if supplied_hash != semantic_sha256_hash_ref(projection):
                raise _invalid(
                    "Product coordinator registration hash does not match content."
                )
        identities = [
            (item.capability_id, item.capability_version) for item in normalized
        ]
        if len(set(identities)) != len(identities):
            raise _error(
                "PRODUCT_COORDINATOR_DUPLICATE",
                "Product coordinator capability bindings must be unique.",
            )
        coordinator_identities = [
            (item.coordinator_id, item.coordinator_version) for item in normalized
        ]
        if len(set(coordinator_identities)) != len(coordinator_identities):
            raise _error(
                "PRODUCT_COORDINATOR_IDENTITY_DUPLICATE",
                "Product coordinator identities must be unique.",
            )
        self.registry_id = _text(registry_id, "registry_id", 160)
        if (
            not isinstance(registry_version, int)
            or isinstance(registry_version, bool)
            or registry_version < 0
        ):
            raise _invalid("Product coordinator registry version is invalid.")
        if normalized and registry_version < 1:
            raise _invalid("A non-empty coordinator registry requires a version.")
        self.registry_version = registry_version
        self._registrations = tuple(
            sorted(
                normalized,
                key=lambda item: (item.capability_id, item.capability_version),
            )
        )
        self.registry_hash = semantic_sha256_hash_ref(
            {
                "schema_version": (
                    PRODUCT_PLANNING_COORDINATOR_REGISTRY_SCHEMA_VERSION
                ),
                "registry_id": self.registry_id,
                "registry_version": self.registry_version,
                "registrations": [
                    item.projection() for item in self._registrations
                ],
            }
        )

    @property
    def registrations(self) -> tuple[ProductPlanningCoordinatorRegistration, ...]:
        return self._registrations

    @property
    def source_identity(self) -> str:
        return (
            "nex-ae:product-planning-coordinator-registry:"
            f"{self.registry_id}:v{self.registry_version}:{self.registry_hash}"
        )

    def resolve(
        self,
        capability_id: str,
        capability_version: str,
        *,
        capability_registration_hash: str | None = None,
        require_active: bool = False,
        required: bool = False,
    ) -> ProductPlanningCoordinatorRegistration | None:
        normalized_id = _text(capability_id, "capability_id", 160)
        normalized_version = _text(
            capability_version, "capability_version", 64
        )
        match = next(
            (
                item
                for item in self._registrations
                if (
                    item.capability_id,
                    item.capability_version,
                )
                == (normalized_id, normalized_version)
            ),
            None,
        )
        if match is None:
            if required:
                raise _error(
                    "PRODUCT_COORDINATOR_REQUIRED",
                    "Required product planning coordinator is not registered.",
                )
            return None
        if capability_registration_hash is not None:
            try:
                expected_hash = validate_hash_ref(capability_registration_hash)
            except ValueError as exc:
                raise _invalid(
                    "Product capability registration hash is invalid."
                ) from exc
            if (
                match.trigger_capability.capability_registration_hash
                != expected_hash
            ):
                raise _error(
                    "PRODUCT_COORDINATOR_CAPABILITY_DRIFT",
                    "Product coordinator capability registration differs.",
                )
        if require_active and match.activation_status != "ACTIVE":
            raise _error(
                "PRODUCT_COORDINATOR_NOT_ACTIVE",
                "Product planning coordinator is not active.",
            )
        return match

    def require_product_capabilities(self, registry: Any) -> None:
        for coordinator in self._registrations:
            for binding in coordinator.required_capabilities:
                try:
                    observed = registry.resolve(binding.capability_id, required=True)
                except Exception as exc:
                    raise _error(
                        "PRODUCT_COORDINATOR_CAPABILITY_UNAVAILABLE",
                        "Required product coordinator capability is unavailable.",
                    ) from exc
                if (
                    observed.capability_version != binding.capability_version
                    or observed.registration_hash
                    != binding.capability_registration_hash
                ):
                    raise _error(
                        "PRODUCT_COORDINATOR_CAPABILITY_DRIFT",
                        "Required product coordinator capability differs.",
                    )


def build_product_planning_coordinator_registration(
    *,
    coordinator_id: str,
    coordinator_version: str,
    activation_status: str,
    implementation_ref: str,
    trigger_capability: ProductPlanningCapabilityBinding,
    required_capabilities: Sequence[ProductPlanningCapabilityBinding],
    preparation_adapter_source_identity: str,
    materializer_source_identity: str,
    initial_state: str,
    waiting_states: Sequence[str],
    ready_state: str,
    terminal_states: Sequence[str],
    required_operations: Sequence[str],
) -> ProductPlanningCoordinatorRegistration:
    if not isinstance(trigger_capability, ProductPlanningCapabilityBinding):
        raise _invalid("Product coordinator trigger capability is invalid.")
    required = tuple(required_capabilities)
    if (
        not 1 <= len(required) <= 16
        or any(
            not isinstance(item, ProductPlanningCapabilityBinding)
            for item in required
        )
    ):
        raise _invalid("Product coordinator required capabilities are invalid.")
    required = tuple(
        sorted(required, key=lambda item: (item.capability_id, item.capability_version))
    )
    required_identities = [
        (item.capability_id, item.capability_version) for item in required
    ]
    if (
        len(set(required_identities)) != len(required_identities)
        or (
            trigger_capability.capability_id,
            trigger_capability.capability_version,
        )
        not in required_identities
    ):
        raise _invalid(
            "Product coordinator capability bindings are inconsistent."
        )
    activation = _text(activation_status, "activation_status", 32)
    if activation not in PRODUCT_COORDINATOR_ACTIVATION_STATUSES:
        raise _invalid("Product coordinator activation status is invalid.")
    waiting = _states(waiting_states, "waiting_states")
    terminal = _states(terminal_states, "terminal_states")
    initial = _state(initial_state, "initial_state")
    ready = _state(ready_state, "ready_state")
    if len({initial, ready, *waiting, *terminal}) != (
        2 + len(waiting) + len(terminal)
    ):
        raise _invalid("Product coordinator states must be distinct.")
    operations = tuple(
        sorted(
            {
                _text(item, "required_operation", 160)
                for item in required_operations
            }
        )
    )
    if not operations:
        raise _invalid("Product coordinator operations are required.")
    projection = {
        "schema_version": (
            PRODUCT_PLANNING_COORDINATOR_REGISTRATION_SCHEMA_VERSION
        ),
        "coordinator_id": _text(coordinator_id, "coordinator_id", 160),
        "coordinator_version": _text(
            coordinator_version, "coordinator_version", 64
        ),
        "activation_status": activation,
        "implementation_ref": _text(
            implementation_ref, "implementation_ref", 512
        ),
        "trigger_capability": trigger_capability.projection(),
        "required_capabilities": [item.projection() for item in required],
        "preparation_adapter_source_identity": _text(
            preparation_adapter_source_identity,
            "preparation_adapter_source_identity",
            512,
        ),
        "materializer_source_identity": _text(
            materializer_source_identity,
            "materializer_source_identity",
            512,
        ),
        "initial_state": initial,
        "waiting_states": list(waiting),
        "ready_state": ready,
        "terminal_states": list(terminal),
        "required_operations": list(operations),
    }
    return ProductPlanningCoordinatorRegistration(
        coordinator_id=projection["coordinator_id"],
        coordinator_version=projection["coordinator_version"],
        activation_status=activation,
        implementation_ref=projection["implementation_ref"],
        trigger_capability=trigger_capability,
        required_capabilities=required,
        preparation_adapter_source_identity=projection[
            "preparation_adapter_source_identity"
        ],
        materializer_source_identity=projection["materializer_source_identity"],
        initial_state=initial,
        waiting_states=waiting,
        ready_state=ready,
        terminal_states=terminal,
        required_operations=operations,
        registration_hash=semantic_sha256_hash_ref(projection),
    )


def capability_binding(registration: Any) -> ProductPlanningCapabilityBinding:
    try:
        capability_id = registration.capability_id
        capability_version = registration.capability_version
        registration_hash = validate_hash_ref(registration.registration_hash)
    except (AttributeError, TypeError, ValueError) as exc:
        raise _invalid("Product capability registration is invalid.") from exc
    return ProductPlanningCapabilityBinding(
        capability_id=_text(capability_id, "capability_id", 160),
        capability_version=_text(
            capability_version, "capability_version", 64
        ),
        capability_registration_hash=registration_hash,
    )


def _states(values: Sequence[str], field: str) -> tuple[str, ...]:
    normalized = tuple(_state(item, field) for item in values)
    if not normalized or len(set(normalized)) != len(normalized):
        raise _invalid(f"Product coordinator {field} is invalid.")
    return normalized


def _state(value: object, field: str) -> str:
    normalized = _text(value, field, 64)
    if normalized != normalized.upper():
        raise _invalid(f"Product coordinator {field} must be uppercase.")
    return normalized


def _text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise _invalid(f"Product coordinator {field} is invalid.")
    return value


def _invalid(detail: str) -> ProductPlanningCoordinatorError:
    return _error("PRODUCT_COORDINATOR_REGISTRY_INVALID", detail)


def _error(error_code: str, detail: str) -> ProductPlanningCoordinatorError:
    return ProductPlanningCoordinatorError(error_code, detail)
