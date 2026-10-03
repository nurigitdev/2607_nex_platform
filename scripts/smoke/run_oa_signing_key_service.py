#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER  # noqa: E402
from nex_oa.signed_token_repository import InMemoryOaSignedTokenRepository  # noqa: E402
from nex_oa.signed_tokens import build_test_public_jwk  # noqa: E402
from nex_oa.signing_key_service import OaSigningKeyService  # noqa: E402


def run_oa_signing_key_service() -> dict[str, Any]:
    service = OaSigningKeyService(
        repository=InMemoryOaSignedTokenRepository(),
        deployment_profile="test",
    )
    service.register_key(
        {
            "key_id": "oa-key-checkpoint",
            "issuer": PRODUCTION_TOKEN_ISSUER,
            "public_jwk": build_test_public_jwk("oa-key-checkpoint"),
            "private_key_ref": "file:///tmp/not-loaded.pem",
            "published_at": 100,
            "activate_at": 430,
            "sign_until": 800,
            "verify_until": 1_130,
        }
    )
    service.set_key_state(
        "oa-key-checkpoint",
        target_state="ACTIVE",
        expected_revision=1,
        now_epoch=430,
    )
    key = service.active_signing_key(at_epoch=500)
    jwks = service.jwks(at_epoch=500)
    reconciled = service.reconcile_key_states(now_epoch=800)
    checks = {
        "active_key_selected": key["key_id"] == "oa-key-checkpoint",
        "private_custody_not_projected": "private_key_ref" not in service.get_key(key["key_id"])["signing_key"],
        "jwks_public_key_published": jwks["key_count"] == 1 and "d" not in jwks["keys"][0],
        "expired_signing_window_reconciled": reconciled["verify_only_count"] == 1,
        "verify_only_key_still_published": service.jwks(at_epoch=900)["key_count"] == 1,
    }
    passed = all(checks.values())
    return {
        "service_schema_version": "oa_signing_key_service_evidence.v1",
        "slice": "1266",
        "requirement": "S127",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_signing_key_service_failed",
        "checks": checks,
        "jwks_key_count": jwks["key_count"],
        "reconciled_count": reconciled["verify_only_count"],
        "next_slice": "1267",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "oa_signing_key_service="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"jwks={evidence.get('jwks_key_count', 0)} "
        f"reconciled={evidence.get('reconciled_count', 0)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_signing_key_service()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
