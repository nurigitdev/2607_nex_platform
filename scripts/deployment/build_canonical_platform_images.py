#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "scripts" / "deployment"))
for service_directory in (
    "nex-oa",
    "nex-ag",
    "nex-ae-api",
    "nex-cx",
    "nex-mo",
    "nex-wc",
    "nex-eos",
):
    sys.path.insert(0, str(ROOT / "services" / service_directory))

import build_platform_images as image_build
from nex_runtime.deployment_artifacts import (
    build_current_deployment_artifact_catalog,
)
from nex_runtime.deployment_entrypoints import (
    build_current_packaged_runtime_manifest,
    build_packaged_entrypoint_definitions,
)
from nex_runtime.deployment_image_build import (
    OCI_IMAGE_BUILD_EVIDENCE_SCHEMA_VERSION,
    OCI_IMAGE_BUILD_STATUS,
    OciImageBuildEvidence,
    oci_image_build_evidence_projection,
    packaged_image_default_command,
)
from nex_runtime.deployment_locks import (
    build_deployment_build_inputs,
    deployment_build_inputs_digest,
)
from nex_runtime.deployment_oci import (
    build_current_oci_definitions,
    materialize_oci_build_context,
    validate_oci_containerfiles,
)
from nex_runtime.deployment_provenance import (
    collect_deployment_release_manifest,
    deployment_release_manifest_projection,
)
from nex_runtime.process_manifest import (
    BACKGROUND_PROCESS_IDS,
    CURRENT_BACKGROUND_PROCESS_IDS,
)
from nex_runtime.runtime_package_admission import (
    RUNTIME_CHECK_MODE_ENV,
    RUNTIME_PACKAGE_CHECK_MODE,
)

EXECUTION_ENV = "NEX_CANONICAL_PLATFORM_OCI_IMAGE_BUILD"
SCHEMA_VERSION = "canonical_platform_oci_release.v1"
DEFAULT_REPORT = (
    ROOT / "reports" / "deployment" / "canonical-platform-oci-image-build.json"
)


def run_canonical_platform_image_build(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    root: Path = ROOT,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(EXECUTION_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"--execute and {EXECUTION_ENV}=1 are required.",
        }
    try:
        return _execute_canonical_platform_image_build(root, report_path)
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "issues": [str(exc)],
            "decision": {
                "release_set_ready": False,
                "registry_push_performed": False,
                "production_contacted": False,
            },
        }


