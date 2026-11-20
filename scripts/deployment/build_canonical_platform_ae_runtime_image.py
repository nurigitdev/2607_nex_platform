#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))

from nex_runtime.deployment_artifacts import build_default_deployment_artifact_catalog
from nex_runtime.deployment_locks import (
    build_deployment_build_inputs,
    deployment_build_inputs_digest,
)
from nex_runtime.deployment_oci import (
    build_default_oci_definitions,
    materialize_oci_build_context,
    oci_build_context_digest,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

DEFAULT_MANIFEST = ROOT / "deployment/locks/nsl-v0.2.1-wheel.json"
DEFAULT_WHEEL = (
    ROOT
    / "reports/deployment/p8-nsl-v0.2.1-wheel"
    / "nex_skill_language-0.2.1-py3-none-any.whl"
)
DEFAULT_NSL_SOURCE = Path("/home/tprover/2608_nsl")
DEFAULT_REPORT = ROOT / "reports/deployment/canonical-platform-ae-runtime-image.json"
M1_ADMISSION_LOCK = ROOT / "deployment/locks/ae-mybee-m1-runtime-admission.v4.json"
M1_ACTIVATION_LOCK = ROOT / "deployment/locks/ae-mybee-m1-runtime-activation.v4.json"


class CanonicalPlatformAeImageBuildError(RuntimeError):
    pass


def build_canonical_platform_ae_runtime_image(
    *,
    base_image: str,
    output_image: str,
    wheel_path: Path = DEFAULT_WHEEL,
    nsl_source: Path = DEFAULT_NSL_SOURCE,
    manifest_path: Path = DEFAULT_MANIFEST,
    report_path: Path = DEFAULT_REPORT,
    build_current_base: bool = False,
    execute: bool,
) -> dict[str, Any]:
    del nsl_source
    readiness = _wheel_readiness(wheel_path, manifest_path)
    if not execute:
        return _record(
            status="READY",
            base_image=base_image,
            output_image=output_image,
            readiness=readiness,
            image=None,
            source_base=None,
        )

    with TemporaryDirectory(prefix="canonical-platform-ae-image-") as temporary:
        temporary_root = Path(temporary)
        resolved_base = base_image
        source_base = None
        if build_current_base:
            resolved_base, source_base = _build_current_ae_base(
                temporary_root / "source-base",
                output_image=output_image,
            )
        context = temporary_root / "runtime-bundle"
        context.mkdir()
        _stage_context(
            context,
            wheel_path=wheel_path,
            wheel_filename=str(readiness["wheel_filename"]),
        )
        subprocess.run(
            [
                "docker",
                "build",
                "--pull=false",
                "--file",
                str(context / "Containerfile"),
                "--build-arg",
                f"NEX_AE_BASE_RUNTIME_IMAGE={resolved_base}",
                "--tag",
                output_image,
                str(context),
            ],
            cwd=ROOT,
            check=True,
        )
    inspection = _json_command(["docker", "image", "inspect", output_image])
    if not isinstance(inspection, list) or len(inspection) != 1:
        raise CanonicalPlatformAeImageBuildError(
            "Canonical AE image inspection is invalid."
        )
    item = inspection[0]
    config = item.get("Config") if isinstance(item, Mapping) else None
    if not isinstance(config, Mapping) or config.get("User") != "65532:65532":
        raise CanonicalPlatformAeImageBuildError(
            "Canonical AE image must retain the non-root user."
        )
    image = {
        "image_id": str(item.get("Id")),
        "repo_digests": sorted(str(value) for value in item.get("RepoDigests") or ()),
        "runtime_user": config["User"],
    }
    record = _record(
        status="PASS",
        base_image=base_image,
        output_image=output_image,
        readiness=readiness,
        image=image,
        source_base=source_base,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return record


def _build_current_ae_base(
    context: Path,
    *,
    output_image: str,
) -> tuple[str, dict[str, Any]]:
    catalog = build_default_deployment_artifact_catalog()
    definition = next(
        item
        for item in build_default_oci_definitions(catalog)
        if item.artifact_id == "nex-ae-runtime"
    )
    manifest = materialize_oci_build_context(ROOT, context, definition)
    context_digest = oci_build_context_digest(manifest)
    inputs_digest = deployment_build_inputs_digest(
        build_deployment_build_inputs(ROOT, catalog=catalog)
    )
    revision = _text_command(["git", "rev-parse", "HEAD"]).strip()
    tag = f"{output_image}-source"
    subprocess.run(
        [
            "docker",
            "build",
            "--pull=false",
            "--file",
            str(context / "Containerfile"),
            "--target",
            definition.target,
            "--build-arg",
            f"NEX_VERSION={revision[:12]}",
            "--build-arg",
            f"NEX_REVISION={revision}",
            "--build-arg",
            f"NEX_BUILD_INPUTS_DIGEST={inputs_digest}",
            "--tag",
            tag,
            str(context),
        ],
        cwd=ROOT,
        check=True,
    )
    inspection = _single_image_inspection(tag)
    return tag, {
        "image": tag,
        "image_id": str(inspection.get("Id") or ""),
        "source_revision": revision,
        "source_context_digest": context_digest,
        "build_inputs_digest": inputs_digest,
        "artifact_id": definition.artifact_id,
        "target": definition.target,
    }


def _stage_context(
    context: Path,
    *,
    wheel_path: Path,
    wheel_filename: str,
) -> None:
    (context / "config").mkdir()
    (context / "wheel").mkdir()
    (context / "repository").mkdir()
    shutil.copy2(
        ROOT / "deployment/oci/canonical-platform-ae-runtime.Containerfile",
        context / "Containerfile",
    )
    shutil.copy2(
        ROOT / "deployment/product/config/project-agent-profile-policy.v1.json",
        context / "config/project-agent-profile-policy.v1.json",
    )
    shutil.copy2(wheel_path, context / "wheel" / wheel_filename)
    for relative in (
        "deployment/locks/ae-mybee-m1-runtime-admission.v4.json",
        "deployment/locks/ae-mybee-m1-runtime-admission.v3.json",
        "deployment/locks/ae-mybee-m1-runtime-admission.v2.json",
        "deployment/locks/ae-mybee-m1-runtime-activation.v4.json",
        "deployment/locks/ae-mybee-m1-runtime-activation.v3.json",
        "deployment/locks/ae-mybee-m1-runtime-activation.v2.json",
        "deployment/locks/ae-mybee-m1-generalized-rollback.v3.json",
        "deployment/locks/ae-mybee-m1-generalized-rollback.v2.json",
        "deployment/locks/ae-mybee-m1-generalized-rollback.v1.json",
        "deployment/locks/ae-mybee-m1-product-coordinator-activation.v3.json",
        "deployment/locks/ae-mybee-m1-product-coordinator-activation.v2.json",
        "deployment/locks/ae-mybee-m1-product-coordinator-activation.v1.json",
        "deployment/locks/ae-mybee-m1-product-coordinator-rollback.v3.json",
        "deployment/locks/ae-mybee-m1-product-coordinator-rollback.v2.json",
        "deployment/locks/ae-mybee-m1-product-coordinator-rollback.v1.json",
        "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v3.json",
        "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v2.json",
        "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v1.json",
        "deployment/locks/nsl-v0.2.1-wheel.json",
        "deployment/locks/python-production.lock",
        "deployment/environments/ae-product-capability-registry.mybee-m1.v4.json",
        "deployment/environments/ae-product-capability-registry.mybee-m1.v1.json",
        "deployment/environments/ae-product-capability-registry.mybee-m1.v2.json",
        "deployment/environments/ae-product-capability-registry.mybee-m1.v3.json",
        "domains/mybee/config/m1_transaction_preparation_registry.v1.json",
        "domains/mybee/skills/m1_checkpoint/context.json",
        "domains/mybee/skills/m1_checkpoint/mybee-m1-d04-d12.v3.nsp",
        "domains/mybee/skills/m1_checkpoint/mybee-m1-d04-d12.v2.nsp",
        "domains/mybee/skills/m1_checkpoint/mybee-m1-d04-d12.v1.nsp",
        "domains/mybee/skills/m1_checkpoint/mybee-m1-release-public-key.v3.json",
        "domains/mybee/skills/m1_checkpoint/mybee-m1-release-public-key.v2.json",
        "domains/mybee/skills/m1_checkpoint/mybee-m1-release-public-key.v1.json",
        "domains/mybee/skills/m1_checkpoint/tool_catalog.v1.json",
        "domains/mybee/skills/d04_accounting/journal_posting.v1_0_2.ns",
        "domains/mybee/skills/d04_accounting/journal_posting.v1_0_1.ns",
        "domains/mybee/skills/d04_accounting/journal_posting.v1.ns",
        "domains/mybee/skills/d04_accounting/manifest.v1.json",
        "domains/mybee/skills/d04_accounting/tool_bindings.v1.json",
        "domains/mybee/skills/d12_project/work_code_context.v1.ns",
        "domains/mybee/skills/d12_project/manifest.v1.json",
        "domains/mybee/skills/d12_project/tool_bindings.v1.json",
        "domains/mybee/skills/tool_inventory.v1.json",
        "contracts/admissions/nex_eos/w70_tool_contract_admission.v1.json",
        "contracts/openapi/nex-eos.openapi.yaml",
        "domains/mybee/catalog/work_codes/catalog.v1.json",
        "domains/mybee/catalog/work_codes/schema.json",
    ):
        source = ROOT / relative
        target = context / "repository" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copytree(
        ROOT / "contracts/schemas/service/nex_eos",
        context / "repository/contracts/schemas/service/nex_eos",
    )


def _record(
    *,
    status: str,
    base_image: str,
    output_image: str,
    readiness: Mapping[str, Any],
    image: Mapping[str, Any] | None,
    source_base: Mapping[str, Any] | None,
) -> dict[str, Any]:
    admission = json.loads(M1_ADMISSION_LOCK.read_text(encoding="utf-8"))
    activation = json.loads(M1_ACTIVATION_LOCK.read_text(encoding="utf-8"))
    payload = {
        "schema_version": "canonical_platform_ae_runtime_image.v1",
        "slice": "GB2-CA00-S18A",
        "status": status,
        "base_image": base_image,
        "output_image": output_image,
        "bundle": dict(readiness),
        "bundle_role": "GENERALIZED_M1_RELEASE",
        "active_runtime_profile": activation["runtime_profile"],
        "verified_product_release": {
            "activation_state": activation["activation_state"],
            "activation_hash": activation["content_hash"],
            "admission_hash": admission["content_hash"],
            "release_id": admission["release_id"],
            "release_hash": admission["release_hash"],
            "package_hash": admission["package_hash"],
            "skill_catalog_hash": admission["skill_catalog_hash"],
            "runtime_selectable_capabilities": admission[
                "runtime_selectable_capabilities"
            ],
            "rollback_target": activation["rollback_target"],
        },
        "source_base": None if source_base is None else dict(source_base),
        "image": None if image is None else dict(image),
        "registry_push_performed": False,
        "secret_included": False,
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    return {**payload, "evidence_hash": semantic_sha256_hash_ref(payload)}


def _wheel_readiness(wheel_path: Path, lock_path: Path) -> dict[str, Any]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if not isinstance(lock, Mapping) or lock.get("schema_version") != "nsl_wheel_lock.v2":
        raise CanonicalPlatformAeImageBuildError("NSL wheel lock is invalid.")
    expected_name = str(lock.get("wheel_filename") or "")
    expected_hash = str(lock.get("wheel_sha256") or "")
    if wheel_path.name != expected_name:
        raise CanonicalPlatformAeImageBuildError("NSL wheel filename has drifted.")
    observed_hash = "sha256:" + hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    if observed_hash != expected_hash or wheel_path.stat().st_size != lock.get(
        "wheel_size"
    ):
        raise CanonicalPlatformAeImageBuildError("NSL wheel admission has drifted.")
    return {
        "status": "PASS",
        "wheel_filename": expected_name,
        "wheel_sha256": observed_hash,
        "package_version": lock.get("package_version"),
        "source_revision": lock.get("source_revision"),
        "historical_scenario_dependency": False,
    }


def _json_command(command: Sequence[str]) -> Any:
    completed = subprocess.run(
        list(command), cwd=ROOT, check=True, capture_output=True, text=True
    )
    return json.loads(completed.stdout)


def _text_command(command: Sequence[str]) -> str:
    completed = subprocess.run(
        list(command), cwd=ROOT, check=True, capture_output=True, text=True
    )
    return completed.stdout


def _single_image_inspection(image: str) -> Mapping[str, Any]:
    inspection = _json_command(["docker", "image", "inspect", image])
    if not isinstance(inspection, list) or len(inspection) != 1:
        raise CanonicalPlatformAeImageBuildError(
            "Canonical AE image inspection is invalid."
        )
    item = inspection[0]
    if not isinstance(item, Mapping):
        raise CanonicalPlatformAeImageBuildError(
            "Canonical AE image inspection is invalid."
        )
    return item


P8DemoAeImageBuildError = CanonicalPlatformAeImageBuildError
build_p8_demo_ae_runtime_image = build_canonical_platform_ae_runtime_image


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--output-image", required=True)
    parser.add_argument("--wheel", type=Path, default=DEFAULT_WHEEL)
    parser.add_argument("--nsl-source", type=Path, default=DEFAULT_NSL_SOURCE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--build-current-base", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = build_canonical_platform_ae_runtime_image(
            base_image=args.base_image,
            output_image=args.output_image,
            wheel_path=args.wheel,
            nsl_source=args.nsl_source,
            manifest_path=args.manifest,
            report_path=args.report,
            build_current_base=args.build_current_base,
            execute=args.execute,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {
            "schema_version": "canonical_platform_ae_runtime_image.v1",
            "slice": "GB2-CA00-S18A",
            "status": "FAIL",
            "detail": str(exc),
            "registry_push_performed": False,
            "secret_included": False,
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"READY", "PASS"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
