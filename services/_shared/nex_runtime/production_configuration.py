from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .runtime_profiles import (
    DATABASE_ENV_NAMES,
    LIVE_PROVIDER_ENV_NAMES,
    SERVICE_ENDPOINT_ENV_NAMES,
    SIGNED_TRUST_ENV_NAMES,
)


PRODUCTION_CONFIGURATION_SCHEMA_VERSION = "production_configuration_manifest.v1"
PRODUCTION_CONFIGURATION_MANIFEST_PATH = (
    "deployment/security/production-configuration.yaml"
)
PRODUCTION_CONTROL_ENV_NAMES = (
    "NEX_CONFIG_GENERATION",
    "NEX_SECRET_GENERATION",
    "NEX_TLS_GENERATION",
    "NEX_TLS_TERMINATION_POLICY_REF",
    "NEX_TLS_CERTIFICATE_REF",
    "NEX_TLS_TRUST_BUNDLE_REF",
)
_SECRET_ENV_NAMES = (
    *DATABASE_ENV_NAMES,
    *SIGNED_TRUST_ENV_NAMES,
    *(name for name in LIVE_PROVIDER_ENV_NAMES if name.endswith("_API_KEY")),
    "NEX_CX_OBJECT_STORAGE_ACCESS_KEY",
    "NEX_CX_OBJECT_STORAGE_SECRET_KEY",
    "NEX_AE_OBJECT_STORAGE_ACCESS_KEY",
    "NEX_AE_OBJECT_STORAGE_SECRET_KEY",
)
_PUBLIC_CONNECTION_ENV_NAMES = (
    *SERVICE_ENDPOINT_ENV_NAMES,
    *(name for name in LIVE_PROVIDER_ENV_NAMES if not name.endswith("_API_KEY")),
    "NEX_CX_OBJECT_STORAGE_ENDPOINT",
    "NEX_AE_OBJECT_STORAGE_ENDPOINT",
)
PRODUCTION_SECRET_BINDING_COUNT = len(_SECRET_ENV_NAMES)
PRODUCTION_PUBLIC_CONNECTION_COUNT = len(_PUBLIC_CONNECTION_ENV_NAMES)
_ALLOWED_OWNERS = (
    "platform_integration",
    "nex-oa",
    "nex-ae-api",
    "nex-cx",
    "nex-mo",
    "nex-ag",
)


class ProductionConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class ProductionConfigurationBinding:
    target_environment_name: str
    source_environment_name: str
    owner: str
    input_kind: str


@dataclass(frozen=True)
class ProductionConfigurationManifest:
    schema_version: str
    profile: str
    bindings: tuple[ProductionConfigurationBinding, ...]
    control_environment_names: tuple[str, ...]


def build_default_production_configuration_manifest(
) -> ProductionConfigurationManifest:
    bindings = tuple(
        ProductionConfigurationBinding(
            target_environment_name=name,
            source_environment_name=f"{name}_REF",
            owner=_secret_owner(name),
            input_kind="external_secret_reference",
        )
        for name in _SECRET_ENV_NAMES
    ) + tuple(
        ProductionConfigurationBinding(
            target_environment_name=name,
            source_environment_name=name,
            owner="platform_integration",
            input_kind="public_connection",
        )
        for name in _PUBLIC_CONNECTION_ENV_NAMES
    )
    manifest = ProductionConfigurationManifest(
        schema_version=PRODUCTION_CONFIGURATION_SCHEMA_VERSION,
        profile="production",
        bindings=bindings,
        control_environment_names=PRODUCTION_CONTROL_ENV_NAMES,
    )
    validate_production_configuration_manifest(manifest)
    return manifest


def load_production_configuration_manifest(
    root: Path,
) -> ProductionConfigurationManifest:
    path = root / PRODUCTION_CONFIGURATION_MANIFEST_PATH
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ProductionConfigurationError(
            "production configuration manifest is unreadable"
        ) from exc
    if not isinstance(document, Mapping):
        raise ProductionConfigurationError(
            "production configuration manifest must be an object"
        )
    try:
        secret_bindings = _required_string_mapping(
            document["secret_bindings"], "secret_bindings"
        )
        public_connections = _required_string_sequence(
            document["public_connections"], "public_connections"
        )
        control_names = _required_string_sequence(
            document["control_environment_names"], "control_environment_names"
        )
        bindings = tuple(
            ProductionConfigurationBinding(
                target_environment_name=target,
                source_environment_name=source,
                owner=_secret_owner(target),
                input_kind="external_secret_reference",
            )
            for target, source in secret_bindings.items()
        ) + tuple(
            ProductionConfigurationBinding(
                target_environment_name=name,
                source_environment_name=name,
                owner="platform_integration",
                input_kind="public_connection",
            )
            for name in public_connections
        )
        manifest = ProductionConfigurationManifest(
            schema_version=str(document["schema_version"]),
            profile=str(document["profile"]),
            bindings=bindings,
            control_environment_names=control_names,
        )
    except (KeyError, TypeError) as exc:
        raise ProductionConfigurationError(
            "production configuration manifest field is invalid"
        ) from exc
    validate_production_configuration_manifest(manifest)
    if manifest != build_default_production_configuration_manifest():
        raise ProductionConfigurationError(
            "production configuration manifest drift"
        )
    return manifest


