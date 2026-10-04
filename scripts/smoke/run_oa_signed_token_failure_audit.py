#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import time
from typing import Any, Mapping

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services/_shared", ROOT / "services/nex-oa"):
    sys.path.insert(0, str(path))

from nex_oa.auth_events import InMemoryOaAuthEventRepository  # noqa: E402
from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER  # noqa: E402
from nex_oa.service_principal_repository import (  # noqa: E402
    InMemoryOaServicePrincipalRepository,
)
from nex_oa.service_principal_service import (  # noqa: E402
    OaServicePrincipalService,
)
from nex_oa.signed_token_api import (  # noqa: E402
    OA_INTROSPECTION_SCOPE,
    OA_REVOCATION_SCOPE,
    register_signed_token_routes,
)
from nex_oa.signed_token_repository import (  # noqa: E402
    InMemoryOaSignedTokenRepository,
)
from nex_oa.signing_key_service import OaSigningKeyService  # noqa: E402
from nex_oa.token_exchange_service import (  # noqa: E402
    OaClientCredentialTokenExchangeService,
)
from nex_oa.token_signing import InMemoryOaRsaSigningProvider  # noqa: E402
from nex_oa.token_validation_service import (  # noqa: E402
    OaSignedTokenValidationService,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
)


SCHEMA_VERSION = "oa_signed_token_failure_audit.v1"


def run_oa_signed_token_failure_audit() -> dict[str, Any]:
    runtime = _runtime()
    client = runtime["client"]
    caller = str(runtime["caller"])
    target = str(runtime["target"])
    headers = {"Authorization": f"Bearer {caller}"}

    rejected_exchange = client.post(
        "/api/v1/auth/service-token",
        json=_token_request(client_secret="not-the-secret"),
    )
    rejected_caller = client.post(
        "/api/v1/auth/introspect",
        json={"token": target, "audience": "nex-cx"},
    )
    inactive_target = client.post(
        "/api/v1/auth/introspect",
        json={"token": "malformed.token.value", "audience": "nex-cx"},
        headers=headers,
    )
    rejected_target = client.post(
        "/api/v1/auth/revoke",
        json={
            "token": "malformed.token.value",
            "audience": "nex-cx",
            "reason_code": "OPERATOR",
        },
        headers=headers,
    )

    events = runtime["auth_events"].events
    serialized = json.dumps(events, sort_keys=True)
    event_types = [event["event_type"] for event in events]
    operations = [event["details"].get("operation") for event in events]
    checks = {
        "credential_exchange_rejected": (
            rejected_exchange.status_code == 401
            and rejected_exchange.json().get("error_code")
            == "oa.service_credential_rejected"
        ),
        "untrusted_service_caller_rejected": rejected_caller.status_code == 401,
        "invalid_introspection_target_inactive": (
            inactive_target.status_code == 200
            and inactive_target.json().get("active") is False
            and inactive_target.json().get("reason_code")
            == "oa.token_encoding_invalid"
        ),
        "invalid_revocation_target_rejected": (
            rejected_target.status_code == 401
            and rejected_target.json().get("error_code")
            == "oa.token_encoding_invalid"
        ),
        "failure_events_complete": event_types
        == [
            "SERVICE_AUTH_FAILED",
            "SERVICE_AUTH_FAILED",
            "TOKEN_VALIDATION_FAILED",
            "TOKEN_VALIDATION_FAILED",
        ],
        "operations_bounded": operations
        == [
            "service_token_exchange",
            "token_introspection_authorization",
            "token_introspection",
            "token_revocation",
        ],
        "outcomes_blocked": all(
            event.get("outcome") == "BLOCKED" for event in events
        ),
        "raw_material_absent": all(
            value not in serialized
            for value in (
                "api-secret",
                "not-the-secret",
                caller,
                target,
                "malformed.token.value",
            )
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1293",
        "requirement": "S130",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "oa_signed_token_failure_audit_failed"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "scenario_count": 4,
            "event_count": len(events),
            "service_auth_failure_count": event_types.count(
                "SERVICE_AUTH_FAILED"
            ),
            "token_validation_failure_count": event_types.count(
                "TOKEN_VALIDATION_FAILED"
            ),
            "raw_material_exposure_count": 0
            if checks["raw_material_absent"]
            else 1,
        },
        "event_types": event_types,
        "operations": operations,
        "next_slice": "1294" if passed else "blocked",
    }


