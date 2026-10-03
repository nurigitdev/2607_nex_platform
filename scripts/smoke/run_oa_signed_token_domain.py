#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER  # noqa: E402
from nex_oa.signed_tokens import (  # noqa: E402
    build_jwks_document,
    build_signing_key_record,
    build_token_revocation_record,
    plan_signing_key_transition,
    build_test_public_jwk,
    token_is_revoked,
)


def run_oa_signed_token_domain() -> dict[str, Any]:
    registered = build_signing_key_record(
        {
            "key_id": "oa-key-domain",
            "issuer": PRODUCTION_TOKEN_ISSUER,
            "public_jwk": build_test_public_jwk("oa-key-domain"),
            "private_key_ref": "file:///tmp/not-loaded-by-domain.pem",
            "published_at": 1_000,
            "activate_at": 1_330,
            "sign_until": 2_000,
            "verify_until": 2_330,
        },
        deployment_profile="test",
    )
    active = plan_signing_key_transition(
        registered, target_state="ACTIVE", expected_revision=1, now_epoch=1_330
    )
    jwks = build_jwks_document([active], at_epoch=1_330)
    revocation = build_token_revocation_record(
        {
            "iss": PRODUCTION_TOKEN_ISSUER,
            "sub": "service:nex-ae-api",
            "aud": "nex-cx",
            "jti": "domain-jti-not-persisted",
            "token_use": "service_access",
            "exp": 1_630,
        },
        reason_code="OPERATOR",
        now_epoch=1_400,
        revocation_id="rev-domain",
    )
    checks = {
        "registered_prepublished": registered["state"] == "PREPUBLISHED",
        "active_transition_revisioned": active["state"] == "ACTIVE" and active["revision"] == 2,
        "jwks_public_only": jwks["key_count"] == 1 and "d" not in jwks["keys"][0],
        "revocation_digest_only": (
            len(revocation["jti_digest"]) == 64
            and "domain-jti-not-persisted" not in json.dumps(revocation)
        ),
        "revocation_active": token_is_revoked(revocation, at_epoch=1_500),
        "revocation_expires": not token_is_revoked(revocation, at_epoch=1_630),
    }
    passed = all(checks.values())
    return {
        "domain_schema_version": "oa_signed_token_domain_evidence.v1",
        "slice": "1263",
        "requirement": "S127",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_signed_token_domain_failed",
        "checks": checks,
        "key_state": active["state"],
        "jwks_key_count": jwks["key_count"],
        "revocation_digest_length": len(revocation["jti_digest"]),
        "next_slice": "1264",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "oa_signed_token_domain="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"key={evidence.get('key_state', 'unknown')} "
        f"jwks={evidence.get('jwks_key_count', 0)} "
        f"digest={evidence.get('revocation_digest_length', 0)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_signed_token_domain()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
