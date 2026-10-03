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
from nex_oa.signed_tokens import (  # noqa: E402
    build_signing_key_record,
    build_test_public_jwk,
    build_token_revocation_record,
    plan_signing_key_transition,
)


def run_oa_signed_token_repository() -> dict[str, Any]:
    repository = InMemoryOaSignedTokenRepository()
    registered = repository.save_signing_key(
        build_signing_key_record(
            {
                "key_id": "oa-key-repository",
                "issuer": PRODUCTION_TOKEN_ISSUER,
                "public_jwk": build_test_public_jwk("oa-key-repository"),
                "private_key_ref": "file:///tmp/not-loaded.pem",
                "published_at": 100,
                "activate_at": 430,
                "sign_until": 800,
                "verify_until": 1_130,
            },
            deployment_profile="test",
        )
    )
    active = repository.save_signing_key(
        plan_signing_key_transition(
            registered, target_state="ACTIVE", expected_revision=1, now_epoch=430
        )
    )
    revocation = repository.create_revocation(
        build_token_revocation_record(
            {
                "iss": PRODUCTION_TOKEN_ISSUER,
                "sub": "service:nex-ae-api",
                "aud": "nex-cx",
                "jti": "repository-jti",
                "token_use": "service_access",
                "exp": 900,
            },
            reason_code="OPERATOR",
            now_epoch=600,
            revocation_id="rev-repository",
        )
    )
    checks = {
        "active_key_restart_read": repository.get_signing_key(active["key_id"])["state"] == "ACTIVE",
        "public_key_round_trip": repository.list_signing_keys()[0]["public_jwk"]["kid"] == active["key_id"],
        "revocation_digest_read": repository.get_revocation_by_digest(revocation["jti_digest"]) is not None,
        "revocation_retained_before_expiry": repository.purge_expired_revocations(at_epoch=899) == 0,
        "revocation_purged_at_expiry": repository.purge_expired_revocations(at_epoch=900) == 1,
    }
    passed = all(checks.values())
    return {
        "repository_schema_version": "oa_signed_token_repository_evidence.v1",
        "slice": "1265",
        "requirement": "S127",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_signed_token_repository_failed",
        "checks": checks,
        "key_count": len(repository.list_signing_keys()),
        "cleanup_residue_count": len(repository.revocations),
        "next_slice": "1266",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "oa_signed_token_repository="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"keys={evidence.get('key_count', 0)} "
        f"residue={evidence.get('cleanup_residue_count', -1)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_signed_token_repository()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
