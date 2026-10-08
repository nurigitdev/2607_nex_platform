from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import ipaddress
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from .production_configuration import (
    PRODUCTION_PUBLIC_CONNECTION_COUNT,
    PRODUCTION_SECRET_BINDING_COUNT,
    ProductionConfigurationManifest,
    load_production_configuration_manifest,
)
from .runtime_profiles import runtime_profile_environment_overlay


PRODUCTION_STARTUP_ADMISSION_SCHEMA_VERSION = "production_startup_admission.v1"
EXTERNAL_STARTUP_PROFILES = ("staging_live", "production")
_GENERATION = re.compile(r"^[a-z][a-z0-9-]{2,31}:[A-Za-z0-9][A-Za-z0-9._-]{3,127}$")
_PLACEHOLDERS = {"changeme", "change-me", "placeholder", "<password>", "<secret>"}


class ProductionStartupAdmissionError(ValueError):
    def __init__(self, errors: tuple[str, ...]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class ProductionStartupAdmission:
    schema_version: str
    profile: str
    status: str
    configuration_digest: str
    secret_reference_count: int
    public_connection_count: int
    control_environment_count: int
    https_endpoint_count: int
    raw_secret_environment_count: int


def admit_production_startup(
    environ: Mapping[str, str],
    *,
    root: Path,
    manifest: ProductionConfigurationManifest | None = None,
) -> ProductionStartupAdmission:
    return admit_external_startup(
        environ,
        profile="production",
        root=root,
        manifest=manifest,
    )


def admit_external_startup(
    environ: Mapping[str, str],
    *,
    profile: str,
    root: Path,
    manifest: ProductionConfigurationManifest | None = None,
) -> ProductionStartupAdmission:
    if profile not in EXTERNAL_STARTUP_PROFILES:
        raise ProductionStartupAdmissionError(
            (f"external startup profile is invalid: {profile}",)
        )
    definition = manifest or load_production_configuration_manifest(root)
    errors: list[str] = []
    expected_modes = runtime_profile_environment_overlay(profile)
    for name, expected in expected_modes.items():
        configured = str(environ.get(name) or "").strip()
        if configured != expected:
            errors.append(f"{profile} runtime mode is invalid: {name}")

    selected_values: list[tuple[str, str]] = []
    secret_reference_count = 0
    public_connection_count = 0
    https_endpoint_count = 0
    raw_secret_names = []
    for binding in definition.bindings:
        raw_value = str(environ.get(binding.target_environment_name) or "").strip()
        if binding.input_kind == "external_secret_reference":
            secret_reference_count += 1
            if raw_value:
                raw_secret_names.append(binding.target_environment_name)
            reference = str(environ.get(binding.source_environment_name) or "").strip()
            if not _valid_versioned_reference(reference, scheme="secret"):
                errors.append(
                    "external secret reference is missing or invalid: "
                    f"{binding.source_environment_name}"
                )
            else:
                selected_values.append((binding.source_environment_name, reference))
        else:
            public_connection_count += 1
            endpoint = str(environ.get(binding.source_environment_name) or "").strip()
            if not _valid_https_endpoint(endpoint):
                errors.append(
                    f"{profile} HTTPS endpoint is missing or invalid: "
                    f"{binding.source_environment_name}"
                )
            else:
                https_endpoint_count += 1
                selected_values.append((binding.source_environment_name, endpoint))
    for name in raw_secret_names:
        errors.append(f"raw secret deployment input is prohibited: {name}")

    for name in definition.control_environment_names[:3]:
        value = str(environ.get(name) or "").strip()
        if _GENERATION.fullmatch(value) is None or _is_placeholder(value):
            errors.append(f"production generation is missing or invalid: {name}")
        else:
            selected_values.append((name, value))
    for name in definition.control_environment_names[3:]:
        value = str(environ.get(name) or "").strip()
        if not _valid_versioned_reference(value, scheme="tls"):
            errors.append(f"TLS reference is missing or invalid: {name}")
        else:
            selected_values.append((name, value))

    if errors:
        raise ProductionStartupAdmissionError(tuple(errors))
    selected_values.extend(sorted(expected_modes.items()))
    configuration_digest = _configuration_digest(selected_values)
    return ProductionStartupAdmission(
        schema_version=PRODUCTION_STARTUP_ADMISSION_SCHEMA_VERSION,
        profile=profile,
        status="ADMITTED_FOR_SECRET_MATERIALIZATION",
        configuration_digest=configuration_digest,
        secret_reference_count=secret_reference_count,
        public_connection_count=public_connection_count,
        control_environment_count=len(definition.control_environment_names),
        https_endpoint_count=https_endpoint_count,
        raw_secret_environment_count=0,
    )


def production_startup_admission_projection(
    admission: ProductionStartupAdmission,
) -> dict[str, Any]:
    if (
        admission.schema_version != PRODUCTION_STARTUP_ADMISSION_SCHEMA_VERSION
        or admission.profile != "production"
        or admission.status != "ADMITTED_FOR_SECRET_MATERIALIZATION"
        or re.fullmatch(r"sha256:[0-9a-f]{64}", admission.configuration_digest)
        is None
        or admission.secret_reference_count != PRODUCTION_SECRET_BINDING_COUNT
        or admission.public_connection_count != PRODUCTION_PUBLIC_CONNECTION_COUNT
        or admission.control_environment_count != 6
        or admission.https_endpoint_count != PRODUCTION_PUBLIC_CONNECTION_COUNT
        or admission.raw_secret_environment_count != 0
    ):
        raise ProductionStartupAdmissionError(
            ("production startup admission projection is invalid",)
        )
    return {
        "schema_version": admission.schema_version,
        "profile": admission.profile,
        "status": admission.status,
        "configuration_digest": admission.configuration_digest,
        "secret_reference_count": admission.secret_reference_count,
        "public_connection_count": admission.public_connection_count,
        "control_environment_count": admission.control_environment_count,
        "https_endpoint_count": admission.https_endpoint_count,
        "raw_secret_environment_count": admission.raw_secret_environment_count,
        "raw_secret_values_included": False,
        "reference_values_included": False,
        "endpoint_values_included": False,
    }


def external_startup_admission_projection(
    admission: ProductionStartupAdmission,
    *,
    expected_profile: str,
) -> dict[str, Any]:
    if expected_profile not in EXTERNAL_STARTUP_PROFILES:
        raise ProductionStartupAdmissionError(
            ("external startup admission profile is invalid",)
        )
    if admission.profile != expected_profile:
        raise ProductionStartupAdmissionError(
            ("external startup admission projection is invalid",)
        )
    if expected_profile == "production":
        return production_startup_admission_projection(admission)
    if (
        admission.schema_version != PRODUCTION_STARTUP_ADMISSION_SCHEMA_VERSION
        or admission.status != "ADMITTED_FOR_SECRET_MATERIALIZATION"
        or re.fullmatch(r"sha256:[0-9a-f]{64}", admission.configuration_digest)
        is None
        or admission.secret_reference_count != PRODUCTION_SECRET_BINDING_COUNT
        or admission.public_connection_count != PRODUCTION_PUBLIC_CONNECTION_COUNT
        or admission.control_environment_count != 6
        or admission.https_endpoint_count != PRODUCTION_PUBLIC_CONNECTION_COUNT
        or admission.raw_secret_environment_count != 0
    ):
        raise ProductionStartupAdmissionError(
            ("external startup admission projection is invalid",)
        )
    return {
        "schema_version": admission.schema_version,
        "profile": admission.profile,
        "status": admission.status,
        "configuration_digest": admission.configuration_digest,
        "secret_reference_count": admission.secret_reference_count,
        "public_connection_count": admission.public_connection_count,
        "control_environment_count": admission.control_environment_count,
        "https_endpoint_count": admission.https_endpoint_count,
        "raw_secret_environment_count": admission.raw_secret_environment_count,
        "raw_secret_values_included": False,
        "reference_values_included": False,
        "endpoint_values_included": False,
    }


def _valid_versioned_reference(value: str, *, scheme: str) -> bool:
    if not value or len(value) > 512 or _is_placeholder(value) or any(
        character.isspace() for character in value
    ):
        return False
    parsed = urlsplit(value)
    if (
        parsed.scheme != scheme
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or "@" not in parsed.path
    ):
        return False
    resource, version = parsed.path.rsplit("@", 1)
    return len(resource) > 1 and bool(version)


def _valid_https_endpoint(value: str) -> bool:
    if not value or len(value) > 2048 or _is_placeholder(value) or any(
        character.isspace() for character in value
    ):
        return False
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return False
    try:
        return not ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return True


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in _PLACEHOLDERS or "<secret>" in normalized


def _configuration_digest(values: list[tuple[str, str]]) -> str:
    payload = json.dumps(
        sorted(values), ensure_ascii=True, separators=(",", ":")
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
