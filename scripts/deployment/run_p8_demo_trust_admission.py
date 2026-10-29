#!/usr/bin/env python3
"""Compatibility alias for canonical Platform trust admission."""

import importlib
import sys

_TARGET = "run_canonical_platform_trust_admission"

if __name__ == "__main__":
    raise SystemExit(importlib.import_module(_TARGET).main())

sys.modules[__name__] = importlib.import_module(_TARGET)
