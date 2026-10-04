#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SHARED_ROOT = ROOT / "services" / "_shared"
if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))

from nex_runtime.platform_trust_restart_plan import (  # noqa: E402
    TRUST_RESTART_CHECKPOINTS,
    build_platform_trust_restart_plan,
    evaluate_platform_trust_restart_checkpoints,
    validate_platform_trust_restart_plan,
)


def run_platform_trust_restart_plan(root: Path = ROOT) -> dict[str, Any]:
    plan = build_platform_trust_restart_plan()
    issues = list(validate_platform_trust_restart_plan(plan))
    checkpoints = evaluate_platform_trust_restart_checkpoints(
        TRUST_RESTART_CHECKPOINTS
    )
    oa_main = (root / "services/nex-oa/nex_oa/main.py").read_text(encoding="utf-8")
    oa_auth = (root / "services/nex-oa/nex_oa/service_auth.py").read_text(
        encoding="utf-8"
    )
    checks = {
        "plan_valid": not issues,
        "restart_checkpoints_complete": checkpoints["status"] == "PASS",
        "oa_local_admission_attached": (
            "build_oa_local_service_token_admission(" in oa_main
        ),
        "oa_local_jwks_source": "class LocalOaJwksSource" in oa_auth,
        "oa_local_introspection": "class LocalOaTokenIntrospector" in oa_auth,
        "remote_model_providers_excluded": not plan.remote_model_providers_allowed,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    return {
        "requirement": "S134",
        "slice": "1338",
        "status": "PASS" if not failed_checks else "FAIL",
        "checks": checks,
        "failed_checks": failed_checks,
        "plan_issues": issues,
        "phase_count": len(plan.phase_order),
        "generation_count": plan.generation_count,
        "service_count": len(plan.process_start_order),
        "checkpoint_count": checkpoints["checkpoint_count"],
        "next_slice": "1339",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_trust_restart_plan()
    if args.summary:
        print(
            "platform_trust_restart_plan="
            f"{result['status'].lower()} phases={result['phase_count']} "
            f"generations={result['generation_count']} services={result['service_count']} "
            f"checkpoints={result['checkpoint_count']} next={result['next_slice']}"
        )
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
