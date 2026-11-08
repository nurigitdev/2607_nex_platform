from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from nex_runtime.canonical_platform_trust import (
    CANONICAL_PLATFORM_OWNERS,
    CANONICAL_PLATFORM_TRUST_GRANTS,
    SERVICE_CLIENT_SECRET_ENV,
    SERVICE_CREDENTIAL_ID_ENV,
)

from .service_principal_service import OaServicePrincipalService
from .service_principals import OaServicePrincipalError

CANONICAL_PRINCIPAL_PROVISIONING_SCHEMA_VERSION = (
    "canonical_service_principal_provisioning.v1"
)
CANONICAL_SERVICE_CREDENTIAL_LIFETIME_DAYS = 7
_GENERATION = re.compile(r"^v[1-9][0-9]*$")


class CanonicalServicePrincipalProvisioningError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalServicePrincipalSpec:
    owner: str
    principal_id: str
    display_name: str
    allowed_audiences: tuple[str, ...]
    allowed_scopes: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalServiceCredentialMaterial:
    owner: str
    credential_id: str
    client_secret: str = field(repr=False)

    def openbao_values(self) -> dict[str, str]:
        return {
            SERVICE_CREDENTIAL_ID_ENV: self.credential_id,
            SERVICE_CLIENT_SECRET_ENV: self.client_secret,
        }


@dataclass(frozen=True)
class CanonicalServicePrincipalProvisioning:
    generation: str
    materials: tuple[CanonicalServiceCredentialMaterial, ...] = field(repr=False)
    created_principal_count: int = 0
    updated_principal_count: int = 0
    created_credential_count: int = 0
    reused_credential_count: int = 0

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": CANONICAL_PRINCIPAL_PROVISIONING_SCHEMA_VERSION,
            "generation": self.generation,
            "owner_count": len(self.materials),
            "created_principal_count": self.created_principal_count,
            "updated_principal_count": self.updated_principal_count,
            "created_credential_count": self.created_credential_count,
            "reused_credential_count": self.reused_credential_count,
            "owners": [material.owner for material in self.materials],
            "credential_values_included": False,
            "client_secret_values_included": False,
        }

    def openbao_values_by_owner(self) -> dict[str, dict[str, str]]:
        return {
            material.owner: material.openbao_values() for material in self.materials
        }


def canonical_service_principal_specs() -> tuple[CanonicalServicePrincipalSpec, ...]:
    specs = []
    for owner in CANONICAL_PLATFORM_OWNERS:
        if owner == "nex-oa":
            continue
        grants = tuple(
            grant for grant in CANONICAL_PLATFORM_TRUST_GRANTS if grant.owner == owner
        )
        short_name = owner.removeprefix("nex-")
        specs.append(
            CanonicalServicePrincipalSpec(
                owner=owner,
                principal_id=f"canonical-{short_name}",
                display_name=f"Canonical {short_name.upper()} Runtime",
                allowed_audiences=tuple(
                    sorted({grant.audience for grant in grants} | {"nex-oa"})
                ),
                allowed_scopes=tuple(
                    sorted(
                        {scope for grant in grants for scope in grant.scopes}
                        | {"token:introspect"}
                    )
                ),
            )
        )
    return tuple(specs)


