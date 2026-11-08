from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .dependency_readiness import (
    DependencyReadinessRequirement,
    PlatformDependencyReadiness,
    normalize_dependency_readiness,
)
from .openbao_secret_resolver import build_openbao_secret_resolver
from .production_secret_materialization import (
    ResolvedSecret,
    SecretReferenceResolver,
    SecretResolutionContext,
)
from .s143_staging import (
    OpenBaoAdminClient,
    configure_openbao_staging,
    initialize_openbao,
)
from .s144_staging import (
    configure_openbao_s144_trust,
    refresh_openbao_s144_transit_credentials,
)

OPENBAO_PROVISIONING_SCHEMA_VERSION = "openbao_provisioning.v1"
OPENBAO_RUNTIME_RESOLUTION_SCHEMA_VERSION = "openbao_runtime_resolution.v1"
OPENBAO_DEPENDENCY_ID = "openbao"
OPENBAO_DEPENDENCY_OWNER = "deployment"
_OWNER = re.compile(r"^nex-(?:oa|ae-api|cx|mo|ag|wc|eos)$")
_TARGET = re.compile(r"^NEX_[A-Z0-9_]+$")
_VERSION = re.compile(r"^v[1-9][0-9]*$")
_GENERATION = re.compile(r"^secret:[A-Za-z0-9._:-]{1,127}$")


class OpenBaoProvisioningError(ValueError):
    pass


class OpenBaoSecretBinding(Protocol):
    owner: str
    target_environment_name: str


class OpenBaoRuntimeResolver(SecretReferenceResolver, Protocol):
    def revoke(self) -> None: ...


ResolverFactory = Callable[[Mapping[str, str]], OpenBaoRuntimeResolver]
Sleep = Callable[[float], None]


@dataclass(frozen=True)
class OpenBaoProvisioningSession:
    owners: tuple[str, ...]
    secret_count: int
    secret_versions: tuple[int, ...]
    trust_configured: bool
    checked_at: str
    root_token: str = field(repr=False)
    unseal_key: str = field(repr=False)

    def provisioning_readiness(self) -> PlatformDependencyReadiness:
        return _readiness(authorized=False, checked_at=self.checked_at)

    def to_projection(self) -> dict[str, Any]:
        return {
            "schema_version": OPENBAO_PROVISIONING_SCHEMA_VERSION,
            "status": "PROVISIONED",
            "owner_count": len(self.owners),
            "secret_count": self.secret_count,
            "secret_versions": list(self.secret_versions),
            "trust_configured": self.trust_configured,
            "runtime_authorization_verified": False,
            "dependency_readiness": self.provisioning_readiness().to_projection(),
            "raw_secret_values_included": False,
        }


def provision_openbao_environment(
    client: OpenBaoAdminClient,
    *,
    root: Path,
    runtime_dir: Path,
    secret_values: Mapping[str, str],
    bindings: Sequence[OpenBaoSecretBinding],
    owners: Sequence[str],
    subject_alt_names: Sequence[str],
    configure_trust: bool = False,
    checked_at: str | None = None,
) -> OpenBaoProvisioningSession:
    """Provision OpenBao without claiming runtime secret authorization."""

    admitted_owners = _validate_inventory(bindings, owners)
    timestamp = _checked_at(checked_at)
    bootstrap = initialize_openbao(client, runtime_dir)
    configured = configure_openbao_staging(
        client,
        root_token=bootstrap.root_token,
        root=root,
        runtime_dir=runtime_dir,
        secret_values=secret_values,
        bindings=tuple(bindings),
        owners=admitted_owners,
        subject_alt_names=tuple(subject_alt_names),
    )
    if configure_trust:
        configure_openbao_s144_trust(client, root_token=bootstrap.root_token)
        refresh_openbao_s144_transit_credentials(
            client,
            root_token=bootstrap.root_token,
            runtime_dir=runtime_dir,
        )
    return OpenBaoProvisioningSession(
        owners=admitted_owners,
        secret_count=_positive_int(configured.get("secret_count"), "secret_count"),
        secret_versions=_versions(configured.get("secret_versions")),
        trust_configured=configure_trust,
        checked_at=timestamp,
        root_token=bootstrap.root_token,
        unseal_key=bootstrap.unseal_key,
    )


