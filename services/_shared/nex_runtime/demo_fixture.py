from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from nex_runtime.demo_database import DEMO_TENANT_ID, DemoDatabaseGuardError
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

DEMO_FIXTURE_SCHEMA_VERSION = "p8_demo_fixture.v1"
_DEMO_FIXTURE_FIELDS = {
    "schema_version",
    "fixture_id",
    "fixture_hash",
    "base_fixture",
    "tenant",
    "login_accounts",
    "project_memberships",
}


def load_demo_business_fixture(
    demo_fixture_path: Path,
    *,
    base_fixture_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the immutable Demo fixture and derive its tenant-scoped business data."""

    document = _read_object(demo_fixture_path, "demo_fixture_unreadable")
    if set(document) != _DEMO_FIXTURE_FIELDS:
        raise DemoDatabaseGuardError("demo_fixture_document_invalid")
    record = deepcopy(document)
    if record.get("schema_version") != DEMO_FIXTURE_SCHEMA_VERSION:
        raise DemoDatabaseGuardError("demo_fixture_schema_invalid")
    supplied_hash = validate_hash_ref(record.get("fixture_hash"))
    hash_input = deepcopy(record)
    hash_input.pop("fixture_hash")
    if semantic_sha256_hash_ref(hash_input) != supplied_hash:
        raise DemoDatabaseGuardError("demo_fixture_hash_mismatch")
    tenant = record.get("tenant")
    if not isinstance(tenant, Mapping) or tenant.get("tenant_id") != DEMO_TENANT_ID:
        raise DemoDatabaseGuardError("demo_fixture_tenant_invalid")

    base_ref = record.get("base_fixture")
    if not isinstance(base_ref, Mapping) or set(base_ref) != {
        "path",
        "fixture_hash",
    }:
        raise DemoDatabaseGuardError("demo_fixture_base_invalid")
    base = _read_object(base_fixture_path, "demo_fixture_base_unreadable")
    base_hash = validate_hash_ref(base.get("fixture_hash"))
    if base_hash != validate_hash_ref(base_ref.get("fixture_hash")):
        raise DemoDatabaseGuardError("demo_fixture_base_hash_mismatch")
    base_hash_input = deepcopy(base)
    base_hash_input.pop("fixture_hash")
    if semantic_sha256_hash_ref(base_hash_input) != base_hash:
        raise DemoDatabaseGuardError("demo_fixture_base_hash_mismatch")

    business_fixture = deepcopy(base)
    business_fixture["fixture_id"] = record["fixture_id"]
    business_fixture["tenant"] = dict(tenant)
    business_hash_input = deepcopy(business_fixture)
    business_hash_input.pop("fixture_hash")
    business_fixture["fixture_hash"] = semantic_sha256_hash_ref(business_hash_input)
    return record, business_fixture


def _read_object(path: Path, error_code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DemoDatabaseGuardError(error_code) from exc
    if not isinstance(value, Mapping):
        raise DemoDatabaseGuardError(error_code)
    return dict(value)
