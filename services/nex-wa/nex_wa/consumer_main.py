from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

from .persistence import (
    WaPersistenceError,
    WaPersistenceRuntime,
    build_wa_persistence_runtime,
)


def check_consumer_readiness(
    environ: Mapping[str, str],
    *,
    persistence_builder=build_wa_persistence_runtime,
) -> dict[str, Any]:
    persistence: WaPersistenceRuntime | None = None
    try:
        persistence = persistence_builder(environ=environ)
        checks = (
            persistence.migration_readiness(),
            persistence.consumer_storage_readiness(),
        )
        ready = all(check.get("ok") is True for check in checks)
        return {
            "service_id": "nex-wa",
            "process_id": "nex-wa-evidence-consumer",
            "readiness_status": "READY" if ready else "NOT_READY",
            "checks": list(checks),
        }
    except (WaPersistenceError, ValueError):
        return {
            "service_id": "nex-wa",
            "process_id": "nex-wa-evidence-consumer",
            "readiness_status": "NOT_READY",
            "checks": [
                {
                    "name": "wa_consumer_bootstrap",
                    "ok": False,
                    "error_code": "WA_CONSUMER_READINESS_FAILED",
                }
            ],
        }
    finally:
        if persistence is not None:
            persistence.dispose()


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    persistence_builder=build_wa_persistence_runtime,
) -> int:
    parser = argparse.ArgumentParser(prog="nex-wa-evidence-consumer")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("only --check is activated in P9-S10")
    result = check_consumer_readiness(
        os.environ if environ is None else environ,
        persistence_builder=persistence_builder,
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["readiness_status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
