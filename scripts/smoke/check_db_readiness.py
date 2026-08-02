#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import psycopg


ROOT = Path(__file__).resolve().parents[2]
DATABASE_ENVS = {
    "nex-oa": "NEX_OA_DATABASE_URL",
    "nex-ag": "NEX_AG_DATABASE_URL",
    "nex-ae-api": "NEX_AE_DATABASE_URL",
    "nex-cx": "NEX_CX_DATABASE_URL",
    "nex-mo": "NEX_MO_DATABASE_URL",
}


def main() -> int:
    _load_env_file(ROOT / ".env.local")
    failures = 0
    for service_id, env_name in DATABASE_ENVS.items():
        started = time.perf_counter()
        database_url = os.getenv(env_name)
        if not database_url:
            print(f"{service_id}: NOT_READY missing {env_name}")
            failures += 1
            continue
        try:
            with psycopg.connect(database_url, connect_timeout=2) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("select current_database(), current_user")
                    database_name, user_name = cursor.fetchone()
        except Exception:
            print(f"{service_id}: NOT_READY connection failed")
            failures += 1
            continue
        latency_ms = round((time.perf_counter() - started) * 1000)
        print(f"{service_id}: READY db={database_name} user={user_name} latency_ms={latency_ms}")
    return 1 if failures else 0


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    raise SystemExit(main())
