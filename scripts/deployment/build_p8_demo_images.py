#!/usr/bin/env python3
"""Compatibility alias for the promoted canonical Platform image builder."""

import importlib
import sys

_TARGET = "build_canonical_platform_images"

if __name__ == "__main__":
    raise SystemExit(importlib.import_module(_TARGET).main())

sys.modules[__name__] = importlib.import_module(_TARGET)
