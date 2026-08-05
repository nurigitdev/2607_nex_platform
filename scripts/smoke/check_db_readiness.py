#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED_PATH))

from nex_runtime import check_database_readiness, load_env_file  # noqa: E402

DATABASE_ENVS = {
    "nex-oa": "NEX_OA_DATABASE_URL",
    "nex-ag": "NEX_AG_DATABASE_URL",
    "nex-ae-api": "NEX_AE_DATABASE_URL",
    "nex-cx": "NEX_CX_DATABASE_URL",
    "nex-mo": "NEX_MO_DATABASE_URL",
}


def main() -> int:
    load_env_file(ROOT / ".env.local")
    failures = 0
    for service_id, env_name in DATABASE_ENVS.items():
        check = check_database_readiness(env_name, environ=os.environ)
        if not check["ok"]:
            if check["error_code"] == "DATABASE_URL_MISSING":
                print(f"{service_id}: NOT_READY missing {env_name}")
            elif check["error_code"] == "DATABASE_URL_PLACEHOLDER":
                print(f"{service_id}: NOT_READY placeholder {env_name}")
            else:
                print(f"{service_id}: NOT_READY connection failed")
            failures += 1
            continue
        database_name = check["database_name"]
        user_name = check["database_user"]
        latency_ms = check["latency_ms"]
        print(f"{service_id}: READY db={database_name} user={user_name} latency_ms={latency_ms}")
    return 1 if failures else 0

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
