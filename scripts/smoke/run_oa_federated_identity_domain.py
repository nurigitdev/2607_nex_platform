#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.federated_identities import (  # noqa: E402
    build_external_identity_link,
    build_federation_provider,
    external_identity_projection,
    federation_provider_projection,
    resolve_federated_identity,
)


def run_oa_federated_identity_domain() -> dict[str, Any]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    provider = build_federation_provider(
        {
            "provider_id": "company-oidc",
            "issuer": "https://id.example.test",
            "client_id": "nex-platform",
            "discovery_url": "https://id.example.test/.well-known/openid-configuration",
            "display_name": "Company OIDC",
        },
        now=now,
    )
    identity = build_external_identity_link(
        {
            "provider_id": "company-oidc",
            "external_subject": "opaque-external-subject",
            "tenant_id": "company",
            "subject_id": "employee-1001",
        },
        provider=provider,
        now=now,
    )
    resolution = resolve_federated_identity(
        {
            "issuer": provider["issuer"],
            "audience": [provider["client_id"]],
            "subject": "opaque-external-subject",
        },
        provider=provider,
        identity_link=identity,
    )
    provider_projection = federation_provider_projection(provider)
    identity_projection = external_identity_projection(identity)
    serialized = json.dumps(
        {
            "provider": provider_projection,
            "identity": identity_projection,
            "resolution": resolution,
        },
        sort_keys=True,
    ).lower()
    forbidden = (
        "opaque-external-subject",
        "access_token",
        "authorization",
        "client_secret",
        "email",
        "employee_id",
        "raw_id_token",
        "phone",
        "raw_profile",
    )
    checks = {
        "provider_active": provider["status"] == "ACTIVE",
        "rs256_only": provider["id_token_algorithms"] == ("RS256",),
        "exact_subject_digest_linking": (
            provider["subject_linking"] == "PREPROVISIONED_EXACT_SUBJECT_DIGEST"
            and len(identity["external_subject_digest"]) == 64
        ),
        "internal_identity_resolved": (
            resolution["tenant_id"] == "company"
            and resolution["subject_id"] == "employee-1001"
        ),
        "raw_subject_absent": not resolution["raw_external_subject_included"],
        "external_profile_absent": not resolution["external_profile_included"],
        "projection_private_material_absent": not any(
            token in serialized for token in forbidden
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_federated_identity_domain_evidence.v1",
        "slice": "1283",
        "requirement": "S129",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_federated_identity_domain_failed",
        "checks": checks,
        "provider": provider_projection,
        "identity": identity_projection,
        "resolution": resolution,
        "next_slice": "1284" if passed else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    return (
        "oa_federated_identity_domain="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"digest={len((evidence.get('identity') or {}).get('external_subject_digest') or '')} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_federated_identity_domain()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
