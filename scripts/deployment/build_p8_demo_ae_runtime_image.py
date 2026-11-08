#!/usr/bin/env python3
"""Compatibility alias for the canonical AE runtime image builder."""

import importlib
import sys

_TARGET = "build_canonical_platform_ae_runtime_image"

if __name__ == "__main__":
    raise SystemExit(importlib.import_module(_TARGET).main())

sys.modules[__name__] = importlib.import_module(_TARGET)