def validate_production_configuration_manifest(
    manifest: ProductionConfigurationManifest,
) -> None:
    errors: list[str] = []
    if manifest.schema_version != PRODUCTION_CONFIGURATION_SCHEMA_VERSION:
        errors.append("production configuration schema version drift")
    if manifest.profile != "production":
        errors.append("production configuration profile drift")
    target_names = tuple(item.target_environment_name for item in manifest.bindings)
    source_names = tuple(item.source_environment_name for item in manifest.bindings)
    expected_targets = (*_SECRET_ENV_NAMES, *_PUBLIC_CONNECTION_ENV_NAMES)
    if target_names != expected_targets:
        errors.append("production configuration target coverage or order drift")
    if len(set(target_names)) != len(target_names):
        errors.append("production configuration targets must be unique")
    if len(set(source_names)) != len(source_names):
        errors.append("production configuration sources must be unique")
    for binding in manifest.bindings:
        if binding.owner not in _ALLOWED_OWNERS:
            errors.append(
                f"production configuration owner is invalid: "
                f"{binding.target_environment_name}"
            )
        if binding.target_environment_name in _SECRET_ENV_NAMES:
            if (
                binding.input_kind != "external_secret_reference"
                or binding.source_environment_name
                != f"{binding.target_environment_name}_REF"
            ):
                errors.append(
                    f"secret reference binding drift: "
                    f"{binding.target_environment_name}"
                )
        elif (
            binding.input_kind != "public_connection"
            or binding.source_environment_name != binding.target_environment_name
        ):
            errors.append(
                f"public connection binding drift: "
                f"{binding.target_environment_name}"
            )
    if manifest.control_environment_names != PRODUCTION_CONTROL_ENV_NAMES:
        errors.append("production control environment coverage or order drift")
    if errors:
        raise ProductionConfigurationError("; ".join(errors))


def production_configuration_manifest_projection(
    manifest: ProductionConfigurationManifest,
) -> dict[str, Any]:
    validate_production_configuration_manifest(manifest)
    return {
        "schema_version": manifest.schema_version,
        "profile": manifest.profile,
        "bindings": [
            {
                "target_environment_name": item.target_environment_name,
                "source_environment_name": item.source_environment_name,
                "owner": item.owner,
                "input_kind": item.input_kind,
            }
            for item in manifest.bindings
        ],
        "control_environment_names": list(manifest.control_environment_names),
        "binding_count": len(manifest.bindings),
        "secret_reference_count": sum(
            item.input_kind == "external_secret_reference"
            for item in manifest.bindings
        ),
        "public_connection_count": sum(
            item.input_kind == "public_connection" for item in manifest.bindings
        ),
        "control_environment_count": len(manifest.control_environment_names),
        "raw_secret_values_included": False,
        "reference_values_included": False,
        "connection_values_included": False,
    }


def _secret_owner(name: str) -> str:
    if name.startswith("NEX_AE_TO_"):
        return "nex-ae-api"
    if name.startswith("NEX_CX_TO_"):
        return "nex-cx"
    if name.startswith("NEX_AG_TO_"):
        return "nex-ag"
    for prefix, owner in (
        ("NEX_OA_", "nex-oa"),
        ("NEX_AE_", "nex-ae-api"),
        ("NEX_CX_", "nex-cx"),
        ("NEX_MO_", "nex-mo"),
        ("NEX_AG_", "nex-ag"),
    ):
        if name.startswith(prefix):
            return owner
    raise ProductionConfigurationError(f"secret owner is unknown: {name}")


def _required_string_mapping(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise TypeError(f"{field} must be a non-empty string mapping")
    result = dict(value)
    if any(
        not isinstance(key, str)
        or not key.strip()
        or not isinstance(item, str)
        or not item.strip()
        for key, item in result.items()
    ):
        raise TypeError(f"{field} must be a non-empty string mapping")
    return result


def _required_string_sequence(value: Any, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise TypeError(f"{field} must be a non-empty string list")
    return tuple(value)
