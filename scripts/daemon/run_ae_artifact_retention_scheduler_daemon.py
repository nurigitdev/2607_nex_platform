#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
for package_root in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
):
    package_path = str(package_root)
    if package_path not in sys.path:
        sys.path.insert(0, package_path)

from nex_ae_api.artifact_retention_scheduler_daemon import main  # noqa: E402


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
