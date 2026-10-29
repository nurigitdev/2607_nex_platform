#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
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

from nex_runtime.current_platform_installation import (
    admit_current_platform_installation,
)
from nex_runtime.deployment_environments import (
    CURRENT_ARTIFACT_REFERENCE_ENVIRONMENTS,
)

EXECUTION_ENV = "NEX_CANONICAL_PLATFORM_COMPOSE_RENDER"
CALIBRATION_ENV = "NEX_CANONICAL_PLATFORM_SEMANTIC_CALIBRATION_POLICIES_JSON"
LEGACY_CALIBRATION_ENV = "NEX_P8_DEMO_SEMANTIC_CALIBRATION_POLICIES_JSON"
SCHEMA_VERSION = "canonical_platform_compose.v1"
BASE_COMPOSE = ROOT / "deployment/compose/s143-staging.compose.yaml"
OBJECT_COMPOSE = ROOT / "deployment/compose/s146-object-storage.override.yaml"
CANONICAL_COMPOSE = ROOT / "deployment/compose/canonical-platform.override.yaml"
WA_COMPOSE = ROOT / "deployment/compose/p9-wa.override.yaml"
DEFAULT_IMAGE_REPORT = (
    ROOT / "reports/deployment/canonical-platform-oci-image-build.json"
)
DEFAULT_REPORT = ROOT / "reports/deployment/canonical-platform-compose-render.json"


def check_canonical_platform_compose(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    root: Path = ROOT,
    image_report_path: Path = DEFAULT_IMAGE_REPORT,
    executor: Any = subprocess.run,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    source = admit_current_platform_installation(root)
    if not execute or env.get(EXECUTION_ENV) != "1":
        return {**source, "status": "SOURCE_ADMITTED", "rendered": False}
    try:
        image_report = json.loads(image_report_path.read_text(encoding="utf-8"))
        image_environment = _image_environment_from_release_report(image_report)
        with TemporaryDirectory(prefix="nex-canonical-platform-compose-") as temporary:
            runtime_dir = Path(temporary) / "runtime"
            runtime_dir.mkdir()
            command = (
                "docker",
                "compose",
                "-f",
                str(root / BASE_COMPOSE.relative_to(ROOT)),
                "-f",
                str(root / OBJECT_COMPOSE.relative_to(ROOT)),
                "-f",
                str(root / CANONICAL_COMPOSE.relative_to(ROOT)),
                "-f",
                str(root / WA_COMPOSE.relative_to(ROOT)),
                "config",
                "--format",
                "yaml",
            )
            completed = executor(
                command,
                cwd=root,
                env={
                    **_canonical_environment(env, default_calibration="[]"),
                    **image_environment,
                    "NEX_S143_RUNTIME_DIR": str(runtime_dir),
                },
                check=False,
                capture_output=True,
                text=True,
            )
        if completed.returncode != 0:
            raise ValueError("Canonical Platform Docker Compose render failed")
        rendered = yaml.safe_load(completed.stdout)
        render = _admit_rendered_canonical_compose(
            rendered,
            image_references={
                artifact_id: image_environment[environment_name]
                for artifact_id, environment_name in _image_environment_names().items()
            },
        )
        return {
            **source,
            "status": "PASS",
            "rendered": True,
            "render": render,
            "image_release_set_digest": image_report["release_manifest"][
                "release_set_digest"
            ],
            "secret_included": False,
            "database_url_included": False,
        }
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "issues": [str(exc)],
            "rendered": False,
            "secret_included": False,
        }


def _image_environment_names() -> dict[str, str]:
    return dict(CURRENT_ARTIFACT_REFERENCE_ENVIRONMENTS)


def _canonical_environment(
    environ: Mapping[str, str], *, default_calibration: str | None = None
) -> dict[str, str]:
    result = dict(environ)
    if CALIBRATION_ENV not in result:
        calibration = result.get(LEGACY_CALIBRATION_ENV, default_calibration)
        if calibration is not None:
            result[CALIBRATION_ENV] = calibration
    return result


def _image_environment_from_release_report(
    report: Mapping[str, Any],
) -> dict[str, str]:
    artifacts = (report.get("image_build") or {}).get("artifacts")
    if report.get("status") != "PASS" or not isinstance(artifacts, list):
        raise ValueError("canonical image release report is not admitted")
    references = {
        str(item.get("artifact_id")): str(item.get("image_reference"))
        for item in artifacts
        if isinstance(item, Mapping)
    }
    expected = _image_environment_names()
    if set(references) != set(expected):
        raise ValueError("canonical image release set is incomplete")
    return {
        environment: references[artifact] for artifact, environment in expected.items()
    }


def _admit_rendered_canonical_compose(
    rendered: Mapping[str, Any],
    *,
    image_references: Mapping[str, str],
) -> dict[str, Any]:
    services = rendered.get("services")
    if not isinstance(services, Mapping):
        raise TypeError("canonical rendered services are unavailable")
    expected_references = set(image_references.values())
    observed_references = {
        str(service.get("image") or "")
        for service in services.values()
        if isinstance(service, Mapping)
    }
    if not expected_references.issubset(observed_references):
        raise ValueError("canonical rendered image references drift")
    for process_id in (
        "nex-wa-evidence-consumer",
        "nex-ae-agent-runtime-worker",
        "nex-wc-event-delivery-worker",
        "nex-eos-outbox-publisher",
    ):
        service = services.get(process_id)
        if not isinstance(service, Mapping):
            raise TypeError(f"canonical process is missing: {process_id}")
        if service.get("restart") != "unless-stopped" or "ports" in service:
            raise ValueError(f"canonical process policy drift: {process_id}")
    serialized = json.dumps(rendered, sort_keys=True)
    if "nuri1004" in serialized or "_TEST_DATABASE_URL" in serialized:
        raise ValueError("canonical Compose exposes forbidden database input")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "service_count": len(services),
        "image_count": len(image_references),
        "installed_process_count": 20,
        "secret_included": False,
        "database_url_included": False,
    }


def _write_report(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or "FAIL")
    render = dict(result.get("render") or {})
    return (
        f"canonical_platform_compose={status.lower()} "
        f"rendered={str(result.get('rendered') is True).lower()} "
        f"services={render.get('service_count', 0)} "
        f"images={render.get('image_count', 0)} secret=false"
    )


check_p8_demo_compose = check_canonical_platform_compose


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the Canonical Platform Compose topology."
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--image-report", type=Path, default=DEFAULT_IMAGE_REPORT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = check_canonical_platform_compose(
        execute=args.execute,
        image_report_path=args.image_report,
    )
    _write_report(args.report, result)
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result.get("status") in {"PASS", "SOURCE_ADMITTED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
