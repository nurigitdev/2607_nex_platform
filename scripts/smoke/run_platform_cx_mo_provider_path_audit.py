#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_cx_mo_provider_path_audit.v1"


@dataclass(frozen=True)
class ProviderClientEvidence:
    capability: str
    relative_path: str
    class_name: str
    mo_route: str
    alias: str
    timeout_environment: str


CLIENTS = (
    ProviderClientEvidence(
        "embedding",
        "services/nex-cx/nex_cx/embedding_index.py",
        "HttpMoEmbeddingClient",
        "/api/v1/embeddings",
        "mock-embedding-default",
        "NEX_CX_MO_EMBEDDING_TIMEOUT_SECONDS",
    ),
    ProviderClientEvidence(
        "reranking",
        "services/nex-cx/nex_cx/retrieval.py",
        "HttpMoRerankClient",
        "/api/v1/rerank",
        "mock-reranker-default",
        "NEX_CX_MO_RERANKER_TIMEOUT_SECONDS",
    ),
    ProviderClientEvidence(
        "generation",
        "services/nex-cx/nex_cx/generation.py",
        "HttpMoGenerationClient",
        "/api/v1/generations",
        "general-llm-default",
        "NEX_CX_MO_GENERATION_TIMEOUT_SECONDS",
    ),
)
REMOTE_PROVIDER_ENV = re.compile(
    r"NEX_MO_(?:REMOTE_(?:EMBEDDING|RERANKER)_URL|"
    r"VLLM_(?:BASE_URL|CHAT_COMPLETIONS_URL|MODELS_URL))"
)
UPSTREAM_BUDGET_ENV = {
    "embedding": (
        "NEX_MO_REMOTE_EMBEDDING_TIMEOUT_SECONDS",
        "NEX_MO_EMBEDDING_MAX_ATTEMPTS",
    ),
    "reranking": (
        "NEX_MO_REMOTE_RERANKER_TIMEOUT_SECONDS",
        "NEX_MO_RERANKER_MAX_ATTEMPTS",
    ),
    "generation": (
        "NEX_MO_VLLM_TIMEOUT_SECONDS",
        "NEX_MO_GENERATION_MAX_ATTEMPTS",
    ),
}


