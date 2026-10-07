#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.deployment_artifacts import (  # noqa: E402
    build_default_deployment_artifact_catalog,
)
from nex_runtime.deployment_entrypoints import (  # noqa: E402
    build_packaged_entrypoint_definitions,
    build_packaged_runtime_manifest,
)
from nex_runtime.deployment_image_build import (  # noqa: E402
    BackgroundContainerCheck,
    OCI_BUILD_LABEL_KEYS,
    OciImageBuildRecord,
    build_oci_image_build_evidence,
    oci_image_build_evidence_projection,
)
from nex_runtime.deployment_locks import (  # noqa: E402
    build_deployment_build_inputs,
    deployment_build_inputs_digest,
)
from nex_runtime.deployment_oci import (  # noqa: E402
    OciBuildDefinition,
    build_default_oci_definitions,
    materialize_oci_build_context,
    oci_build_context_digest,
)
from nex_runtime.deployment_provenance import (  # noqa: E402
    collect_deployment_release_manifest,
    deployment_release_manifest_projection,
    oci_build_definition_digest,
)
from nex_runtime.process_manifest import BACKGROUND_PROCESS_IDS  # noqa: E402


SCHEMA_VERSION = "platform_oci_image_build_acceptance.v1"
EXECUTION_ENV = "NEX_PLATFORM_OCI_IMAGE_BUILD"
LOCAL_REPOSITORY = "nex-platform-local"
DEFAULT_REPORT = ROOT / "reports" / "deployment" / "s142-oci-image-build.json"


class PlatformImageBuildError(RuntimeError):
    pass