def verify_openbao_runtime_resolution(
    session: OpenBaoProvisioningSession,
    *,
    resolver_environments: Mapping[str, Mapping[str, str]],
    bindings: Sequence[OpenBaoSecretBinding],
    namespace: str,
    reference_version: str,
    secret_generation: str,
    checked_at: str | None = None,
    resolver_factory: ResolverFactory = build_openbao_secret_resolver,
) -> dict[str, Any]:
    """Authenticate each owner independently and emit only redacted evidence."""

    owners = _validate_inventory(bindings, session.owners)
    if set(resolver_environments) != set(owners):
        raise OpenBaoProvisioningError(
            "OpenBao runtime resolver owner coverage is invalid"
        )
    if namespace not in {"staging", "production"}:
        raise OpenBaoProvisioningError("OpenBao runtime namespace is invalid")
    if not isinstance(reference_version, str) or not _VERSION.fullmatch(
        reference_version
    ):
        raise OpenBaoProvisioningError("OpenBao runtime reference version is invalid")
    if not isinstance(secret_generation, str) or not _GENERATION.fullmatch(
        secret_generation
    ):
        raise OpenBaoProvisioningError("OpenBao runtime secret generation is invalid")

    representative = _representative_bindings(bindings, owners)
    resolved_owners: list[str] = []
    for owner in owners:
        binding = representative[owner]
        resolver: OpenBaoRuntimeResolver | None = None
        try:
            resolver = resolver_factory(dict(resolver_environments[owner]))
            context = SecretResolutionContext(
                owner=owner,
                target_environment_name=binding.target_environment_name,
                secret_generation=secret_generation,
                reference_version=reference_version,
            )
            secret = resolver.resolve(
                _reference(
                    namespace,
                    owner,
                    binding.target_environment_name,
                    reference_version,
                ),
                context=context,
            )
            _validate_resolved_secret(secret, context=context)
            resolved_owners.append(owner)
        except Exception:  # noqa: BLE001 - sanitize all provider failures here
            raise OpenBaoProvisioningError(
                f"OpenBao runtime resolution failed for owner: {owner}"
            ) from None
        finally:
            if resolver is not None:
                try:
                    resolver.revoke()
                except Exception:  # noqa: BLE001 - sanitize all provider failures here
                    raise OpenBaoProvisioningError(
                        f"OpenBao runtime token revocation failed for owner: {owner}"
                    ) from None

    readiness = _readiness(authorized=True, checked_at=_checked_at(checked_at))
    return {
        "schema_version": OPENBAO_RUNTIME_RESOLUTION_SCHEMA_VERSION,
        "status": "READY",
        "owner_count": len(owners),
        "resolved_owner_count": len(resolved_owners),
        "reference_version": reference_version,
        "fresh_authentication_per_owner": True,
        "resolver_tokens_revoked": True,
        "dependency_readiness": readiness.to_projection(),
        "raw_secret_values_included": False,
    }


