from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Protocol
from urllib.parse import urlsplit

from .production_configuration import (
    ProductionConfigurationManifest,
    load_production_configuration_manifest,
)
from .production_startup_admission import admit_external_startup, admit_production_startup


PRODUCTION_SECRET_MATERIALIZATION_SCHEMA_VERSION = (
    "production_secret_materialization.v1"
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_PLACEHOLDERS = {"changeme", "change-me", "placeholder", "<password>", "<secret>"}


class ProductionSecretMaterializationError(ValueError):
    pass


@dataclass(frozen=True)
class SecretResolutionContext:
    owner: str
    target_environment_name: str
    secret_generation: str
    reference_version: str


@dataclass(frozen=True)
class ResolvedSecret:
    owner: str
    target_environment_name: str
    secret_generation: str
    reference_version: str
    provider_id: str
    value: str = field(repr=False)


class SecretReferenceResolver(Protocol):
    def resolve(
        self,
        reference: str,
        *,
        context: SecretResolutionContext,
    ) -> ResolvedSecret: ...


@dataclass(frozen=True)
class OwnerSecretEnvironment:
    owner: str
    secrets: tuple[ResolvedSecret, ...] = field(repr=False)

    def process_environment(self) -> dict[str, str]:
        return {
            secret.target_environment_name: secret.value for secret in self.secrets
        }


@dataclass(frozen=True)
class ProductionSecretMaterialization:
    schema_version: str
    profile: str
    status: str
    configuration_digest: str
    materialization_digest: str
    secret_generation: str
    owner_environments: tuple[OwnerSecretEnvironment, ...] = field(repr=False)

    def environment_for(self, owner: str) -> dict[str, str]:
        for item in self.owner_environments:
            if item.owner == owner:
                return item.process_environment()
        raise ProductionSecretMaterializationError(
            f"secret materialization owner is unknown: {owner}"
        )


@dataclass(frozen=True)
class OwnerProductionSecretMaterialization:
    schema_version: str
    profile: str
    status: str
    configuration_digest: str
    materialization_digest: str
    secret_generation: str
    owner_environment: OwnerSecretEnvironment = field(repr=False)


def materialize_production_secrets(
    environ: Mapping[str, str],
    resolver: SecretReferenceResolver,
    *,
    root: Path,
    manifest: ProductionConfigurationManifest | None = None,
) -> ProductionSecretMaterialization:
    definition = manifest or load_production_configuration_manifest(root)
    admission = admit_production_startup(environ, root=root, manifest=definition)
    generation = str(environ["NEX_SECRET_GENERATION"]).strip()
    by_owner: dict[str, list[ResolvedSecret]] = {}
    metadata: list[tuple[str, str, str, str]] = []

    for binding in definition.bindings:
        if binding.input_kind != "external_secret_reference":
            continue
        reference = str(environ[binding.source_environment_name]).strip()
        provider_id, reference_version = _reference_metadata(reference)
        context = SecretResolutionContext(
            owner=binding.owner,
            target_environment_name=binding.target_environment_name,
            secret_generation=generation,
            reference_version=reference_version,
        )
        try:
            secret = resolver.resolve(reference, context=context)
        except Exception:
            raise ProductionSecretMaterializationError(
                "external secret resolution failed: "
                f"{binding.target_environment_name}"
            ) from None
        _validate_resolved_secret(secret, context=context, provider_id=provider_id)
        by_owner.setdefault(binding.owner, []).append(secret)
        metadata.append(
            (
                binding.owner,
                binding.target_environment_name,
                secret.provider_id,
                secret.reference_version,
            )
        )

    owner_environments = tuple(
        OwnerSecretEnvironment(owner=owner, secrets=tuple(secrets))
        for owner, secrets in by_owner.items()
    )
    if sum(len(item.secrets) for item in owner_environments) != 16:
        raise ProductionSecretMaterializationError(
            "production secret materialization coverage drift"
        )
    digest_payload = {
        "configuration_digest": admission.configuration_digest,
        "secret_generation": generation,
        "metadata": metadata,
    }
    digest = hashlib.sha256(
        json.dumps(
            digest_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("ascii")
    ).hexdigest()
    return ProductionSecretMaterialization(
        schema_version=PRODUCTION_SECRET_MATERIALIZATION_SCHEMA_VERSION,
        profile="production",
        status="MATERIALIZED_FOR_OWNER_PROCESSES",
        configuration_digest=admission.configuration_digest,
        materialization_digest=f"sha256:{digest}",
        secret_generation=generation,
        owner_environments=owner_environments,
    )


def materialize_owner_production_secrets(
    environ: Mapping[str, str],
    resolver: SecretReferenceResolver,
    *,
    owner: str,
    profile: str = "production",
    root: Path,
    manifest: ProductionConfigurationManifest | None = None,
) -> OwnerProductionSecretMaterialization:
    definition = manifest or load_production_configuration_manifest(root)
    admission = admit_external_startup(
        environ,
        profile=profile,
        root=root,
        manifest=definition,
    )
    bindings = tuple(
        binding
        for binding in definition.bindings
        if binding.input_kind == "external_secret_reference"
        and binding.owner == owner
    )
    if not bindings:
        raise ProductionSecretMaterializationError(
            f"production secret owner is unknown: {owner}"
        )
    generation = str(environ["NEX_SECRET_GENERATION"]).strip()
    secrets = []
    metadata = []
    for binding in bindings:
        reference = str(environ[binding.source_environment_name]).strip()
        provider_id, reference_version = _reference_metadata(reference)
        context = SecretResolutionContext(
            owner=owner,
            target_environment_name=binding.target_environment_name,
            secret_generation=generation,
            reference_version=reference_version,
        )
        try:
            secret = resolver.resolve(reference, context=context)
        except Exception:
            raise ProductionSecretMaterializationError(
                "external owner secret resolution failed: "
                f"{binding.target_environment_name}"
            ) from None
        _validate_resolved_secret(secret, context=context, provider_id=provider_id)
        secrets.append(secret)
        metadata.append(
            (
                owner,
                binding.target_environment_name,
                secret.provider_id,
                secret.reference_version,
            )
        )
    digest_payload = {
        "configuration_digest": admission.configuration_digest,
        "secret_generation": generation,
        "owner": owner,
        "metadata": metadata,
    }
    digest = hashlib.sha256(
        json.dumps(
            digest_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("ascii")
    ).hexdigest()
    return OwnerProductionSecretMaterialization(
        schema_version=PRODUCTION_SECRET_MATERIALIZATION_SCHEMA_VERSION,
        profile=profile,
        status="MATERIALIZED_FOR_OWNER_PROCESS",
        configuration_digest=admission.configuration_digest,
        materialization_digest=f"sha256:{digest}",
        secret_generation=generation,
        owner_environment=OwnerSecretEnvironment(owner=owner, secrets=tuple(secrets)),
    )


def owner_production_secret_materialization_projection(
    materialization: OwnerProductionSecretMaterialization,
) -> dict[str, Any]:
    if (
        materialization.schema_version
        != PRODUCTION_SECRET_MATERIALIZATION_SCHEMA_VERSION
        or materialization.profile not in {"staging_live", "production"}
        or materialization.status != "MATERIALIZED_FOR_OWNER_PROCESS"
        or _DIGEST.fullmatch(materialization.configuration_digest) is None
        or _DIGEST.fullmatch(materialization.materialization_digest) is None
        or not materialization.owner_environment.owner
        or not materialization.owner_environment.secrets
    ):
        raise ProductionSecretMaterializationError(
            "owner production secret materialization projection is invalid"
        )
    environment_names = [
        secret.target_environment_name
        for secret in materialization.owner_environment.secrets
    ]
    if len(environment_names) != len(set(environment_names)):
        raise ProductionSecretMaterializationError(
            "owner production secret materialization coverage drift"
        )
    return {
        "schema_version": materialization.schema_version,
        "profile": materialization.profile,
        "status": materialization.status,
        "configuration_digest": materialization.configuration_digest,
        "materialization_digest": materialization.materialization_digest,
        "secret_generation": materialization.secret_generation,
        "owner": materialization.owner_environment.owner,
        "target_environment_names": environment_names,
        "secret_count": len(environment_names),
        "raw_secret_values_included": False,
        "reference_values_included": False,
    }


def production_secret_materialization_projection(
    materialization: ProductionSecretMaterialization,
) -> dict[str, Any]:
    if (
        materialization.schema_version
        != PRODUCTION_SECRET_MATERIALIZATION_SCHEMA_VERSION
        or materialization.profile != "production"
        or materialization.status != "MATERIALIZED_FOR_OWNER_PROCESSES"
        or _DIGEST.fullmatch(materialization.configuration_digest) is None
        or _DIGEST.fullmatch(materialization.materialization_digest) is None
    ):
        raise ProductionSecretMaterializationError(
            "production secret materialization projection is invalid"
        )
    owners = [
        {
            "owner": item.owner,
            "target_environment_names": [
                secret.target_environment_name for secret in item.secrets
            ],
            "secret_count": len(item.secrets),
        }
        for item in materialization.owner_environments
    ]
    if sum(int(item["secret_count"]) for item in owners) != 16:
        raise ProductionSecretMaterializationError(
            "production secret materialization projection coverage drift"
        )
    return {
        "schema_version": materialization.schema_version,
        "profile": materialization.profile,
        "status": materialization.status,
        "configuration_digest": materialization.configuration_digest,
        "materialization_digest": materialization.materialization_digest,
        "secret_generation": materialization.secret_generation,
        "owners": owners,
        "owner_count": len(owners),
        "secret_count": sum(int(item["secret_count"]) for item in owners),
        "raw_secret_values_included": False,
        "reference_values_included": False,
    }


def _reference_metadata(reference: str) -> tuple[str, str]:
    parsed = urlsplit(reference)
    try:
        _, version = parsed.path.rsplit("@", 1)
    except ValueError:
        raise ProductionSecretMaterializationError(
            "admitted secret reference metadata is invalid"
        ) from None
    if not parsed.hostname or not version:
        raise ProductionSecretMaterializationError(
            "admitted secret reference metadata is invalid"
        )
    return parsed.hostname, version


def _validate_resolved_secret(
    secret: ResolvedSecret,
    *,
    context: SecretResolutionContext,
    provider_id: str,
) -> None:
    if not isinstance(secret, ResolvedSecret):
        raise ProductionSecretMaterializationError(
            f"secret resolver result is invalid: {context.target_environment_name}"
        )
    if (
        secret.owner != context.owner
        or secret.target_environment_name != context.target_environment_name
        or secret.secret_generation != context.secret_generation
        or secret.reference_version != context.reference_version
        or secret.provider_id != provider_id
    ):
        raise ProductionSecretMaterializationError(
            f"secret resolver metadata mismatch: {context.target_environment_name}"
        )
    value = secret.value
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.strip().lower() in _PLACEHOLDERS
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ProductionSecretMaterializationError(
            f"resolved secret value is invalid: {context.target_environment_name}"
        )
