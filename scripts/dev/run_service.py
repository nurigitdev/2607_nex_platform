#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED_PATH))

from nex_runtime import SERVICE_SPECS, load_env_file, merge_pythonpath  # noqa: E402


SERVICE_MODULES = {
    "nex-oa": "nex_oa.main:app",
    "nex-ag": "nex_ag.main:app",
    "nex-ae-api": "nex_ae_api.main:app",
    "nex-cx": "nex_cx.main:app",
    "nex-mo": "nex_mo.main:app",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a NeX backend service shell.")
    parser.add_argument("service_id", choices=sorted(SERVICE_MODULES))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    load_env_file(ROOT / ".env.local")
    spec = SERVICE_SPECS[args.service_id]
    service_path = ROOT / "services" / args.service_id
    os.environ["PYTHONPATH"] = merge_pythonpath(service_path, SHARED_PATH)
    sys.path.insert(0, str(service_path))

    import uvicorn

    uvicorn.run(
        SERVICE_MODULES[args.service_id],
        host=args.host,
        port=args.port or spec.default_port,
        reload=args.reload,
        reload_dirs=[str(service_path), str(SHARED_PATH)] if args.reload else None,
    )
    return 0

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