def run_platform_image_build(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    root: Path = ROOT,
    report_path: Path = DEFAULT_REPORT,
    executor: Callable[[Path, Path], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(EXECUTION_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "1422",
            "requirement": "S142-supplement",
            "status": "SKIPPED",
            "skip_reason": (
                f"--execute and {EXECUTION_ENV}=1 are required."
            ),
        }
    try:
        return dict((executor or _execute_image_build)(root, report_path))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "1422",
            "requirement": "S142-supplement",
            "status": "FAIL",
            "issues": [str(exc)],
            "decision": {
                "release_set_ready": False,
                "registry_push_performed": False,
                "production_contacted": False,
            },
        }


def _execute_image_build(root: Path, report_path: Path) -> dict[str, Any]:
    source_revision, source_tree_clean = _git_metadata(root)
    if not source_tree_clean:
        raise PlatformImageBuildError(
            "OCI release-set build requires a clean source tree"
        )
    docker_server = _docker_preflight(root)
    catalog = build_default_deployment_artifact_catalog()
    inputs = build_deployment_build_inputs(root, catalog=catalog)
    inputs_digest = deployment_build_inputs_digest(inputs)
    definitions = build_default_oci_definitions(catalog)
    locks_by_id = {lock.lock_id: lock for lock in inputs.locks}
    artifacts_by_id = {
        artifact.artifact_id: artifact for artifact in catalog.artifacts
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_directory = report_path.parent / f"{report_path.stem}-logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    records: list[OciImageBuildRecord] = []
    build_logs: dict[str, str] = {}

    with TemporaryDirectory(prefix="nex-platform-oci-build-") as temporary:
        temporary_root = Path(temporary)
        docker_config = temporary_root / "docker-config"
        docker_config.mkdir()
        for index, definition in enumerate(definitions, start=1):
            print(
                f"[{index}/{len(definitions)}] building {definition.artifact_id}",
                file=sys.stderr,
                flush=True,
            )
            context_root = temporary_root / definition.artifact_id
            context = materialize_oci_build_context(
                root, context_root, definition
            )
            metadata_path = temporary_root / f"{definition.artifact_id}.json"
            log_path = log_directory / f"{definition.artifact_id}.log"
            artifact = artifacts_by_id[definition.artifact_id]
            lock = locks_by_id[artifact.dependency_family]
            tag = (
                f"{LOCAL_REPOSITORY}/{definition.artifact_id}:"
                f"{source_revision[:12]}"
            )
            _build_image(
                definition=definition,
                context_root=context_root,
                metadata_path=metadata_path,
                log_path=log_path,
                tag=tag,
                source_revision=source_revision,
                build_inputs_digest=inputs_digest,
                docker_config=docker_config,
                root=root,
            )
            record = _build_record(
                root=root,
                definition=definition,
                artifact=artifact,
                lock=lock,
                context=context,
                metadata_path=metadata_path,
                tag=tag,
                source_revision=source_revision,
                build_inputs_digest=inputs_digest,
            )
            records.append(record)
            build_logs[definition.artifact_id] = (
                f"{log_directory.name}/{log_path.name}"
            )
            print(
                f"[{index}/{len(definitions)}] built {definition.artifact_id} "
                f"manifest={record.manifest_digest}",
                file=sys.stderr,
                flush=True,
            )

    record_by_artifact = {record.artifact_id: record for record in records}
    background_checks = _run_background_checks(
        record_by_artifact,
        root=root,
    )
    image_references = {
        record.artifact_id: record.image_reference for record in records
    }
    release_manifest = collect_deployment_release_manifest(
        root,
        source_revision=source_revision,
        source_tree_clean=source_tree_clean,
        image_references=image_references,
    )
    release_set_digest = _validated_release_set_digest(release_manifest)
    evidence = build_oci_image_build_evidence(
        root=root,
        source_revision=source_revision,
        source_tree_clean=source_tree_clean,
        artifacts=tuple(records),
        background_checks=background_checks,
        release_set_digest=release_set_digest,
    )
    projection = oci_image_build_evidence_projection(evidence)
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1422",
        "requirement": "S142-supplement",
        "status": "PASS",
        "docker_server": docker_server,
        "image_build": projection,
        "release_manifest": deployment_release_manifest_projection(
            release_manifest
        ),
        "build_logs": build_logs,
        "summary": {
            "artifact_count": len(records),
            "manifest_digest_count": len(
                {record.manifest_digest for record in records}
            ),
            "non_root_image_count": sum(
                bool(record.runtime_user) for record in records
            ),
            "background_check_count": len(background_checks),
            "release_set_ready": True,
        },
        "decision": {
            "release_set_ready": True,
            "registry_push_performed": False,
            "production_contacted": False,
            "production_deployment_approved": False,
            "next_requirement": "S143",
        },
    }


def _build_image(
    *,
    definition: OciBuildDefinition,
    context_root: Path,
    metadata_path: Path,
    log_path: Path,
    tag: str,
    source_revision: str,
    build_inputs_digest: str,
    docker_config: Path,
    root: Path,
) -> None:
    command = (
        "docker",
        "buildx",
        "build",
        "--load",
        "--pull",
        "--provenance=false",
        "--sbom=false",
        "--platform",
        definition.platform,
        "--file",
        str(context_root / "Containerfile"),
        "--target",
        definition.target,
        "--tag",
        tag,
        "--build-arg",
        f"NEX_VERSION={source_revision[:12]}",
        "--build-arg",
        f"NEX_REVISION={source_revision}",
        "--build-arg",
        f"NEX_BUILD_INPUTS_DIGEST={build_inputs_digest}",
        "--metadata-file",
        str(metadata_path),
        str(context_root),
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["DOCKER_CONFIG"] = str(docker_config)
    with log_path.open("w", encoding="utf-8") as output:
        completed = subprocess.run(
            command,
            cwd=root,
            check=False,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
            env=environment,
        )
    if completed.returncode != 0:
        raise PlatformImageBuildError(
            f"OCI image build failed: {definition.artifact_id}"
        )


def _build_record(
    *,
    root: Path,
    definition: OciBuildDefinition,
    artifact: Any,
    lock: Any,
    context: Any,
    metadata_path: Path,
    tag: str,
    source_revision: str,
    build_inputs_digest: str,
) -> OciImageBuildRecord:
    metadata = _read_object(metadata_path, "BuildKit metadata")
    manifest_digest = _manifest_digest(metadata)
    inspection = _inspect_image(tag, root=root)
    image_id = _required_digest(inspection.get("Id"), "image ID")
    config_digest = metadata.get("containerimage.config.digest")
    if config_digest is not None and config_digest != image_id:
        raise PlatformImageBuildError(
            f"image config digest drift: {definition.artifact_id}"
        )
    config = inspection.get("Config")
    if not isinstance(config, dict):
        raise PlatformImageBuildError(
            f"image configuration missing: {definition.artifact_id}"
        )
    labels = config.get("Labels") or {}
    if not isinstance(labels, dict):
        raise PlatformImageBuildError(
            f"image labels invalid: {definition.artifact_id}"
        )
    return OciImageBuildRecord(
        artifact_id=definition.artifact_id,
        owner=artifact.owner,
        target=definition.target,
        local_tag=tag,
        image_id=image_id,
        manifest_digest=manifest_digest,
        image_reference=(
            f"{LOCAL_REPOSITORY}/{definition.artifact_id}@{manifest_digest}"
        ),
        base_image_reference=definition.base_image,
        source_revision=source_revision,
        dependency_lock_id=lock.lock_id,
        dependency_lock_digest=f"sha256:{lock.sha256}",
        build_definition_digest=oci_build_definition_digest(root, definition),
        build_context_digest=oci_build_context_digest(context),
        platform=definition.platform,
        runtime_user=str(config.get("User") or ""),
        entrypoint=_string_tuple(config.get("Entrypoint")),
        command=_string_tuple(config.get("Cmd")),
        labels=tuple(
            (key, str(labels.get(key) or "")) for key in OCI_BUILD_LABEL_KEYS
        ),
    )


def _validated_release_set_digest(release_manifest: Any) -> str:
    if release_manifest.status != "RELEASE_SET_READY":
        raise PlatformImageBuildError("complete OCI release set was not admitted")
    if release_manifest.release_set_digest is None:
        raise PlatformImageBuildError("OCI release set digest is missing")
    return _required_digest(release_manifest.release_set_digest, "release set digest")


def _run_background_checks(
    records: Mapping[str, OciImageBuildRecord],
    *,
    root: Path,
) -> tuple[BackgroundContainerCheck, ...]:
    catalog = build_default_deployment_artifact_catalog()
    manifest = build_packaged_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    entries = {
        entry.process_id: entry
        for entry in build_packaged_entrypoint_definitions(manifest, catalog)
    }
    checks = []
    for index, process_id in enumerate(BACKGROUND_PROCESS_IDS, start=1):
        entry = entries[process_id]
        record = records[entry.artifact_id]
        command = (*entry.command, "--check")
        print(
            f"[{index}/{len(BACKGROUND_PROCESS_IDS)}] checking {process_id}",
            file=sys.stderr,
            flush=True,
        )
        completed = _run_capture(
            (
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                "none",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
                record.local_tag,
                *command,
            ),
            cwd=root,
            operation=f"background container check: {process_id}",
        )
        payload = _last_json_object(completed.stdout, process_id)
        checks.append(
            BackgroundContainerCheck(
                process_id=process_id,
                artifact_id=entry.artifact_id,
                command=command,
                profile=str(payload.get("profile") or ""),
                persistence_mode=str(payload.get("persistence_mode") or ""),
                lifecycle_ready=payload.get("lifecycle_ready") is True,
                work_claiming_enabled=(
                    payload.get("work_claiming_enabled") is True
                ),
            )
        )
    return tuple(checks)


def _docker_preflight(root: Path) -> dict[str, str]:
    completed = _run_capture(
        (
            "docker",
            "version",
            "--format",
            "{{json .Server}}",
        ),
        cwd=root,
        operation="Docker daemon preflight",
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PlatformImageBuildError("Docker daemon metadata is invalid") from exc
    if not isinstance(payload, dict) or not payload.get("Version"):
        raise PlatformImageBuildError("Docker daemon metadata is incomplete")
    return {
        "version": str(payload["Version"]),
        "api_version": str(payload.get("ApiVersion") or ""),
        "os": str(payload.get("Os") or ""),
        "architecture": str(payload.get("Arch") or ""),
    }


def _inspect_image(tag: str, *, root: Path) -> dict[str, Any]:
    completed = _run_capture(
        ("docker", "image", "inspect", tag),
        cwd=root,
        operation=f"image inspection: {tag.split(':', 1)[0]}",
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PlatformImageBuildError("Docker image inspection is invalid") from exc
    if not isinstance(payload, list) or len(payload) != 1:
        raise PlatformImageBuildError("Docker image inspection is incomplete")
    inspection = payload[0]
    if not isinstance(inspection, dict):
        raise PlatformImageBuildError("Docker image inspection object is invalid")
    return inspection


def _run_capture(
    command: Sequence[str],
    *,
    cwd: Path,
    operation: str,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        tuple(command),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise PlatformImageBuildError(f"{operation} failed")
    return completed


def _git_metadata(root: Path) -> tuple[str, bool]:
    revision = _run_capture(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        operation="Git revision lookup",
    ).stdout.strip()
    status = _run_capture(
        ("git", "status", "--porcelain", "--untracked-files=all"),
        cwd=root,
        operation="Git worktree status",
    ).stdout
    if len(revision) != 40:
        raise PlatformImageBuildError("Git source revision is invalid")
    return revision, not bool(status.strip())


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlatformImageBuildError(f"{label} is unavailable") from exc
    if not isinstance(payload, dict):
        raise PlatformImageBuildError(f"{label} is invalid")
    return payload


def _manifest_digest(metadata: Mapping[str, Any]) -> str:
    value = metadata.get("containerimage.digest")
    if value is None:
        descriptor = metadata.get("containerimage.descriptor")
        if isinstance(descriptor, dict):
            value = descriptor.get("digest")
    return _required_digest(value, "manifest digest")


def _required_digest(value: Any, label: str) -> str:
    digest = str(value or "")
    if (
        not digest.startswith("sha256:")
        or len(digest) != 71
        or any(character not in "0123456789abcdef" for character in digest[7:])
    ):
        raise PlatformImageBuildError(f"{label} is invalid")
    return digest


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PlatformImageBuildError("image command metadata is invalid")
    return tuple(value)


def _last_json_object(output: str, process_id: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            if payload.get("process_id") != process_id:
                raise PlatformImageBuildError(
                    f"background container identity drift: {process_id}"
                )
            return payload
    raise PlatformImageBuildError(
        f"background container output is invalid: {process_id}"
    )


def _write_report(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    status = result.get("status")
    if status == "SKIPPED":
        return "platform_oci_image_build=skipped"
    if status != "PASS":
        return f"platform_oci_image_build=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_oci_image_build=pass "
        f"artifacts={summary.get('artifact_count', 0)} "
        f"manifests={summary.get('manifest_digest_count', 0)} "
        f"non_root={summary.get('non_root_image_count', 0)} "
        f"background={summary.get('background_check_count', 0)} "
        f"release_set={str(summary.get('release_set_ready', False)).lower()} "
        f"registry_push={str(decision.get('registry_push_performed', False)).lower()}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_image_build(
        execute=args.execute,
        report_path=args.report,
    )
    if result.get("status") != "SKIPPED":
        _write_report(args.report, result)
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
