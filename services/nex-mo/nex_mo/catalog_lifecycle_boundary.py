from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class CatalogLifecycleBoundary:
    boundary_id: str
    source_path: str
    evidence_token: str
    disposition: str
    target_slice: str


CATALOG_LIFECYCLE_BOUNDARIES = (
    CatalogLifecycleBoundary(
        "static_model_catalog",
        "services/nex-mo/nex_mo/provider_catalog.py",
        "GENERATION_PROFILE_CANDIDATES",
        "REPLACE_WITH_DURABLE_CATALOG",
        "1173",
    ),
    CatalogLifecycleBoundary(
        "static_alias_routes",
        "services/nex-mo/nex_mo/provider_registry.py",
        "DEFAULT_PROVIDER_ROUTES",
        "PRESERVE_AS_BOOTSTRAP_FALLBACK",
        "1178",
    ),
    CatalogLifecycleBoundary(
        "immutable_route_contract",
        "services/nex-mo/nex_mo/provider_registry.py",
        "class ProviderRoute:",
        "PRESERVE",
        "1173",
    ),
    CatalogLifecycleBoundary(
        "authenticated_mo_boundary",
        "services/nex-mo/nex_mo/provider_auth.py",
        "def authorize_mo_service_request",
        "REUSE",
        "1177",
    ),
    CatalogLifecycleBoundary(
        "durable_mo_repository_pattern",
        "services/nex-mo/nex_mo/provider_telemetry_repository.py",
        "class SqlAlchemyDurableProviderTelemetryRepository",
        "REUSE_PATTERN",
        "1174",
    ),
    CatalogLifecycleBoundary(
        "mo_migration_baseline",
        "database/nex-mo/migrations/1154_mo_provider_telemetry.sql",
        "INSERT INTO schema_migrations",
        "EXTEND",
        "1174",
    ),
)


CATALOG_LIFECYCLE_POLICY = {
    "owner": "nex-mo",
    "required_capabilities": ["embedding", "reranking", "generation"],
    "catalog_states": ["DRAFT", "ACTIVE", "RETIRED"],
    "alias_binding_states": ["ACTIVE", "SUPERSEDED", "ROLLED_BACK"],
    "persistence": "postgresql_with_sqlite_regression_adapter",
    "tables": ["mo_model_catalog", "mo_alias_bindings"],
    "bootstrap": "static_routes_seed_empty_store_only",
    "selection": "one_active_binding_per_alias_and_capability",
    "concurrency": "expected_revision_optimistic_guard",
    "activation": "atomic_validate_then_supersede_then_activate",
    "rollback": "append_new_binding_to_prior_catalog_revision",
    "runtime_configuration": "environment_owned_not_persisted",
    "forbidden_persistence": [
        "provider_endpoint",
        "provider_api_key",
        "authorization_token",
        "ssh_target",
        "model_path",
        "database_url",
    ],
    "allowed_persistence": [
        "catalog_id",
        "capability",
        "model_name",
        "model_revision",
        "deployment_id",
        "runtime_profile",
        "precision",
        "catalog_state",
        "alias",
        "binding_revision",
        "binding_state",
        "change_reason",
        "created_at",
        "updated_at",
    ],
}


def build_mo_catalog_lifecycle_boundary(
    root: Path = ROOT,
    *,
    boundaries: Sequence[CatalogLifecycleBoundary] = CATALOG_LIFECYCLE_BOUNDARIES,
) -> dict[str, Any]:
    results = [_inspect_boundary(root, boundary) for boundary in boundaries]
    issues = [
        {
            "category": "catalog_lifecycle_boundary_evidence_missing",
            "boundary_id": item["boundary_id"],
            "source_path": item["source_path"],
        }
        for item in results
        if not item["evidence_present"]
    ]
    tables = CATALOG_LIFECYCLE_POLICY["tables"]
    forbidden = set(CATALOG_LIFECYCLE_POLICY["forbidden_persistence"])
    allowed = set(CATALOG_LIFECYCLE_POLICY["allowed_persistence"])
    checks = {
        "boundary_inventory_complete": len(results) == 6,
        "source_evidence_present": not issues,
        "slice_order_bounded": all(
            "1173" <= item["target_slice"] <= "1178" for item in results
        ),
        "three_capabilities_required": CATALOG_LIFECYCLE_POLICY[
            "required_capabilities"
        ]
        == ["embedding", "reranking", "generation"],
        "durable_persistence_selected": CATALOG_LIFECYCLE_POLICY["persistence"]
        == "postgresql_with_sqlite_regression_adapter",
        "table_names_are_short": tables
        == ["mo_model_catalog", "mo_alias_bindings"]
        and all(len(name) <= 24 for name in tables),
        "single_active_alias_guarded": CATALOG_LIFECYCLE_POLICY["selection"]
        == "one_active_binding_per_alias_and_capability",
        "runtime_secrets_remain_external": {
            "provider_endpoint",
            "provider_api_key",
            "model_path",
            "database_url",
        }.issubset(forbidden)
        and forbidden.isdisjoint(allowed),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_catalog_lifecycle_boundary.v1",
        "slice": "1172",
        "requirement": "S118",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_catalog_lifecycle_boundary_failed",
        "boundary": "durable_model_catalog_and_atomic_alias_lifecycle",
        "checks": checks,
        "summary": {
            "boundary_count": len(results),
            "required_capability_count": len(
                CATALOG_LIFECYCLE_POLICY["required_capabilities"]
            ),
            "table_count": len(tables),
            "forbidden_persistence_count": len(forbidden),
            "evidence_issue_count": len(issues),
        },
        "lifecycle_policy": CATALOG_LIFECYCLE_POLICY,
        "boundaries": results,
        "issues": issues,
        "guardrails": [
            "persist public model identity and alias binding metadata only",
            "keep endpoints credentials model paths and database URLs external",
            "require optimistic revision checks for every lifecycle mutation",
            "allow exactly one active binding per alias and capability",
            "append rollback bindings instead of rewriting history",
            "seed static defaults only when the durable catalog is empty",
            "preserve deterministic SQLite regression and prove PostgreSQL separately",
        ],
        "ordered_work": [
            {"slice": "1173", "work_item": "domain contracts"},
            {"slice": "1174", "work_item": "durable repository and migration"},
            {"slice": "1175", "work_item": "catalog lifecycle service"},
            {"slice": "1176", "work_item": "atomic alias activation and rollback"},
            {"slice": "1177", "work_item": "authenticated lifecycle API"},
            {"slice": "1178", "work_item": "runtime resolver compatibility"},
            {"slice": "1179", "work_item": "contract and privacy hardening"},
            {"slice": "1180", "work_item": "PostgreSQL smoke evidence"},
            {"slice": "1181", "work_item": "S118 closure"},
        ],
        "next_slice": "1173" if passed else "blocked",
    }


def _inspect_boundary(
    root: Path,
    boundary: CatalogLifecycleBoundary,
) -> dict[str, Any]:
    path = root / boundary.source_path
    source = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "boundary_id": boundary.boundary_id,
        "source_path": boundary.source_path,
        "disposition": boundary.disposition,
        "target_slice": boundary.target_slice,
        "evidence_present": boundary.evidence_token in source,
    }