def _execute_canonical_platform_image_build(
    root: Path, report_path: Path
) -> dict[str, Any]:
    catalog = build_current_deployment_artifact_catalog()
    definitions = build_current_oci_definitions()
    validate_oci_containerfiles(root, definitions)
    source_revision, source_tree_clean, excluded_untracked_count = _git_metadata(
        root, definitions
    )
    if not source_tree_clean:
        raise image_build.PlatformImageBuildError(
            "Canonical Platform OCI build requires clean tracked and build-context sources"
        )
    docker_server = image_build._docker_preflight(root)
    inputs = build_deployment_build_inputs(root, catalog=catalog)
    inputs_digest = deployment_build_inputs_digest(inputs)
    locks_by_id = {item.lock_id: item for item in inputs.locks}
    artifacts_by_id = {item.artifact_id: item for item in catalog.artifacts}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_directory = report_path.parent / f"{report_path.stem}-logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    records = []
    build_logs: dict[str, str] = {}

    with TemporaryDirectory(prefix="nex-canonical-platform-oci-") as temporary:
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
            context = materialize_oci_build_context(root, context_root, definition)
            metadata_path = temporary_root / f"{definition.artifact_id}.json"
            log_path = log_directory / f"{definition.artifact_id}.log"
            artifact = artifacts_by_id[definition.artifact_id]
            lock = locks_by_id[artifact.dependency_family]
            tag = f"nex-platform-canonical/{definition.artifact_id}:{source_revision[:12]}"
            image_build._build_image(
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
            record = image_build._build_record(
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
            build_logs[definition.artifact_id] = f"{log_directory.name}/{log_path.name}"
            print(
                f"[{index}/{len(definitions)}] built {definition.artifact_id} "
                f"manifest={record.manifest_digest}",
                file=sys.stderr,
                flush=True,
            )

    record_by_artifact = {item.artifact_id: item for item in records}
    background_checks = image_build._run_background_checks(
        record_by_artifact,
        root=root,
    )
    package_checks = _run_canonical_package_checks(
        record_by_artifact,
        root=root,
    )
    image_references = {item.artifact_id: item.image_reference for item in records}
    release_manifest = collect_deployment_release_manifest(
        root,
        source_revision=source_revision,
        source_tree_clean=True,
        image_references=image_references,
        catalog=catalog,
    )
    release_set_digest = image_build._validated_release_set_digest(release_manifest)
    _validate_canonical_release(
        source_revision=source_revision,
        build_inputs_digest=inputs_digest,
        release_set_digest=release_set_digest,
        records=records,
        package_checks=package_checks,
    )
    generic_evidence = OciImageBuildEvidence(
        schema_version=OCI_IMAGE_BUILD_EVIDENCE_SCHEMA_VERSION,
        status=OCI_IMAGE_BUILD_STATUS,
        source_revision=source_revision,
        source_tree_clean=True,
        build_inputs_digest=inputs_digest,
        artifacts=tuple(records),
        background_checks=background_checks,
        release_set_digest=release_set_digest,
        registry_push_performed=False,
        production_contacted=False,
    )
    image_projection = oci_image_build_evidence_projection(generic_evidence)
    image_projection["schema_version"] = SCHEMA_VERSION
    image_projection["domain_background_package_checks"] = [
        {
            **item,
            "command": list(item["command"]),
        }
        for item in package_checks
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "GB2-CA00-S18A",
        "status": "PASS",
        "source_revision": source_revision,
        "docker_server": docker_server,
        "image_build": image_projection,
        "release_manifest": deployment_release_manifest_projection(release_manifest),
        "build_logs": build_logs,
        "excluded_untracked_count": excluded_untracked_count,
        "summary": {
            "artifact_count": len(records),
            "manifest_digest_count": len({item.manifest_digest for item in records}),
            "non_root_image_count": sum(bool(item.runtime_user) for item in records),
            "background_check_count": len(background_checks) + len(package_checks),
            "release_set_ready": True,
        },
        "decision": {
            "release_set_ready": True,
            "registry_push_performed": False,
            "production_contacted": False,
            "next_slice": "GB2-CA00-S19",
        },
    }


def _run_canonical_package_checks(
    records: Mapping[str, Any], *, root: Path
) -> tuple[dict[str, Any], ...]:
    catalog = build_current_deployment_artifact_catalog()
    manifest = build_current_packaged_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    entries = {
        item.process_id: item
        for item in build_packaged_entrypoint_definitions(manifest, catalog)
    }
    process_ids = tuple(
        item
        for item in CURRENT_BACKGROUND_PROCESS_IDS
        if item not in BACKGROUND_PROCESS_IDS
    )
    checks = []
    for index, process_id in enumerate(process_ids, start=1):
        entry = entries[process_id]
        record = records[entry.artifact_id]
        command = (*entry.command, "--check")
        print(
            f"[{index}/{len(process_ids)}] package-checking {process_id}",
            file=sys.stderr,
            flush=True,
        )
        completed = image_build._run_capture(
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
                "--env",
                f"{RUNTIME_CHECK_MODE_ENV}={RUNTIME_PACKAGE_CHECK_MODE}",
                record.local_tag,
                *command,
            ),
            cwd=root,
            operation=f"Canonical Platform package check: {process_id}",
        )
        payload = image_build._last_json_object(completed.stdout, process_id)
        checks.append(
            {
                "process_id": process_id,
                "artifact_id": entry.artifact_id,
                "command": command,
                "package_ready": payload.get("package_ready") is True,
                "runtime_ready": payload.get("runtime_ready") is True,
                "secret_included": payload.get("secret_included") is True,
            }
        )
    return tuple(checks)


def _validate_canonical_release(
    *,
    source_revision: str,
    build_inputs_digest: str,
    release_set_digest: str,
    records: Sequence[Any],
    package_checks: Sequence[Mapping[str, Any]],
) -> None:
    catalog = build_current_deployment_artifact_catalog()
    manifest = build_current_packaged_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    entries = build_packaged_entrypoint_definitions(manifest, catalog)
    expected_commands = {
        item.artifact_id: packaged_image_default_command(item)
        for item in entries
        if item.kind in {"api", "web"}
    }
    errors: list[str] = []
    expected_artifacts = tuple(item.artifact_id for item in catalog.artifacts)
    if tuple(item.artifact_id for item in records) != expected_artifacts:
        errors.append("canonical artifact coverage or order drift")
    if re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        errors.append("canonical source revision is invalid")
    for label, value in (
        ("build inputs", build_inputs_digest),
        ("release set", release_set_digest),
    ):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
            errors.append(f"canonical {label} digest is invalid")
    for record in records:
        if record.source_revision != source_revision:
            errors.append(f"canonical source drift: {record.artifact_id}")
        if record.entrypoint:
            errors.append(f"canonical entrypoint drift: {record.artifact_id}")
        if record.command != expected_commands.get(record.artifact_id):
            errors.append(f"canonical command drift: {record.artifact_id}")
        if not _non_root_user(record.runtime_user):
            errors.append(f"canonical privileged runtime: {record.artifact_id}")
    direct_processes = tuple(
        item
        for item in CURRENT_BACKGROUND_PROCESS_IDS
        if item not in BACKGROUND_PROCESS_IDS
    )
    if tuple(item.get("process_id") for item in package_checks) != direct_processes:
        errors.append("canonical domain package-check coverage drift")
    for item in package_checks:
        process_id = str(item.get("process_id") or "unknown")
        if not item.get("package_ready"):
            errors.append(f"canonical package is not ready: {process_id}")
        if item.get("runtime_ready") or item.get("secret_included"):
            errors.append(f"canonical package check is not isolated: {process_id}")
    if errors:
        raise image_build.PlatformImageBuildError("; ".join(errors))


def _non_root_user(value: str) -> bool:
    account = value.strip().lower().split(":", 1)[0]
    return account not in {"", "0", "root"}


def _git_metadata(root: Path, definitions: Sequence[Any]) -> tuple[str, bool, int]:
    revision = image_build._run_capture(
        ("git", "rev-parse", "HEAD"), cwd=root, operation="Git revision lookup"
    ).stdout.strip()
    tracked = image_build._run_capture(
        ("git", "status", "--porcelain", "--untracked-files=no"),
        cwd=root,
        operation="Git tracked status",
    ).stdout.splitlines()
    untracked = image_build._run_capture(
        ("git", "ls-files", "--others", "--exclude-standard"),
        cwd=root,
        operation="Git untracked inventory",
    ).stdout.splitlines()
    admitted_paths = {
        value
        for definition in definitions
        for value in (definition.containerfile, *definition.context_paths)
    }
    relevant_untracked = [
        path
        for path in untracked
        if any(
            path == root_path or path.startswith(f"{root_path}/")
            for root_path in admitted_paths
        )
    ]
    clean = (
        not tracked
        and not relevant_untracked
        and bool(re.fullmatch(r"[0-9a-f]{40}", revision))
    )
    return revision, clean, len(untracked) - len(relevant_untracked)


def _write_report(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "canonical_platform_oci_image_build=skipped"
    if result.get("status") != "PASS":
        return f"canonical_platform_oci_image_build=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    return (
        "canonical_platform_oci_image_build=pass "
        f"artifacts={summary.get('artifact_count', 0)} "
        f"manifests={summary.get('manifest_digest_count', 0)} "
        f"non_root={summary.get('non_root_image_count', 0)} "
        f"background={summary.get('background_check_count', 0)} "
        f"release_set={str(summary.get('release_set_ready', False)).lower()} "
        "registry_push=false"
    )


run_p8_demo_image_build = run_canonical_platform_image_build
_execute_p8_demo_image_build = _execute_canonical_platform_image_build


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the Canonical Platform nine-image release set."
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = run_canonical_platform_image_build(
        execute=args.execute, report_path=args.report
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
