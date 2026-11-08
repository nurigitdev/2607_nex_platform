#!/usr/bin/env python3
"""Compatibility alias for canonical Platform Compose admission."""

import importlib
import sys

_TARGET = "check_canonical_platform_compose"

if __name__ == "__main__":
    raise SystemExit(importlib.import_module(_TARGET).main())

sys.modules[__name__] = importlib.import_module(_TARGET)