def run_platform_cx_mo_provider_path_audit(root: Path = ROOT) -> dict[str, Any]:
    env_example = _read_text(root / ".env.example")
    clients = []
    for item in CLIENTS:
        source = _read_text(root / item.relative_path)
        uses_shared_timeout_policy = (
            "resolve_cx_mo_timeout_budget" in source
            and f'"{item.capability}"' in source
        )
        clients.append(
            {
                "capability": item.capability,
                "path": item.relative_path,
                "class_name": item.class_name,
                "mo_route": item.mo_route,
                "alias": item.alias,
                "present": f"class {item.class_name}" in source,
                "route_present": item.mo_route in source,
                "alias_present": item.alias in source,
                "service_token": 'audience="nex-mo"' in source,
                "request_id": '"X-Request-ID"' in source,
                "traceparent": '"traceparent"' in source,
                "uses_shared_timeout_policy": uses_shared_timeout_policy,
                "timeout_seconds": (
                    _env_number(env_example, item.timeout_environment)
                    if uses_shared_timeout_policy
                    else _client_timeout_seconds(source)
                ),
            }
        )
    provider_api = _read_text(root / "services/nex-mo/nex_mo/providers.py")
    provider_registry = _read_text(
        root / "services/nex-mo/nex_mo/provider_registry.py"
    )
    cx_root = root / "services/nex-cx/nex_cx"
    direct_provider_references = _direct_provider_references(cx_root, root=root)
    upstream_timeouts = {
        capability: _env_number(env_example, names[0])
        for capability, names in UPSTREAM_BUDGET_ENV.items()
    }
    upstream_attempts = {
        capability: _env_number(env_example, names[1])
        for capability, names in UPSTREAM_BUDGET_ENV.items()
    }
    retry_after = _env_number(env_example, "NEX_MO_RETRY_AFTER_MAX_SECONDS")
    safety_margin = _env_number(
        env_example, "NEX_CX_MO_TIMEOUT_SAFETY_MARGIN_SECONDS"
    )
    minimum_timeouts = {
        capability: _minimum_timeout(
            upstream_timeouts[capability],
            upstream_attempts[capability],
            retry_after,
            safety_margin,
        )
        for capability in UPSTREAM_BUDGET_ENV
    }
    timeout_budget_safe = all(
        isinstance(item["timeout_seconds"], (int, float))
        and isinstance(minimum_timeouts[item["capability"]], (int, float))
        and item["timeout_seconds"] >= minimum_timeouts[item["capability"]]
        for item in clients
    )
    checks = {
        "cx_has_three_mo_capability_clients": all(item["present"] for item in clients),
        "cx_calls_only_mo_capability_routes": (
            all(item["route_present"] for item in clients)
            and not direct_provider_references
        ),
        "cx_mo_clients_propagate_service_identity_and_trace": all(
            item[key]
            for item in clients
            for key in ("service_token", "request_id", "traceparent")
        ),
        "mo_exposes_three_capability_routes": all(
            item.mo_route in provider_api for item in CLIENTS
        ),
        "cx_aliases_resolve_in_mo_registry": all(
            item.alias in provider_registry for item in CLIENTS
        ),
        "provider_hosts_are_not_visible_to_cx": not direct_provider_references,
        "cx_uses_shared_timeout_policy": all(
            item["uses_shared_timeout_policy"] for item in clients
        ),
        "cx_timeout_budget_covers_mo_retries": timeout_budget_safe,
    }
    issues = [name for name, passed in checks.items() if not passed]
    profile_materialized = all(
        token in env_example
        for token in (
            "NEX_MO_BASE_URL=",
            "NEX_CX_TO_MO_SERVICE_TOKEN=",
            "NEX_CX_EMBEDDING_ALIAS=",
            "NEX_CX_RERANKER_ALIAS=",
        )
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1307",
        "requirement": "S131",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": None if not issues else "platform_cx_mo_provider_path_audit_failed",
        "checks": checks,
        "issues": issues,
        "clients": clients,
        "direct_provider_references": direct_provider_references,
        "findings": {
            "cx_mo_client_count": len(clients),
            "mo_capability_route_count": len(CLIENTS),
            "direct_provider_reference_count": len(direct_provider_references),
            "cx_client_timeout_seconds": {
                item["capability"]: item["timeout_seconds"] for item in clients
            },
            "mo_upstream_timeout_seconds": upstream_timeouts,
            "mo_upstream_max_attempts": upstream_attempts,
            "minimum_cx_client_timeout_seconds": minimum_timeouts,
            "timeout_budget_safe": timeout_budget_safe,
            "mock_named_live_capability_alias_count": sum(
                item.alias.startswith("mock-") for item in CLIENTS
            ),
            "environment_example_materializes_cx_mo_activation": profile_materialized,
        },
        "refactoring_candidates": [
            {
                "priority": "P0",
                "owner": "nex-cx/nex-mo",
                "gap": "keep CX-to-MO timeout budgets synchronized with MO retry policy",
                "target_requirement": "S132",
                "status": "RESOLVED",
            },
            {
                "priority": "P1",
                "owner": "nex-mo",
                "gap": "introduce capability-neutral canonical aliases while preserving mock-named compatibility aliases",
                "target_requirement": "S132/S136",
            },
            {
                "priority": "P1",
                "owner": "platform_integration",
                "gap": "materialize MO base URL, CX service identity, aliases, and provider mode in one runtime profile",
                "target_requirement": "S132",
            },
        ],
        "decision": {
            "mo_is_only_provider_host_owner": True,
            "cx_uses_mo_alias_contracts": True,
            "s131_timeout_gap_was_recorded": True,
            "current_timeout_budget_is_accepted_live_state": timeout_budget_safe,
            "mutation_performed": False,
            "next_slice": "1308",
        },
    }


def _client_timeout_seconds(source: str) -> float | None:
    match = re.search(r"timeout_seconds:\s*float\s*=\s*([0-9]+(?:\.[0-9]+)?)", source)
    return float(match.group(1)) if match else None


def _minimum_timeout(
    upstream_timeout: float | None,
    attempts: float | None,
    retry_after: float | None,
    safety_margin: float | None,
) -> float | None:
    if (
        upstream_timeout is None
        or attempts is None
        or retry_after is None
        or safety_margin is None
    ):
        return None
    return (
        upstream_timeout * attempts
        + retry_after * max(0, attempts - 1)
        + safety_margin
    )


def _env_number(source: str, name: str) -> float | None:
    match = re.search(rf"^{re.escape(name)}=([0-9]+(?:\.[0-9]+)?)$", source, re.MULTILINE)
    return float(match.group(1)) if match else None


def _direct_provider_references(path: Path, *, root: Path) -> list[dict[str, str]]:
    if not path.is_dir():
        return []
    findings = []
    for candidate in path.rglob("*.py"):
        for env_name in sorted(set(REMOTE_PROVIDER_ENV.findall(_read_text(candidate)))):
            findings.append(
                {
                    "environment": env_name,
                    "path": str(candidate.relative_to(root)),
                }
            )
    return findings


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_cx_mo_provider_path=fail issues={len(evidence.get('issues') or [])}"
    findings = evidence.get("findings") or {}
    return (
        "platform_cx_mo_provider_path=pass "
        f"clients={findings.get('cx_mo_client_count', 0)} "
        f"routes={findings.get('mo_capability_route_count', 0)} "
        f"direct={findings.get('direct_provider_reference_count', 0)} "
        f"timeout_safe={findings.get('timeout_budget_safe')} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_cx_mo_provider_path_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
