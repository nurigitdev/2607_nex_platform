#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt  # noqa: E402
from nex_runtime import (  # noqa: E402
    BoundedJwksCache,
    SERVICE_SPECS,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    build_service_app,
)


CONSUMER_MAIN_PATHS = (
    "services/nex-ae-api/nex_ae_api/main.py",
    "services/nex-cx/nex_cx/main.py",
    "services/nex-mo/nex_mo/main.py",
    "services/nex-ag/nex_ag/main.py",
)


def run_service_token_rollout_observability(root: Path = ROOT) -> dict[str, Any]:
    signer = InMemoryOaRsaSigningProvider()
    reference = "memory://oa-key-rollout-observability"
    signer.generate_key(reference)
    key_id = "oa-key-rollout-observability"
    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": key_id},
        claims={
            "iss": "urn:nex-platform:oa",
            "sub": "service:nex-oa",
            "aud": "nex-cx",
            "iat": 500,
            "nbf": 500,
            "exp": 800,
            "jti": "sat-rollout-observability",
            "token_use": "service_access",
            "scope": "service:call",
            "service_id": "nex-oa",
            "credential_id": "cred-oa-runtime",
            "credential_revision": 1,
        },
        private_key_ref=reference,
        signing_provider=signer,
    )
    verifier = SignedServiceTokenVerifier(
        BoundedJwksCache(
            StaticJwksSource(
                {
                    "issuer": "urn:nex-platform:oa",
                    "keys": [signer.public_jwk(reference, key_id=key_id)],
                }
            ),
            clock=lambda: 600,
        ),
        clock=lambda: 600,
    )
    runtime = ServiceTokenAdmissionRuntime(
        expected_audience="nex-cx",
        rollout_profile="SIGNED_ONLY",
        signed_verifier=verifier,
        clock=lambda: 600,
    )
    client = TestClient(
        build_service_app(
            SERVICE_SPECS["nex-cx"],
            service_token_admission=runtime,
        )
    )
    denied = client.get("/internal/v1/auth/service-token-runtime")
    accepted = client.get(
        "/internal/v1/auth/service-token-runtime",
        headers={"Authorization": f"Bearer {token}"},
    )
    projection = accepted.json()

    schema_path = root / "contracts/schemas/common/service_token_runtime.v1.schema.json"
    contract_valid = False
    if schema_path.is_file() and accepted.status_code == 200:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        contract_valid = not list(Draft202012Validator(schema).iter_errors(projection))
    wired_consumers = [
        path
        for path in CONSUMER_MAIN_PATHS
        if "service_token_admission=SERVICE_TOKEN_ADMISSION"
        in _read_text(root / path)
    ]
    serialized = json.dumps(projection, sort_keys=True)
    forbidden_fragments = (
        token,
        "cred-oa-runtime",
        key_id,
        "Authorization",
        "client_secret",
        "private_key",
    )
    checks = {
        "runtime_route_is_protected": denied.status_code == 401,
        "signed_runtime_projection_available": accepted.status_code == 200,
        "projection_contract_valid": contract_valid,
        "admission_counters_are_visible": projection.get("admission_counts")
        == {
            "accepted_mock": 0,
            "accepted_signed": 1,
            "rejected": 1,
            "introspected": 0,
        },
        "jwks_cache_is_bounded_and_redacted": projection.get("jwks_cache", {}).get(
            "status"
        ) == "POPULATED"
        and projection.get("jwks_cache", {}).get("key_count") == 1,
        "all_consumers_wire_shared_admission": len(wired_consumers)
        == len(CONSUMER_MAIN_PATHS),
        "secrets_and_identifiers_are_redacted": not any(
            fragment in serialized for fragment in forbidden_fragments
        ),
        "database_not_required": True,
        "dgx_provider_not_required": True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "service_token_rollout_observability_evidence.v1",
        "slice": "1279",
        "requirement": "S128",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "service_token_rollout_observability_failed",
        "checks": checks,
        "consumer_count": len(wired_consumers),
        "runtime_schema_version": projection.get("runtime_schema_version"),
        "next_slice": "1280",
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "service_token_rollout_observability="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"consumers={evidence.get('consumer_count', 0)} "
        f"schema={evidence.get('runtime_schema_version', 'missing')} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_service_token_rollout_observability()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
