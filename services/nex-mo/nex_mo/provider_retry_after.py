from __future__ import annotations


def parse_retry_after_seconds(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = float(value.strip())
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
