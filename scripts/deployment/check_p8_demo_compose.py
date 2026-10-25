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

from nex_runtime.demo_compose import (
    DEMO_COMPOSE_SCHEMA_VERSION,
    DemoComposeError,
    admit_demo_compose_sources,
    admit_rendered_demo_compose,
    image_environment_from_release_report,
)

EXECUTION_ENV = "NEX_P8_DEMO_COMPOSE_RENDER"
BASE_COMPOSE = ROOT / "deployment/compose/s143-staging.compose.yaml"
OBJECT_COMPOSE = ROOT / "deployment/compose/s146-object-storage.override.yaml"
DEMO_COMPOSE = ROOT / "deployment/compose/p8-demo.override.yaml"
DEFAULT_IMAGE_REPORT = ROOT / "reports/deployment/p8-demo-oci-image-build.json"
DEFAULT_REPORT = ROOT / "reports/deployment/p8-demo-compose-render.json"


def check_p8_demo_compose(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    root: Path = ROOT,
    image_report_path: Path = DEFAULT_IMAGE_REPORT,
    executor: Any = subprocess.run,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    source = admit_demo_compose_sources(root)
    if not execute or env.get(EXECUTION_ENV) != "1":
        return {**source, "status": "SOURCE_ADMITTED", "rendered": False}
    try:
        image_report = json.loads(image_report_path.read_text(encoding="utf-8"))
        image_environment = image_environment_from_release_report(image_report)
        with TemporaryDirectory(prefix="nex-p8-demo-compose-") as temporary:
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
                str(root / DEMO_COMPOSE.relative_to(ROOT)),
                "config",
                "--format",
                "yaml",
            )
            completed = executor(
                command,
                cwd=root,
                env={
                    **env,
                    **image_environment,
                    "NEX_S143_RUNTIME_DIR": str(runtime_dir),
                },
                check=False,
                capture_output=True,
                text=True,
            )
        if completed.returncode != 0:
            raise DemoComposeError("P8 Demo Docker Compose render failed")
        rendered = yaml.safe_load(completed.stdout)
        render = admit_rendered_demo_compose(
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
            "schema_version": DEMO_COMPOSE_SCHEMA_VERSION,
            "status": "FAIL",
            "issues": [str(exc)],
            "rendered": False,
            "secret_included": False,
        }


def _image_environment_names() -> dict[str, str]:
    return {
        "nex-oa-runtime": "NEX_OA_RUNTIME_IMAGE",
        "nex-ag-runtime": "NEX_AG_RUNTIME_IMAGE",
        "nex-ae-runtime": "NEX_AE_RUNTIME_IMAGE",
        "nex-cx-runtime": "NEX_CX_RUNTIME_IMAGE",
        "nex-mo-runtime": "NEX_MO_RUNTIME_IMAGE",
        "nex-wc-runtime": "NEX_WC_RUNTIME_IMAGE",
        "nex-eos-runtime": "NEX_EOS_RUNTIME_IMAGE",
        "nex-ae-web": "NEX_AE_WEB_IMAGE",
    }


def _write_report(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or "FAIL")
    render = dict(result.get("render") or {})
    return (
        f"p8_demo_compose={status.lower()} "
        f"rendered={str(result.get('rendered') is True).lower()} "
        f"services={render.get('service_count', 0)} "
        f"images={render.get('image_count', 0)} secret=false"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the P8 Demo Compose topology.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--image-report", type=Path, default=DEFAULT_IMAGE_REPORT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = check_p8_demo_compose(
        execute=args.execute,
        image_report_path=args.image_report,
    )
    _write_report(args.report, result)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"PASS", "SOURCE_ADMITTED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