def reactivate_openbao_after_restart(
    client: OpenBaoAdminClient,
    session: OpenBaoProvisioningSession,
    *,
    attempts: int = 50,
    interval_seconds: float = 0.1,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    """Unseal a provisioned node after process restart without exposing custody."""

    if attempts <= 0 or interval_seconds < 0:
        raise OpenBaoProvisioningError("OpenBao restart recovery policy is invalid")
    for attempt in range(1, attempts + 1):
        try:
            status = client.request("GET", "/v1/sys/seal-status")
            if status.get("initialized") is not True:
                raise OpenBaoProvisioningError(
                    "OpenBao restart target is not initialized"
                )
            if status.get("sealed") is True:
                client.request(
                    "PUT",
                    "/v1/sys/unseal",
                    payload={"key": session.unseal_key},
                )
            leader = client.request(
                "GET", "/v1/sys/leader", token=session.root_token
            )
            if leader.get("ha_enabled") is True and leader.get("is_self") is True:
                return {
                    "schema_version": OPENBAO_PROVISIONING_SCHEMA_VERSION,
                    "status": "REACTIVATED",
                    "attempts": attempt,
                    "custody_material_included": False,
                }
        except OpenBaoProvisioningError:
            raise
        except Exception:  # noqa: BLE001, S110 - retry without private details
            pass
        if attempt < attempts:
            sleep(interval_seconds)
    raise OpenBaoProvisioningError("OpenBao restart recovery did not become ready")


def _validate_inventory(
    bindings: Sequence[OpenBaoSecretBinding], owners: Sequence[str]
) -> tuple[str, ...]:
    owner_tuple = tuple(owners)
    if (
        not owner_tuple
        or len(owner_tuple) != len(set(owner_tuple))
        or any(not isinstance(owner, str) or not _OWNER.fullmatch(owner) for owner in owner_tuple)
    ):
        raise OpenBaoProvisioningError("OpenBao owner inventory is invalid")
    binding_tuple = tuple(bindings)
    if not binding_tuple:
        raise OpenBaoProvisioningError("OpenBao binding inventory is empty")
    try:
        binding_owners = {binding.owner for binding in binding_tuple}
        invalid_target = any(
            not _TARGET.fullmatch(binding.target_environment_name)
            for binding in binding_tuple
        )
    except (AttributeError, TypeError):
        raise OpenBaoProvisioningError("OpenBao binding inventory is invalid") from None
    if binding_owners != set(owner_tuple) or invalid_target:
        raise OpenBaoProvisioningError("OpenBao binding inventory is invalid")
    return owner_tuple


def _representative_bindings(
    bindings: Sequence[OpenBaoSecretBinding], owners: Sequence[str]
) -> dict[str, OpenBaoSecretBinding]:
    selected: dict[str, OpenBaoSecretBinding] = {}
    for binding in sorted(
        bindings, key=lambda item: (item.owner, item.target_environment_name)
    ):
        selected.setdefault(binding.owner, binding)
    if set(selected) != set(owners):
        raise OpenBaoProvisioningError("OpenBao binding owner coverage is invalid")
    return selected


def _validate_resolved_secret(
    secret: ResolvedSecret, *, context: SecretResolutionContext
) -> None:
    if (
        not isinstance(secret, ResolvedSecret)
        or secret.owner != context.owner
        or secret.target_environment_name != context.target_environment_name
        or secret.secret_generation != context.secret_generation
        or secret.reference_version != context.reference_version
        or secret.provider_id != "openbao"
        or not secret.value
    ):
        raise OpenBaoProvisioningError("OpenBao runtime resolution metadata mismatch")


def _reference(namespace: str, owner: str, target: str, version: str) -> str:
    return f"secret://openbao/nex-platform/{namespace}/{owner}/{target}@{version}"


def _readiness(*, authorized: bool, checked_at: str) -> PlatformDependencyReadiness:
    return normalize_dependency_readiness(
        DependencyReadinessRequirement(
            dependency_id=OPENBAO_DEPENDENCY_ID,
            dependency_type="OPENBAO",
            owner=OPENBAO_DEPENDENCY_OWNER,
            required=True,
        ),
        configured=True,
        provisioned=True,
        reachable=True,
        authorized=authorized,
        checked_at=checked_at,
    )


def _checked_at(value: str | None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise OpenBaoProvisioningError("OpenBao readiness timestamp is invalid") from None
    if parsed.tzinfo is None:
        raise OpenBaoProvisioningError("OpenBao readiness timestamp is invalid")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise OpenBaoProvisioningError(f"OpenBao {field_name} is invalid")
    return value


def _versions(value: Any) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise OpenBaoProvisioningError("OpenBao secret versions are invalid")
    versions = tuple(value)
    if not versions or any(
        not isinstance(item, int) or isinstance(item, bool) or item < 1
        for item in versions
    ):
        raise OpenBaoProvisioningError("OpenBao secret versions are invalid")
    return versions
