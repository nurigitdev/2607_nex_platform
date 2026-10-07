from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .background_process import ENABLED_BACKGROUND_PROFILES
from .deployment_artifacts import (
    DeploymentArtifactCatalog,
    build_default_deployment_artifact_catalog,
    immutable_image_reference,
)
from .runtime_profiles import (
    RuntimeProfileError,
    resolve_runtime_profile,
    runtime_profile_required_environment_names,
)
from .topology import RUNTIME_PROFILES


ENVIRONMENT_COMPOSITION_SCHEMA_VERSION = "environment_composition.v1"
ENVIRONMENT_CLASSES = ("development", "test", "staging", "production")
ARTIFACT_REFERENCE_ENVIRONMENTS = {
    "nex-oa-runtime": "NEX_OA_RUNTIME_IMAGE",
    "nex-ae-runtime": "NEX_AE_RUNTIME_IMAGE",
    "nex-cx-runtime": "NEX_CX_RUNTIME_IMAGE",
    "nex-mo-runtime": "NEX_MO_RUNTIME_IMAGE",
    "nex-ag-runtime": "NEX_AG_RUNTIME_IMAGE",
    "nex-ae-web": "NEX_AE_WEB_IMAGE",
}
COMPOSITION_STATUSES = ("LIMITED", "BLOCKED")


class EnvironmentCompositionError(ValueError):
    pass


@dataclass(frozen=True)
class EnvironmentCompositionDefinition:
    environment_class: str
    runtime_profiles: tuple[str, ...]
    artifact_reference_policy: str
    immutable_artifacts_required: bool
    allow_loopback: bool
    allow_local_storage: bool
    secret_source: str
    production_contact_allowed: bool
    admitted_background_profiles: tuple[str, ...]


@dataclass(frozen=True)
class EnvironmentCompositionResolution:
    environment_class: str
    profile: str
    status: str
    reason_codes: tuple[str, ...]
    required_environment_names: tuple[str, ...]
    required_artifact_environment_names: tuple[str, ...]
    artifact_references: tuple[tuple[str, str], ...] = field(repr=False)


DEFAULT_ENVIRONMENT_COMPOSITIONS = (
    EnvironmentCompositionDefinition(
        "development",
        ("local_mock", "local_live"),
        "local_build_or_digest",
        False,
        True,
        True,
        "local_environment",
        False,
        ("local_mock",),
    ),
    EnvironmentCompositionDefinition(
        "test",
        ("test",),
        "immutable_digest",
        True,
        False,
        False,
        "test_injection",
        False,
        ("test",),
    ),
    EnvironmentCompositionDefinition(
        "staging",
        ("staging_live",),
        "immutable_digest",
        True,
        False,
        False,
        "external_reference",
        False,
        (),
    ),
    EnvironmentCompositionDefinition(
        "production",
        ("production",),
        "immutable_digest",
        True,
        False,
        False,
        "external_reference",
        False,
        (),
    ),
)


def build_default_environment_compositions() -> tuple[EnvironmentCompositionDefinition, ...]:
    validate_environment_compositions(DEFAULT_ENVIRONMENT_COMPOSITIONS)
    return DEFAULT_ENVIRONMENT_COMPOSITIONS


