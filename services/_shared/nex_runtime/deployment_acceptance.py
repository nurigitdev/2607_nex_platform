from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .deployment_artifacts import (
    DeploymentArtifactCatalog,
    build_default_deployment_artifact_catalog,
)
from .postgres_orchestration import POSTGRES_SERVICE_ORDER
from .process_manifest import BACKGROUND_PROCESS_IDS


PACKAGED_RUNTIME_ACCEPTANCE_SCHEMA_VERSION = "packaged_runtime_acceptance.v1"
PACKAGED_RUNTIME_ACCEPTANCE_STATUS = "PACKAGE_CONTEXT_ACCEPTED"
PACKAGED_RUNTIME_EXECUTION_MODE = "materialized_package_context"
NETWORK_PROCESS_IDS = (
    "nex-oa-api",
    "nex-mo-api",
    "nex-cx-api",
    "nex-ae-api",
    "nex-ag-api",
    "nex-ae-web",
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class PackagedRuntimeAcceptanceError(ValueError):
    pass


@dataclass(frozen=True)
class PackagedRuntimeAcceptanceEvidence:
    schema_version: str
    status: str
    profile: str
    execution_mode: str
    artifact_context_digests: tuple[tuple[str, str], ...]
    migrated_service_ids: tuple[str, ...]
    background_check_process_ids: tuple[str, ...]
    startup_generations: tuple[tuple[str, ...], ...]
    postgres_identity_count: int
    oci_daemon_status: str
    image_build_performed: bool
    complete_set_restart_observed: bool
    mixed_artifact_set_allowed: bool
    database_downgrade_performed: bool
    production_contacted: bool


def build_packaged_runtime_acceptance_evidence(
    *,
    artifact_context_digests: tuple[tuple[str, str], ...],
    migrated_service_ids: tuple[str, ...],
    background_check_process_ids: tuple[str, ...],
    startup_generations: tuple[tuple[str, ...], ...],
    postgres_identity_count: int,
    oci_daemon_status: str,
) -> PackagedRuntimeAcceptanceEvidence:
    evidence = PackagedRuntimeAcceptanceEvidence(
        schema_version=PACKAGED_RUNTIME_ACCEPTANCE_SCHEMA_VERSION,
        status=PACKAGED_RUNTIME_ACCEPTANCE_STATUS,
        profile="test",
        execution_mode=PACKAGED_RUNTIME_EXECUTION_MODE,
        artifact_context_digests=artifact_context_digests,
        migrated_service_ids=migrated_service_ids,
        background_check_process_ids=background_check_process_ids,
        startup_generations=startup_generations,
        postgres_identity_count=postgres_identity_count,
        oci_daemon_status=oci_daemon_status,
        image_build_performed=False,
        complete_set_restart_observed=True,
        mixed_artifact_set_allowed=False,
        database_downgrade_performed=False,
        production_contacted=False,
    )
    validate_packaged_runtime_acceptance_evidence(evidence)
    return evidence


def validate_packaged_runtime_acceptance_evidence(
    evidence: PackagedRuntimeAcceptanceEvidence,
    *,
    catalog: DeploymentArtifactCatalog | None = None,
) -> None:
    artifact_catalog = catalog or build_default_deployment_artifact_catalog()
    errors: list[str] = []
    expected_artifacts = tuple(
        artifact.artifact_id for artifact in artifact_catalog.artifacts
    )
    context_ids = tuple(item[0] for item in evidence.artifact_context_digests)
    context_digests = tuple(item[1] for item in evidence.artifact_context_digests)
    if evidence.schema_version != PACKAGED_RUNTIME_ACCEPTANCE_SCHEMA_VERSION:
        errors.append("packaged runtime acceptance schema version drift")
    if evidence.status != PACKAGED_RUNTIME_ACCEPTANCE_STATUS:
        errors.append("packaged runtime acceptance status drift")
    if evidence.profile != "test":
        errors.append("packaged runtime acceptance profile must be test")
    if evidence.execution_mode != PACKAGED_RUNTIME_EXECUTION_MODE:
        errors.append("packaged runtime acceptance execution mode drift")
    if context_ids != expected_artifacts:
        errors.append("artifact context coverage or order drift")
    if any(_SHA256.fullmatch(digest) is None for digest in context_digests):
        errors.append("artifact context digest is invalid")
    if len(context_digests) != len(set(context_digests)):
        errors.append("artifact context digests must be unique")
    if evidence.migrated_service_ids != tuple(POSTGRES_SERVICE_ORDER):
        errors.append("packaged migration service order drift")
    if evidence.background_check_process_ids != tuple(BACKGROUND_PROCESS_IDS):
        errors.append("background packaged check coverage or order drift")
    if len(evidence.startup_generations) != 2 or any(
        generation != NETWORK_PROCESS_IDS
        for generation in evidence.startup_generations
    ):
        errors.append("network packaged restart evidence is incomplete")
    if evidence.postgres_identity_count != len(POSTGRES_SERVICE_ORDER):
        errors.append("PostgreSQL identity evidence is incomplete")
    if evidence.oci_daemon_status not in {
        "AVAILABLE_NOT_USED",
        "UNAVAILABLE_PERMISSION_OR_SOCKET",
        "UNAVAILABLE_NOT_INSTALLED",
    }:
        errors.append("OCI daemon status is invalid")
    if evidence.image_build_performed:
        errors.append("package-context acceptance cannot claim an image build")
    if not evidence.complete_set_restart_observed:
        errors.append("complete artifact-set restart was not observed")
    if evidence.mixed_artifact_set_allowed:
        errors.append("mixed artifact sets are prohibited")
    if evidence.database_downgrade_performed:
        errors.append("database downgrade is prohibited")
    if evidence.production_contacted:
        errors.append("production contact is prohibited")
    if errors:
        raise PackagedRuntimeAcceptanceError("; ".join(errors))


def packaged_runtime_acceptance_projection(
    evidence: PackagedRuntimeAcceptanceEvidence,
) -> dict[str, Any]:
    validate_packaged_runtime_acceptance_evidence(evidence)
    return {
        "schema_version": evidence.schema_version,
        "status": evidence.status,
        "profile": evidence.profile,
        "execution_mode": evidence.execution_mode,
        "artifact_contexts": [
            {"artifact_id": artifact_id, "context_digest": digest}
            for artifact_id, digest in evidence.artifact_context_digests
        ],
        "migrated_service_ids": list(evidence.migrated_service_ids),
        "background_check_process_ids": list(
            evidence.background_check_process_ids
        ),
        "startup_generations": [
            list(generation) for generation in evidence.startup_generations
        ],
        "postgres_identity_count": evidence.postgres_identity_count,
        "oci_daemon_status": evidence.oci_daemon_status,
        "image_build_performed": evidence.image_build_performed,
        "complete_set_restart_observed": (
            evidence.complete_set_restart_observed
        ),
        "mixed_artifact_set_allowed": evidence.mixed_artifact_set_allowed,
        "database_downgrade_performed": evidence.database_downgrade_performed,
        "production_contacted": evidence.production_contacted,
        "runtime_values_included": False,
        "machine_paths_included": False,
        "credentials_included": False,
    }
