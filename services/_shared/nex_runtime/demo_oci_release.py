from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .demo_processes import (
    DEMO_APPLICATION_ARTIFACTS,
    build_demo_process_manifest,
)
from .deployment_artifacts import (
    DeploymentArtifactCatalog,
    DeploymentArtifactDefinition,
    ProcessArtifactBinding,
    build_default_deployment_artifact_catalog,
    validate_deployment_artifact_catalog,
)
from .deployment_image_build import OciImageBuildRecord

DEMO_OCI_RELEASE_SCHEMA_VERSION = "p8_demo_oci_release.v1"
DEMO_PACKAGE_CHECK_MODE_ENV = "NEX_DEMO_RUNTIME_CHECK_MODE"
DEMO_PACKAGE_CHECK_MODE = "PACKAGE"
DEMO_BACKGROUND_PROCESS_IDS = (
    "nex-ae-agent-runtime-worker",
    "nex-wc-event-delivery-worker",
    "nex-eos-outbox-publisher",
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class DemoOciReleaseError(ValueError):
    pass


@dataclass(frozen=True)
class DemoPackagedEntrypoint:
    process_id: str
    artifact_id: str
    owner: str
    kind: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class DemoBackgroundContainerCheck:
    process_id: str
    artifact_id: str
    command: tuple[str, ...]
    package_ready: bool
    runtime_ready: bool
    secret_included: bool


def build_demo_deployment_artifact_catalog() -> DeploymentArtifactCatalog:
    historical = build_default_deployment_artifact_catalog()
    additions = (
        DeploymentArtifactDefinition(
            "nex-wc-runtime",
            "nex-wc",
            "python-service",
            "wc-runtime",
            "python-production",
            ("services/_shared/nex_runtime", "services/nex-wc/nex_wc"),
        ),
        DeploymentArtifactDefinition(
            "nex-eos-runtime",
            "nex-eos",
            "python-service",
            "eos-runtime",
            "python-production",
            ("services/_shared/nex_runtime", "services/nex-eos/nex_eos"),
        ),
    )
    entrypoint_ids = {
        "nex-ae-agent-runtime-worker": "agent-runtime-worker",
        "nex-wc-event-delivery-worker": "event-delivery-worker",
        "nex-eos-outbox-publisher": "outbox-publisher",
    }
    bindings = tuple(
        ProcessArtifactBinding(
            item.process_id,
            item.artifact_id,
            entrypoint_ids.get(item.process_id, item.kind),
        )
        for item in build_demo_process_manifest()
        if item.execution_model == "INSTALLED_PROCESS"
    )
    catalog = DeploymentArtifactCatalog(
        historical.schema_version,
        (*historical.artifacts, *additions),
        bindings,
    )
    validate_deployment_artifact_catalog(catalog)
    if {item.artifact_id for item in catalog.artifacts} != set(
        DEMO_APPLICATION_ARTIFACTS
    ):
        raise DemoOciReleaseError("Demo artifact catalog coverage drift")
    return catalog


def build_demo_packaged_entrypoints() -> tuple[DemoPackagedEntrypoint, ...]:
    ports = {
        "nex-oa-api": 8101,
        "nex-ag-api": 8102,
        "nex-ae-api": 8103,
        "nex-cx-api": 8104,
        "nex-mo-api": 8105,
        "nex-wc-api": 8106,
        "nex-eos-api": 8107,
    }
    entries = []
    for binding in build_demo_process_manifest():
        if binding.execution_model != "INSTALLED_PROCESS":
            continue
        command = tuple(binding.command or ())
        if binding.kind == "api":
            command = (*command, "--host", "0.0.0.0", "--port", str(ports[binding.process_id]))
        entries.append(
            DemoPackagedEntrypoint(
                binding.process_id,
                binding.artifact_id,
                binding.owner,
                binding.kind,
                command,
            )
        )
    result = tuple(entries)
    _validate_demo_packaged_entrypoints(result)
    return result


def validate_demo_oci_release(
    *,
    source_revision: str,
    build_inputs_digest: str,
    release_set_digest: str,
    records: Sequence[OciImageBuildRecord],
    background_checks: Sequence[DemoBackgroundContainerCheck],
) -> None:
    catalog = build_demo_deployment_artifact_catalog()
    entries = build_demo_packaged_entrypoints()
    default_commands = {
        item.artifact_id: item.command
        for item in entries
        if item.kind in {"api", "web"}
    }
    expected_artifacts = tuple(item.artifact_id for item in catalog.artifacts)
    errors: list[str] = []
    if not re.fullmatch(r"[0-9a-f]{40}", source_revision):
        errors.append("Demo OCI source revision is invalid")
    if _SHA256.fullmatch(build_inputs_digest) is None:
        errors.append("Demo OCI build inputs digest is invalid")
    if _SHA256.fullmatch(release_set_digest) is None:
        errors.append("Demo OCI release set digest is invalid")
    if tuple(item.artifact_id for item in records) != expected_artifacts:
        errors.append("Demo OCI artifact coverage or order drift")
    manifest_digests: list[str] = []
    image_ids: list[str] = []
    for record in records:
        if record.source_revision != source_revision:
            errors.append(f"Demo OCI source drift: {record.artifact_id}")
        if not _non_root_user(record.runtime_user):
            errors.append(f"Demo OCI privileged runtime: {record.artifact_id}")
        if record.entrypoint:
            errors.append(f"Demo OCI entrypoint drift: {record.artifact_id}")
        if record.command != default_commands.get(record.artifact_id):
            errors.append(f"Demo OCI command drift: {record.artifact_id}")
        if record.image_id not in {record.manifest_digest, record.config_digest}:
            errors.append(f"Demo OCI image identity drift: {record.artifact_id}")
        for label, digest in (
            ("image", record.image_id),
            ("manifest", record.manifest_digest),
            ("config", record.config_digest),
            ("lock", record.dependency_lock_digest),
            ("definition", record.build_definition_digest),
            ("context", record.build_context_digest),
        ):
            if _SHA256.fullmatch(digest) is None:
                errors.append(f"Demo OCI {label} digest invalid: {record.artifact_id}")
        labels = dict(record.labels)
        if labels.get("org.opencontainers.image.revision") != source_revision:
            errors.append(f"Demo OCI revision label drift: {record.artifact_id}")
        if labels.get("io.nex-platform.build-inputs-digest") != build_inputs_digest:
            errors.append(f"Demo OCI inputs label drift: {record.artifact_id}")
        manifest_digests.append(record.manifest_digest)
        image_ids.append(record.image_id)
    if len(manifest_digests) != len(set(manifest_digests)):
        errors.append("Demo OCI manifest digests must be unique")
    if len(image_ids) != len(set(image_ids)):
        errors.append("Demo OCI image IDs must be unique")
    if tuple(item.process_id for item in background_checks) != DEMO_BACKGROUND_PROCESS_IDS:
        errors.append("Demo OCI background package-check coverage drift")
    background_entries = {
        item.process_id: item for item in entries if item.kind == "worker"
    }
    for check in background_checks:
        entry = background_entries.get(check.process_id)
        if entry is None or check.artifact_id != entry.artifact_id:
            errors.append(f"Demo OCI background binding drift: {check.process_id}")
            continue
        if check.command != (*entry.command, "--check"):
            errors.append(f"Demo OCI background command drift: {check.process_id}")
        if not check.package_ready or check.runtime_ready or check.secret_included:
            errors.append(f"Demo OCI background package-check invalid: {check.process_id}")
    if errors:
        raise DemoOciReleaseError("; ".join(errors))


def _validate_demo_packaged_entrypoints(
    entries: Sequence[DemoPackagedEntrypoint],
) -> None:
    installed = {
        item.process_id: item
        for item in build_demo_process_manifest()
        if item.execution_model == "INSTALLED_PROCESS"
    }
    errors: list[str] = []
    if len(entries) != len(installed) or {item.process_id for item in entries} != set(installed):
        errors.append("Demo packaged process coverage drift")
    for entry in entries:
        source = installed.get(entry.process_id)
        if source is None:
            continue
        if (entry.owner, entry.artifact_id, entry.kind) != (
            source.owner,
            source.artifact_id,
            source.kind,
        ):
            errors.append(f"Demo packaged ownership drift: {entry.process_id}")
        if not entry.command or any("tests/" in value for value in entry.command):
            errors.append(f"Demo packaged command invalid: {entry.process_id}")
    if errors:
        raise DemoOciReleaseError("; ".join(errors))


def _non_root_user(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(
        normalized
        and normalized not in {"0", "root"}
        and not normalized.startswith("0:")
        and not normalized.startswith("root:")
    )
