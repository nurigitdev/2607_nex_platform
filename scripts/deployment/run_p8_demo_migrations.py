#!/usr/bin/env python3
"""Compatibility alias for canonical Platform migration orchestration."""

import importlib
import sys

_TARGET = "run_canonical_platform_migrations"

if __name__ == "__main__":
    raise SystemExit(
        importlib.import_module(_TARGET).main(
            [*sys.argv[1:], "--historical-p8-demo"]
        )
    )

sys.modules[__name__] = importlib.import_module(_TARGET)