def _runtime() -> dict[str, Any]:
    now = int(time())
    principals = OaServicePrincipalService(
        InMemoryOaServicePrincipalRepository()
    )
    principals.upsert_principal(
        {
            "principal_id": "cx-s130-audit",
            "service_id": "nex-cx",
            "display_name": "CX S130 Audit",
            "allowed_audiences": ["nex-oa", "nex-cx"],
            "allowed_scopes": [
                OA_INTROSPECTION_SCOPE,
                OA_REVOCATION_SCOPE,
                "document:read",
            ],
            "expected_revision": 0,
        }
    )
    principals.issue_credential(
        "cx-s130-audit",
        lifetime_days=1,
        now_epoch=now - 10,
        credential_id="cred-cx-s130-audit",
        client_secret="api-secret",
    )
    signer = InMemoryOaRsaSigningProvider()
    reference = "file:///tmp/oa-key-s130-audit"
    signer.generate_key(reference)
    keys = OaSigningKeyService(
        repository=InMemoryOaSignedTokenRepository(),
        deployment_profile="test",
    )
    keys.register_key(
        {
            "key_id": "oa-key-s130-audit",
            "issuer": PRODUCTION_TOKEN_ISSUER,
            "public_jwk": signer.public_jwk(
                reference, key_id="oa-key-s130-audit"
            ),
            "private_key_ref": reference,
            "published_at": now - 330,
            "activate_at": now,
            "sign_until": now + 600,
            "verify_until": now + 930,
        }
    )
    keys.set_key_state(
        "oa-key-s130-audit",
        target_state="ACTIVE",
        expected_revision=1,
        now_epoch=now,
    )
    exchange = OaClientCredentialTokenExchangeService(
        principal_service=principals,
        signing_key_service=keys,
        signing_provider=signer,
    )
    validation = OaSignedTokenValidationService(
        signing_key_service=keys,
        principal_service=principals,
    )
    auth_events = InMemoryOaAuthEventRepository()
    app = build_service_app(
        SERVICE_SPECS["nex-oa"], include_oa_mock_auth_routes=False
    )
    register_signed_token_routes(
        app,
        token_exchange_service=exchange,
        validation_service=validation,
        signing_key_service=keys,
        audit_emitter=OperationalEventEmitter(
            service_id="nex-oa", store=InMemoryOperationalEventStore()
        ),
        auth_event_repository=auth_events,
    )
    caller = exchange.exchange(
        _token_request(
            audience="nex-oa",
            scope=f"{OA_INTROSPECTION_SCOPE} {OA_REVOCATION_SCOPE}",
        )
    )["access_token"]
    target = exchange.exchange(_token_request())["access_token"]
    return {
        "client": TestClient(app),
        "caller": caller,
        "target": target,
        "auth_events": auth_events,
    }


def _token_request(**changes: object) -> dict[str, object]:
    return {
        "grant_type": "client_credentials",
        "credential_id": "cred-cx-s130-audit",
        "client_secret": "api-secret",
        "audience": "nex-cx",
        "scope": "document:read",
        **changes,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "oa_signed_token_failure_audit="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"scenarios={summary.get('scenario_count', 0)} "
        f"events={summary.get('event_count', 0)} "
        f"service_auth={summary.get('service_auth_failure_count', 0)} "
        f"token_validation={summary.get('token_validation_failure_count', 0)} "
        f"exposure={summary.get('raw_material_exposure_count', 1)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_signed_token_failure_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
