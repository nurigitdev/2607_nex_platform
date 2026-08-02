#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


SERVICES = {
    "nex-oa": 8101,
    "nex-ag": 8102,
    "nex-ae-api": 8103,
    "nex-cx": 8104,
    "nex-mo": 8105,
}


def main() -> int:
    failures = 0
    for service_id, port in SERVICES.items():
        for endpoint in ("health", "ready", "version"):
            url = f"http://127.0.0.1:{port}/{endpoint}"
            ok, summary = _fetch(url)
            status = "OK" if ok else "FAIL"
            print(f"{service_id} /{endpoint}: {status} {summary}")
            failures += 0 if ok else 1
    return 1 if failures else 0


def _fetch(url: str) -> tuple[bool, str]:
    try:
        with urlopen(url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return True, _summarize(payload)
    except HTTPError as exc:
        return False, f"http_status={exc.code}"
    except (OSError, URLError) as exc:
        return False, exc.__class__.__name__


def _summarize(payload: dict[str, object]) -> str:
    for key in ("health_status", "readiness_status", "version"):
        if key in payload:
            return f"{key}={payload[key]}"
    return "response=received"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