def load_environment_compositions(
    root: Path,
) -> tuple[EnvironmentCompositionDefinition, ...]:
    definitions = []
    directory = root / "deployment" / "environments"
    for environment_class in ENVIRONMENT_CLASSES:
        path = directory / f"{environment_class}.yaml"
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise EnvironmentCompositionError(
                f"environment composition is unreadable: {environment_class}"
            ) from exc
        if not isinstance(document, Mapping):
            raise EnvironmentCompositionError(
                f"environment composition is not an object: {environment_class}"
            )
        if document.get("schema_version") != ENVIRONMENT_COMPOSITION_SCHEMA_VERSION:
            raise EnvironmentCompositionError(
                f"environment composition schema drift: {environment_class}"
            )
        try:
            definitions.append(
                EnvironmentCompositionDefinition(
                    environment_class=str(document["environment_class"]),
                    runtime_profiles=_required_string_sequence(
                        document["runtime_profiles"], "runtime_profiles"
                    ),
                    artifact_reference_policy=str(
                        document["artifact_reference_policy"]
                    ),
                    immutable_artifacts_required=_required_bool(
                        document["immutable_artifacts_required"],
                        "immutable_artifacts_required",
                    ),
                    allow_loopback=_required_bool(
                        document["allow_loopback"], "allow_loopback"
                    ),
                    allow_local_storage=_required_bool(
                        document["allow_local_storage"], "allow_local_storage"
                    ),
                    secret_source=str(document["secret_source"]),
                    production_contact_allowed=_required_bool(
                        document["production_contact_allowed"],
                        "production_contact_allowed",
                    ),
                    admitted_background_profiles=_required_string_sequence(
                        document["admitted_background_profiles"],
                        "admitted_background_profiles",
                    ),
                )
            )
        except (KeyError, TypeError) as exc:
            raise EnvironmentCompositionError(
                f"environment composition field is invalid: {environment_class}"
            ) from exc
    result = tuple(definitions)
    validate_environment_compositions(result)
    if result != DEFAULT_ENVIRONMENT_COMPOSITIONS:
        raise EnvironmentCompositionError("environment composition manifest drift")
    return result


def validate_environment_compositions(
    definitions: tuple[EnvironmentCompositionDefinition, ...],
) -> None:
    errors: list[str] = []
    class_ids: set[str] = set()
    profiles: list[str] = []
    for definition in definitions:
        if definition.environment_class not in ENVIRONMENT_CLASSES:
            errors.append(
                f"unknown environment class: {definition.environment_class}"
            )
        if definition.environment_class in class_ids:
            errors.append(
                f"duplicate environment class: {definition.environment_class}"
            )
        class_ids.add(definition.environment_class)
        profiles.extend(definition.runtime_profiles)
        if definition.artifact_reference_policy not in {
            "local_build_or_digest",
            "immutable_digest",
        }:
            errors.append(
                f"invalid artifact reference policy: {definition.environment_class}"
            )
        if not definition.runtime_profiles:
            errors.append(f"environment profiles are empty: {definition.environment_class}")
        if not set(definition.admitted_background_profiles).issubset(
            set(definition.runtime_profiles).intersection(ENABLED_BACKGROUND_PROFILES)
        ):
            errors.append(
                f"invalid background profile admission: {definition.environment_class}"
            )
        if definition.production_contact_allowed:
            errors.append(
                f"production contact is not approved: {definition.environment_class}"
            )
    if class_ids != set(ENVIRONMENT_CLASSES):
        errors.append("environment class coverage is incomplete")
    if len(profiles) != len(set(profiles)) or set(profiles) != set(RUNTIME_PROFILES):
        errors.append("runtime profile coverage must be exact")
    by_class = {item.environment_class: item for item in definitions}
    for protected_class in ("test", "staging", "production"):
        definition = by_class.get(protected_class)
        if definition is not None and (
            not definition.immutable_artifacts_required
            or definition.allow_loopback
            or definition.allow_local_storage
        ):
            errors.append(f"protected class policy is unsafe: {protected_class}")
    if errors:
        raise EnvironmentCompositionError("; ".join(errors))


