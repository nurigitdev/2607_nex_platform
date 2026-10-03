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

from nex_oa.federated_identities import build_external_identity_link, build_federation_provider  # noqa: E402
from nex_oa.federated_identity_repository import InMemoryOaFederatedIdentityRepository  # noqa: E402
from nex_oa.federated_login import OaFederatedLoginService  # noqa: E402
from nex_oa.oidc_verifier import VerifiedOidcIdentity  # noqa: E402


class _Verifier:
    def verify(self, _token: object, *, expected_nonce: object) -> VerifiedOidcIdentity:
        assert expected_nonce == "browser-nonce"
        return VerifiedOidcIdentity(
            provider_id="company-oidc",
            issuer="https://id.example.test",
            audiences=("nex-platform",),
            authorized_party="nex-platform",
            issued_at=1_800_000_000,
            expires_at=1_800_000_300,
            key_id="key-1",
            external_subject_digest=(
                "1fe37e2c4f3041166edbf415c389921987cba9b5fe6edf1919dd8ed136b7b16f"
            ),
            nonce_digest="0" * 64,
            _external_subject="opaque-subject",
        )


class _Verifiers:
    def for_provider(self, _provider: Mapping[str, Any]) -> _Verifier:
        return _Verifier()


class _Sessions:
    payload: dict[str, Any] | None = None

    def issue_session(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self.payload = dict(payload)
        return {
            "session_schema_version": "oa_user_session.v1",
            "session_id": "opaque-oa-session",
            "tenant_id": payload["tenant_id"],
            "subject_id": payload["subject_id"],
            "status": "ACTIVE",
            "roles": ["admin"],
            "scopes": ["workspace:use"],
            "metadata": {},
        }


def run_oa_federated_login_orchestration() -> dict[str, Any]:
    provider = build_federation_provider(
        {
            "provider_id": "company-oidc",
            "issuer": "https://id.example.test",
            "client_id": "nex-platform",
            "discovery_url": "https://id.example.test/.well-known/openid-configuration",
            "display_name": "Company OIDC",
        }
    )
    identity = build_external_identity_link(
        {
            "provider_id": "company-oidc",
            "external_subject": "opaque-subject",
            "tenant_id": "company",
            "subject_id": "employee-1001",
        },
        provider=provider,
    )
    repository = InMemoryOaFederatedIdentityRepository()
    repository.save_provider(provider)
    repository.save_identity(identity)
    sessions = _Sessions()
    response = OaFederatedLoginService(
        repository=repository,
        session_issuer=sessions,
        verifier_provider=_Verifiers(),
    ).login(
        {
            "provider_id": "company-oidc",
            "id_token": "private-id-token",
            "nonce": "browser-nonce",
            "requested_scopes": ["workspace:use"],
        }
    )
    serialized = json.dumps(response, sort_keys=True).lower()
    checks = {
        "oa_session_issued": response["session_id"] == "opaque-oa-session",
        "canonical_identity_used": sessions.payload == {
            "tenant_id": "company",
            "subject_id": "employee-1001",
            "requested_scopes": ["workspace:use"],
        },
        "federated_method_marked": response["metadata"]["auth_method"] == "federated_oidc",
        "provider_marked": response["metadata"]["provider_id"] == "company-oidc",
        "raw_id_token_absent": "private-id-token" not in serialized and response["metadata"]["raw_id_token_included"] is False,
        "raw_subject_absent": "opaque-subject" not in serialized and response["metadata"]["raw_external_subject_included"] is False,
        "external_profile_absent": response["metadata"]["external_profile_included"] is False,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_federated_login_orchestration_evidence.v1",
        "slice": "1286",
        "requirement": "S129",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_federated_login_orchestration_failed",
        "checks": checks,
        "session": response,
        "next_slice": "1287" if passed else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    return (
        "oa_federated_login_orchestration="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"session={bool((evidence.get('session') or {}).get('session_id'))} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_federated_login_orchestration()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
