#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-oa"))

from nex_oa.openbao_transit_keys import (
    OpenBaoTransitKeyProvisioner,
    register_openbao_transit_key_version,
)
from nex_oa.openbao_transit_signer import (
    OpenBaoTransitOaRsaSigningProvider,
)
from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER
from nex_oa.service_principal_repository import (
    InMemoryOaServicePrincipalRepository,
)
from nex_oa.service_principal_service import OaServicePrincipalService
from nex_oa.signed_token_repository import (
    InMemoryOaSignedTokenRepository,
)
from nex_oa.signed_tokens import OaSignedTokenError
from nex_oa.signing_key_service import OaSigningKeyService
from nex_oa.token_exchange_service import (
    OaClientCredentialTokenExchangeService,
)
from nex_oa.token_validation_service import (
    OaSignedTokenValidationService,
)

SCHEMA_VERSION = "oa_openbao_transit_rotation_checkpoint.v1"
KEY_NAME = "oa-signing"
CLIENT_SECRET = "rotation-client-secret-1234567890"


class _TransitLifecycleTransport:
    def __init__(self) -> None:
        self.keys: dict[int, rsa.RSAPrivateKey] = {}
        self.requests: list[tuple[str, str, str | None]] = []

    def request(self, method, path, *, token=None, payload=None):
        self.requests.append((method, path, token))
        if path == "/v1/auth/approle/login":
            role = str(payload.get("role_id") or "")
            prefix = "operator" if role.startswith("operator") else "runtime"
            return {"auth": {"client_token": f"{prefix}-token-12345678"}}
        if path == f"/v1/transit/keys/{KEY_NAME}" and method == "POST":
            if not self.keys:
                self.keys[1] = _rsa_key()
            return {}
        if path == f"/v1/transit/keys/{KEY_NAME}/rotate":
            self.keys[max(self.keys) + 1] = _rsa_key()
            return {}
        if path == f"/v1/transit/keys/{KEY_NAME}" and method == "GET":
            return {"data": self._metadata()}
        if path == f"/v1/transit/sign/{KEY_NAME}/sha2-256":
            version = int(payload["key_version"])
            signature = self.keys[version].sign(
                base64.b64decode(payload["input"]),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            return {
                "data": {
                    "signature": f"vault:v{version}:"
                    + base64.b64encode(signature).decode("ascii")
                }
            }
        return {}

    def _metadata(self) -> dict[str, Any]:
        return {
            "type": "rsa-3072",
            "supports_signing": True,
            "derived": False,
            "exportable": False,
            "allow_plaintext_backup": False,
            "latest_version": max(self.keys),
            "keys": {
                str(version): {
                    "public_key": key.public_key()
                    .public_bytes(
                        serialization.Encoding.PEM,
                        serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                    .decode("ascii")
                }
                for version, key in self.keys.items()
            },
        }


def _rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def _key_service(repository) -> OaSigningKeyService:
    return OaSigningKeyService(
        repository=repository,
        deployment_profile="production",
    )


def _principal_service(repository) -> OaServicePrincipalService:
    return OaServicePrincipalService(repository)


def _exchange_service(principals, keys, signer):
    return OaClientCredentialTokenExchangeService(
        principal_service=principals,
        signing_key_service=keys,
        signing_provider=signer,
    )


def _validator(principals, keys):
    return OaSignedTokenValidationService(
        signing_key_service=keys,
        principal_service=principals,
    )


def _issue(exchange, *, now_epoch: int, token_id: str) -> str:
    return exchange.exchange(
        {
            "grant_type": "client_credentials",
            "credential_id": "cred-ae-rotation",
            "client_secret": CLIENT_SECRET,
            "audience": "nex-cx",
            "scope": "document:read",
        },
        now_epoch=now_epoch,
        token_id=token_id,
    )["access_token"]


def run_oa_openbao_transit_rotation_checkpoint() -> dict[str, Any]:
    transport = _TransitLifecycleTransport()
    operator = OpenBaoTransitKeyProvisioner.authenticate(
        transport,
        role_id="operator-role-12345678",
        secret_id="operator-secret-12345678",
    )
    signer = OpenBaoTransitOaRsaSigningProvider.authenticate(
        transport,
        role_id="runtime-role-12345678",
        secret_id="runtime-secret-12345678",
    )
    key_repository = InMemoryOaSignedTokenRepository()
    keys = _key_service(key_repository)
    principal_repository = InMemoryOaServicePrincipalRepository()
    principals = _principal_service(principal_repository)
    principals.upsert_principal(
        {
            "principal_id": "ae-rotation",
            "service_id": "nex-ae-api",
            "display_name": "AE rotation runtime",
            "allowed_audiences": ["nex-cx"],
            "allowed_scopes": ["document:read"],
            "expected_revision": 0,
        }
    )
    principals.issue_credential(
        "ae-rotation",
        lifetime_days=1,
        now_epoch=100,
        credential_id="cred-ae-rotation",
        client_secret=CLIENT_SECRET,
    )

    first_version = operator.provision_rsa3072(KEY_NAME)
    register_openbao_transit_key_version(
        operator,
        keys,
        key_name=KEY_NAME,
        key_version=first_version,
        key_id="oa-key-s144-v1",
        issuer=PRODUCTION_TOKEN_ISSUER,
        published_at=100,
        activate_at=430,
        sign_until=900,
        verify_until=1_230,
    )
    keys.set_key_state(
        "oa-key-s144-v1",
        target_state="ACTIVE",
        expected_revision=1,
        now_epoch=430,
    )
    first_token = _issue(
        _exchange_service(principals, keys, signer),
        now_epoch=500,
        token_id="sat-s144-v1",
    )

    second_version = operator.rotate_rsa3072(
        KEY_NAME,
        expected_current_version=first_version,
    )
    register_openbao_transit_key_version(
        operator,
        keys,
        key_name=KEY_NAME,
        key_version=second_version,
        key_id="oa-key-s144-v2",
        issuer=PRODUCTION_TOKEN_ISSUER,
        published_at=200,
        activate_at=530,
        sign_until=1_000,
        verify_until=1_330,
    )
    prepublished = keys.jwks(at_epoch=520)

    rollback_preserved = False
    try:
        keys.activate_rotation(
            "oa-key-s144-v1",
            "oa-key-s144-v2",
            expected_previous_revision=2,
            expected_active_revision=1,
            now_epoch=529,
        )
    except OaSignedTokenError as exc:
        rollback_preserved = (
            exc.code == "oa.signing_key_activation_early"
            and keys.get_key("oa-key-s144-v1")["signing_key"]["state"]
            == "ACTIVE"
            and keys.get_key("oa-key-s144-v2")["signing_key"]["state"]
            == "PREPUBLISHED"
        )

    rotation = keys.activate_rotation(
        "oa-key-s144-v1",
        "oa-key-s144-v2",
        expected_previous_revision=2,
        expected_active_revision=1,
        now_epoch=530,
    )
    second_token = _issue(
        _exchange_service(principals, keys, signer),
        now_epoch=540,
        token_id="sat-s144-v2",
    )
    validator = _validator(principals, keys)
    first_claims = validator.validate(
        first_token, expected_audience="nex-cx", now_epoch=550
    )
    second_claims = validator.validate(
        second_token, expected_audience="nex-cx", now_epoch=550
    )

    restarted_keys = _key_service(key_repository)
    restarted_principals = _principal_service(principal_repository)
    restarted_validator = _validator(restarted_principals, restarted_keys)
    before_revocation = restarted_validator.introspect(
        first_token,
        expected_audience="nex-cx",
        now_epoch=550,
    )
    restarted_keys.revoke_token_claims(
        first_claims,
        reason_code="OPERATOR",
        now_epoch=550,
        revocation_id="rev-s144-v1",
    )
    after_revocation = restarted_validator.introspect(
        first_token,
        expected_audience="nex-cx",
        now_epoch=550,
    )
    second_after_restart = restarted_validator.introspect(
        second_token,
        expected_audience="nex-cx",
        now_epoch=550,
    )
    final_jwks = restarted_keys.jwks(at_epoch=550)
    operator.close()
    signer.close()

    states = {
        record["key_id"]: record["state"]
        for record in key_repository.list_signing_keys()
    }
    checks = {
        "transit_version_incremented": (first_version, second_version) == (1, 2),
        "prepublication_has_overlap": prepublished["key_count"] == 2,
        "early_activation_rolls_back": rollback_preserved,
        "rotation_is_atomic": rotation["previous_signing_key"]["state"]
        == "VERIFY_ONLY"
        and rotation["active_signing_key"]["state"] == "ACTIVE",
        "exactly_one_active_key": list(states.values()).count("ACTIVE") == 1,
        "old_token_survives_overlap": first_claims["jti"] == "sat-s144-v1",
        "new_token_uses_rotated_key": second_claims["jti"] == "sat-s144-v2",
        "restart_restores_jwks": final_jwks["key_count"] == 2,
        "introspection_active_before_revocation": before_revocation["active"] is True,
        "revocation_survives_restart": after_revocation == {
            "introspection_schema_version": "oa_token_introspection.v1",
            "active": False,
            "reason_code": "oa.token_revoked",
        },
        "new_token_remains_active": second_after_restart["active"] is True,
        "private_material_absent": all(
            not {"d", "p", "q", "dp", "dq", "qi", "oth"}.intersection(item)
            for item in final_jwks["keys"]
        ),
        "separate_operator_runtime_tokens": any(
            token == "operator-token-12345678" for _, _, token in transport.requests
        )
        and any(token == "runtime-token-12345678" for _, _, token in transport.requests),
        "live_openbao_postgres_not_contacted": True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1437",
        "requirement": "S144",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": [] if passed else [name for name, value in checks.items() if not value],
        "summary": {
            "check_count": len(checks),
            "key_count": len(states),
            "active_key_count": list(states.values()).count("ACTIVE"),
            "jwks_key_count": final_jwks["key_count"],
            "restart_count": 1,
        },
        "decision": {
            "atomic_rotation_required": True,
            "silent_signing_fallback_allowed": False,
            "live_openbao_contacted": False,
            "live_postgres_contacted": False,
            "production_deployment_approved": False,
            "next_slice": "1438" if passed else "blocked",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"oa_transit_rotation_checkpoint=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "oa_transit_rotation_checkpoint=pass "
        f"checks={summary.get('check_count', 0)}/14 "
        f"keys={summary.get('key_count', 0)} "
        f"active={summary.get('active_key_count', 0)} "
        f"jwks={summary.get('jwks_key_count', 0)} "
        f"restarts={summary.get('restart_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_oa_openbao_transit_rotation_checkpoint()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