def resolve_environment_composition(
    profile: str,
    *,
    environ: Mapping[str, str],
    definitions: tuple[EnvironmentCompositionDefinition, ...] | None = None,
    catalog: DeploymentArtifactCatalog | None = None,
) -> EnvironmentCompositionResolution:
    compositions = definitions or build_default_environment_compositions()
    validate_environment_compositions(compositions)
    artifact_catalog = catalog or build_default_deployment_artifact_catalog()
    try:
        runtime = resolve_runtime_profile(profile, environ=environ)
    except RuntimeProfileError as exc:
        raise EnvironmentCompositionError(str(exc)) from exc
    definition = next(
        item for item in compositions if runtime.profile in item.runtime_profiles
    )
    artifact_names = tuple(
        ARTIFACT_REFERENCE_ENVIRONMENTS[artifact.artifact_id]
        for artifact in artifact_catalog.artifacts
    )
    references: list[tuple[str, str]] = []
    if definition.immutable_artifacts_required:
        for artifact in artifact_catalog.artifacts:
            environment_name = ARTIFACT_REFERENCE_ENVIRONMENTS[artifact.artifact_id]
            reference = str(environ.get(environment_name) or "").strip()
            if not reference:
                raise EnvironmentCompositionError(
                    f"immutable artifact reference is missing: {environment_name}"
                )
            references.append(
                (artifact.artifact_id, _validated_image_reference(reference))
            )
        if len({value for _, value in references}) != len(references):
            raise EnvironmentCompositionError("artifact references must be unique")
    reasons = []
    if runtime.profile not in definition.admitted_background_profiles:
        reasons.append("background_execution_profile_not_admitted")
    if runtime.profile == "production":
        reasons.append("production_deployment_approval_deferred")
    if not reasons:
        status = "LIMITED"
        reasons.append("lifecycle_only_background_roles_present")
    else:
        status = "BLOCKED"
    return EnvironmentCompositionResolution(
        environment_class=definition.environment_class,
        profile=runtime.profile,
        status=status,
        reason_codes=tuple(reasons),
        required_environment_names=runtime.required_environment_names,
        required_artifact_environment_names=(
            artifact_names if definition.immutable_artifacts_required else ()
        ),
        artifact_references=tuple(references),
    )


def environment_composition_projection(
    resolution: EnvironmentCompositionResolution,
) -> dict[str, Any]:
    if resolution.status not in COMPOSITION_STATUSES:
        raise EnvironmentCompositionError("environment composition status is invalid")
    return {
        "schema_version": ENVIRONMENT_COMPOSITION_SCHEMA_VERSION,
        "environment_class": resolution.environment_class,
        "profile": resolution.profile,
        "status": resolution.status,
        "reason_codes": list(resolution.reason_codes),
        "required_environment_names": list(resolution.required_environment_names),
        "required_artifact_environment_names": list(
            resolution.required_artifact_environment_names
        ),
        "artifact_reference_count": len(resolution.artifact_references),
        "artifact_reference_values_included": False,
    }


def environment_composition_manifest_projection(
    definition: EnvironmentCompositionDefinition,
) -> dict[str, Any]:
    return {
        "schema_version": ENVIRONMENT_COMPOSITION_SCHEMA_VERSION,
        "environment_class": definition.environment_class,
        "runtime_profiles": list(definition.runtime_profiles),
        "artifact_reference_policy": definition.artifact_reference_policy,
        "immutable_artifacts_required": definition.immutable_artifacts_required,
        "allow_loopback": definition.allow_loopback,
        "allow_local_storage": definition.allow_local_storage,
        "secret_source": definition.secret_source,
        "production_contact_allowed": definition.production_contact_allowed,
        "admitted_background_profiles": list(
            definition.admitted_background_profiles
        ),
    }


def required_environment_names_for_composition(profile: str) -> tuple[str, ...]:
    return runtime_profile_required_environment_names(profile)


def _validated_image_reference(reference: str) -> str:
    try:
        repository, digest = reference.rsplit("@", 1)
    except ValueError as exc:
        raise EnvironmentCompositionError(
            "artifact reference must use an immutable digest"
        ) from exc
    try:
        return immutable_image_reference(repository, digest)
    except ValueError as exc:
        raise EnvironmentCompositionError(
            "artifact reference must use an immutable digest"
        ) from exc


def _required_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")
    return value


def _required_string_sequence(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise TypeError(f"{field_name} must be a string list")
    return tuple(value)
