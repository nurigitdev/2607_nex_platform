#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.signing_key_policy import (  # noqa: E402
    MINIMUM_PUBLICATION_LEAD_SECONDS,
    MINIMUM_VERIFICATION_OVERLAP_SECONDS,
    PRODUCTION_SIGNING_KEY_POLICY,
    allowed_key_transition,
    validate_signing_key_metadata,
)


def run_oa_signing_key_policy() -> dict[str, Any]:
    modulus = base64.urlsafe_b64encode(bytes([0x80]) + bytes(383)).rstrip(b"=").decode()
    key = {
        "key_id": "oa-key-1",
        "issuer": "urn:nex-platform:oa",
        "algorithm": "RS256",
        "state": "PREPUBLISHED",
        "public_jwk": {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": "oa-key-1",
            "n": modulus,
            "e": "AQAB",
        },
        "private_key_ref": "kms://nex-oa/signing/oa-key-1",
        "published_at": 1_000,
        "activate_at": 1_000 + MINIMUM_PUBLICATION_LEAD_SECONDS,
        "sign_until": 2_000,
        "verify_until": 2_000 + MINIMUM_VERIFICATION_OVERLAP_SECONDS,
        "revision": 1,
    }
    errors = validate_signing_key_metadata(key, deployment_profile="production")
    plaintext_errors = validate_signing_key_metadata(
        key | {"private_key_ref": "inline://private-key"},
        deployment_profile="production",
    )
    checks = {
        "rs256_only": PRODUCTION_SIGNING_KEY_POLICY.algorithm == "RS256",
        "rsa_3072_minimum": (
            PRODUCTION_SIGNING_KEY_POLICY.minimum_rsa_modulus_bits == 3072
        ),
        "production_metadata_valid": errors == (),
        "plaintext_inline_custody_rejected": (
            "private_key_custody_scheme_forbidden" in plaintext_errors
        ),
        "private_key_database_storage_forbidden": (
            not PRODUCTION_SIGNING_KEY_POLICY.private_key_plaintext_database_allowed
        ),
        "rotation_lifecycle_ordered": (
            allowed_key_transition("PREPUBLISHED", "ACTIVE")
            and allowed_key_transition("ACTIVE", "VERIFY_ONLY")
            and allowed_key_transition("VERIFY_ONLY", "RETIRED")
            and not allowed_key_transition("RETIRED", "ACTIVE")
        ),
    }
    passed = all(checks.values())
    return {
        "policy_schema_version": "oa_signing_key_policy.v1",
        "slice": "1245",
        "requirement": "S125",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_signing_key_policy_failed",
        "policy": PRODUCTION_SIGNING_KEY_POLICY.to_wire(),
        "database_storage": (
            "public_jwk_status_timing_revision_and_external_private_key_locator_only"
        ),
        "checks": checks,
        "next_slice": "1246",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    policy = evidence.get("policy") or {}
    return (
        "oa_signing_key_policy="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"alg={policy.get('algorithm')} rsa_bits={policy.get('minimum_rsa_modulus_bits')} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_signing_key_policy()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
