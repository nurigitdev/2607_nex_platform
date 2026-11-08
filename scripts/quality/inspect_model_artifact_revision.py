#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
ROOT = (
    SCRIPT_PATH.parents[2]
    if len(SCRIPT_PATH.parents) > 2
    else SCRIPT_PATH.parent
)
sys.path.insert(0, str(ROOT / "services" / "_shared"))

try:
    from nex_runtime import (  # noqa: E402
        ModelArtifactRevisionError,
        inspect_huggingface_local_revision,
    )
except ModuleNotFoundError:  # pragma: no cover - standalone DGX utility mode
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from model_artifact_revision import (  # type: ignore[no-redef] # noqa: E402
        ModelArtifactRevisionError,
        inspect_huggingface_local_revision,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = inspect_huggingface_local_revision(args.model_directory)
    except ModelArtifactRevisionError as exc:
        result = {
            "schema_version": "model_artifact_revision.v1",
            "status": "FAIL",
            "failure_code": "model_artifact_revision_inspection_failed",
            "detail": str(exc),
            "model_path_persisted": False,
            "artifact_content_persisted": False,
        }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(result, indent=2, sort_keys=True)}\n",
            encoding="utf-8",
        )
    if args.summary:
        revision = result.get("artifact_revision", "unavailable")
        print(
            "model_artifact_revision="
            f"{result['status'].lower()} revision={revision}"
        )
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
