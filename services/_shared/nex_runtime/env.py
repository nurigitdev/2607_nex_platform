from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), _strip_env_quotes(value.strip()))


def merge_pythonpath(*paths: Path) -> str:
    existing = os.environ.get("PYTHONPATH")
    parts = [str(path) for path in paths]
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)


def _strip_env_quotes(value: str) -> str:
    if len(value) < 2:
        return value
    if value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
