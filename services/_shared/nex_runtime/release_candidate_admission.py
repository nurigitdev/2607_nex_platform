from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import json
from typing import Any
from urllib.parse import urlsplit

from .postgres_targets import (
    POSTGRES_TEST_TARGETS,
    PostgresTargetConfigError,
    postgres_test_targets_public_projection,
    resolve_postgres_test_targets,
)


RELEASE_CANDIDATE_ADMISSION_SCHEMA_VERSION = (
    "platform_release_candidate_admission.v1"
)
RELEASE_CANDIDATE_ENABLE_ENV = "NEX_S140_RELEASE_CANDIDATE_ACCEPTANCE"
RELEASE_CANDIDATE_PROFILE_ENV = "NEX_S140_RELEASE_CANDIDATE_PROFILE"
RELEASE_CANDIDATE_PROFILE = "test_live"
BROWSER_VIEWPORTS_ENV = "NEX_S140_BROWSER_VIEWPORTS"
EXPECTED_BROWSER_VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}


@dataclass(frozen=True)
class ReleaseCandidateProviderAdmission:
    capability: str
    alias: str
    endpoint_env: str


RELEASE_CANDIDATE_PROVIDER_ADMISSIONS = (
    ReleaseCandidateProviderAdmission(
        "embedding", "embedding-default", "NEX_MO_REMOTE_EMBEDDING_URL"
    ),
    ReleaseCandidateProviderAdmission(
        "reranking", "reranker-default", "NEX_MO_REMOTE_RERANKER_URL"
    ),
    ReleaseCandidateProviderAdmission(
        "generation", "general-llm-default", "NEX_MO_VLLM_BASE_URL"
    ),
)

REQUIRED_MODE_VALUES = {
    "NEX_PERSISTENCE_MODE": "postgres",
    "NEX_MO_PROVIDER_MODE": "live",
    "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
    "NEX_AG_OPERATIONS_SOURCE_MODE": "api",
    "NEX_AE_AUTH_SESSION_MODE": "oa",
}
CANONICAL_PROVIDER_PROFILE_ENV = "NEX_MO_PROTECTED_LIVE_PROFILE"
CANONICAL_PROVIDER_PROFILES = frozenset({"dgx", "dgx_vllm"})
SENSITIVE_ENV_PARTS = (
    "API_KEY",
    "DATABASE_URL",
    "PASSWORD",
    "PRIVATE_KEY",
    "SECRET",
    "TOKEN",
)