def provision_canonical_service_principals(
    service: OaServicePrincipalService,
    *,
    generation: str,
    client_secrets: Mapping[str, str],
    now_epoch: int,
    lifetime_days: int = CANONICAL_SERVICE_CREDENTIAL_LIFETIME_DAYS,
    specs: Sequence[CanonicalServicePrincipalSpec] | None = None,
) -> CanonicalServicePrincipalProvisioning:
    if not isinstance(service, OaServicePrincipalService):
        raise CanonicalServicePrincipalProvisioningError(
            "canonical service principal authority is invalid"
        )
    normalized_generation = str(generation).strip()
    if _GENERATION.fullmatch(normalized_generation) is None:
        raise CanonicalServicePrincipalProvisioningError(
            "canonical service credential generation is invalid"
        )
    if isinstance(now_epoch, bool) or not isinstance(now_epoch, int) or now_epoch < 0:
        raise CanonicalServicePrincipalProvisioningError(
            "canonical service credential clock is invalid"
        )
    if (
        isinstance(lifetime_days, bool)
        or not isinstance(lifetime_days, int)
        or not 1 <= lifetime_days <= 30
    ):
        raise CanonicalServicePrincipalProvisioningError(
            "canonical service credential lifetime is invalid"
        )
    admitted_specs = tuple(specs or canonical_service_principal_specs())
    owners = tuple(spec.owner for spec in admitted_specs)
    if len(owners) != len(set(owners)) or set(client_secrets) != set(owners):
        raise CanonicalServicePrincipalProvisioningError(
            "canonical service credential owner coverage is invalid"
        )
    admitted_secrets = {
        owner: _client_secret(client_secrets[owner]) for owner in owners
    }

    materials = []
    created_principals = 0
    updated_principals = 0
    created_credentials = 0
    reused_credentials = 0
    for spec in admitted_specs:
        secret = admitted_secrets[spec.owner]
        current = _get_principal(service, spec.principal_id)
        desired = {
            "principal_id": spec.principal_id,
            "service_id": spec.owner,
            "display_name": spec.display_name,
            "status": "ACTIVE",
            "allowed_audiences": list(spec.allowed_audiences),
            "allowed_scopes": list(spec.allowed_scopes),
        }
        if current is None:
            service.upsert_principal({**desired, "expected_revision": 0})
            created_principals += 1
        elif not _principal_matches(current, desired):
            service.upsert_principal(
                {**desired, "expected_revision": current["revision"]}
            )
            updated_principals += 1

        credential_id = f"{spec.principal_id}-{normalized_generation}"
        credential = _get_credential(service, credential_id)
        if credential is None:
            service.issue_credential(
                spec.principal_id,
                lifetime_days=lifetime_days,
                now_epoch=now_epoch,
                credential_id=credential_id,
                client_secret=secret,
            )
            created_credentials += 1
        else:
            try:
                service.verify_client_secret(
                    credential_id,
                    secret,
                    now_epoch=now_epoch,
                )
            except OaServicePrincipalError as exc:
                raise CanonicalServicePrincipalProvisioningError(
                    "canonical service credential generation is already bound to "
                    "different material"
                ) from exc
            reused_credentials += 1
        materials.append(
            CanonicalServiceCredentialMaterial(
                owner=spec.owner,
                credential_id=credential_id,
                client_secret=secret,
            )
        )

    return CanonicalServicePrincipalProvisioning(
        generation=normalized_generation,
        materials=tuple(materials),
        created_principal_count=created_principals,
        updated_principal_count=updated_principals,
        created_credential_count=created_credentials,
        reused_credential_count=reused_credentials,
    )


def _get_principal(
    service: OaServicePrincipalService, principal_id: str
) -> dict[str, Any] | None:
    try:
        return dict(service.get_principal(principal_id)["principal"])
    except OaServicePrincipalError as exc:
        if exc.status_code == 404:
            return None
        raise


def _get_credential(
    service: OaServicePrincipalService, credential_id: str
) -> dict[str, Any] | None:
    try:
        return dict(service.get_credential(credential_id)["credential"])
    except OaServicePrincipalError as exc:
        if exc.status_code == 404:
            return None
        raise


def _principal_matches(current: Mapping[str, Any], desired: Mapping[str, Any]) -> bool:
    return all(
        current.get(name) == desired[name]
        for name in ("principal_id", "service_id", "display_name", "status")
    ) and all(
        tuple(current.get(name) or ()) == tuple(desired[name])
        for name in ("allowed_audiences", "allowed_scopes")
    )


def _client_secret(value: object) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or len(value) < 24
        or len(value) > 512
    ):
        raise CanonicalServicePrincipalProvisioningError(
            "canonical service client secret is invalid"
        )
    return value