def evaluate_release_candidate_admission(
    environ: Mapping[str, str],
) -> dict[str, Any]:
    env = dict(environ)
    if env.get(RELEASE_CANDIDATE_ENABLE_ENV) != "1":
        return _not_admitted(
            status="SKIPPED",
            failure_code="release_candidate_admission_not_enabled",
            issues=("activation_required",),
        )
    if env.get(RELEASE_CANDIDATE_PROFILE_ENV) != RELEASE_CANDIDATE_PROFILE:
        return _not_admitted(
            status="FAIL",
            failure_code="release_candidate_profile_not_allowed",
            issues=("test_live_profile_required",),
        )

    issues: list[str] = []
    resolved_databases = ()
    try:
        resolved_databases = resolve_postgres_test_targets(env)
    except PostgresTargetConfigError as exc:
        issues.append(str(exc))

    mode_checks = {
        name: str(env.get(name) or "").casefold() == expected.casefold()
        for name, expected in REQUIRED_MODE_VALUES.items()
    }
    issues.extend(
        f"mode_invalid:{name}"
        for name, passed in mode_checks.items()
        if not passed
    )

    requested_provider_profile = str(
        env.get(CANONICAL_PROVIDER_PROFILE_ENV) or ""
    )
    provider_profile_valid = (
        requested_provider_profile in CANONICAL_PROVIDER_PROFILES
    )
    if not provider_profile_valid:
        issues.append("canonical_provider_profile_required")

    providers = [
        {
            **asdict(spec),
            "configured": _valid_http_url(env.get(spec.endpoint_env)),
        }
        for spec in RELEASE_CANDIDATE_PROVIDER_ADMISSIONS
    ]
    issues.extend(
        f"provider_endpoint_invalid:{item['capability']}"
        for item in providers
        if not item["configured"]
    )

    configured_viewports = _configured_viewports(env.get(BROWSER_VIEWPORTS_ENV))
    viewport_inventory_valid = (
        len(configured_viewports) == len(EXPECTED_BROWSER_VIEWPORTS)
        and set(configured_viewports) == set(EXPECTED_BROWSER_VIEWPORTS)
    )
    if not viewport_inventory_valid:
        issues.append("browser_viewport_inventory_invalid")

    checks = {
        "five_test_databases_exact": len(resolved_databases)
        == len(POSTGRES_TEST_TARGETS),
        "service_local_database_identity": bool(resolved_databases)
        and len({item.database_url for item in resolved_databases})
        == len(POSTGRES_TEST_TARGETS),
        "protected_modes_exact": all(mode_checks.values()),
        "canonical_provider_profile": provider_profile_valid,
        "three_provider_capabilities_configured": len(providers) == 3
        and all(item["configured"] for item in providers),
        "provider_admission_model_independent": all(
            "model" not in item for item in providers
        ),
        "desktop_mobile_viewports_exact": viewport_inventory_valid,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not issues and not failed_checks
    result = {
        "admission_schema_version": RELEASE_CANDIDATE_ADMISSION_SCHEMA_VERSION,
        "slice": "1395",
        "requirement": "S140",
        "status": "PASS" if passed else "FAIL",
        "admitted": passed,
        "profile": RELEASE_CANDIDATE_PROFILE,
        "checks": checks,
        "failed_checks": failed_checks,
        "issues": sorted(set(issues)),
        "database_profile": (
            postgres_test_targets_public_projection(resolved_databases)
            if resolved_databases
            else _empty_database_projection()
        ),
        "provider_profile": {
            "profile": "dgx_vllm" if provider_profile_valid else None,
            "model_identity_required_for_admission": False,
            "capability_count": len(providers),
            "capabilities": providers,
            "endpoint_values_exposed": False,
            "credential_values_exposed": False,
        },
        "browser_profile": {
            "viewport_count": len(EXPECTED_BROWSER_VIEWPORTS),
            "viewports": [
                {"name": name, **dimensions}
                for name, dimensions in EXPECTED_BROWSER_VIEWPORTS.items()
            ],
            "configured_viewports": list(configured_viewports),
        },
        "actual_execution": {
            "postgresql": False,
            "remote_provider": False,
            "browser": False,
        },
        "redaction": {
            "status": "PASS",
            "database_urls_exposed": False,
            "provider_endpoints_exposed": False,
            "credentials_exposed": False,
        },
        "decision": {
            "protected_execution_admitted": passed,
            "next_slice": "1396" if passed else "blocked",
        },
    }
    _assert_sensitive_values_absent(result, env)
    return result


def _not_admitted(
    *,
    status: str,
    failure_code: str,
    issues: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "admission_schema_version": RELEASE_CANDIDATE_ADMISSION_SCHEMA_VERSION,
        "slice": "1395",
        "requirement": "S140",
        "status": status,
        "admitted": False,
        "failure_code": failure_code,
        "issues": list(issues),
        "actual_execution": {
            "postgresql": False,
            "remote_provider": False,
            "browser": False,
        },
        "decision": {
            "protected_execution_admitted": False,
            "next_slice": "blocked",
        },
    }


def _configured_viewports(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    items = tuple(item.strip().casefold() for item in value.split(",") if item.strip())
    if len(items) != len(set(items)):
        return ()
    return items


def _valid_http_url(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlsplit(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def _empty_database_projection() -> dict[str, Any]:
    return {
        "schema_version": "platform_postgres_test_targets.v1",
        "profile": "test",
        "service_count": 0,
        "targets": [],
        "database_urls_exposed": False,
    }


def _assert_sensitive_values_absent(
    result: Mapping[str, Any],
    environ: Mapping[str, str],
) -> None:
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    leaked = [
        name
        for name, value in environ.items()
        if value
        and any(part in name.upper() for part in SENSITIVE_ENV_PARTS)
        and value in serialized
    ]
    if leaked:
        raise ValueError(
            "release candidate admission evidence contains sensitive values: "
            + ",".join(sorted(leaked))
        )
