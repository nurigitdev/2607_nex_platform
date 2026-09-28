#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT,
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "_shared",
):
    sys.path.insert(0, str(path))

from nex_ae_api.generation_policy import build_generation_policy_package  # noqa: E402
from nex_ae_api.prompts import seed_ae_prompt_registry  # noqa: E402
from nex_ae_api.runtime_policy import resolve_runtime_policy  # noqa: E402
from nex_ae_api.runtime_policy_api import resolve_safe_prompt_binding  # noqa: E402
from nex_ae_api.workspace_chat_observability import (  # noqa: E402
    observe_workspace_chat_state,
)
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter  # noqa: E402
from nex_runtime.prompts import PromptRegistryStore, render_prompt_from_binding  # noqa: E402
from scripts.quality.validate_contracts import validate_contract_tree  # noqa: E402


def _load_json(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def run_ae_runtime_policy_contract_observability() -> dict[str, Any]:
    source = {
        "user_message": "private contract summary",
        "tenant_id": "tenant-smoke",
        "user_id": "user-smoke",
    }
    runtime_policy = resolve_runtime_policy(source)
    prompt_store = PromptRegistryStore()
    seed_ae_prompt_registry(prompt_store)
    binding = resolve_safe_prompt_binding(
        prompt_store,
        binding_key=runtime_policy["prompt_contract_ref"]["prompt_binding_key"],
        prompt_version=runtime_policy["prompt_contract_ref"]["prompt_version"],
    )
    render_event = render_prompt_from_binding(
        prompt_store,
        binding_key=binding["binding_key"],
        variables={},
        request_id="request-1029",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        user_prompt=source["user_message"],
    )["render_event"]
    package = build_generation_policy_package(
        source,
        runtime_policy=runtime_policy,
        prompt_binding=binding,
        prompt_render_event=render_event,
        retrieval_package={
            "retrieval_package_id": "retrieval-1029",
            "package_hash": "b" * 64,
            "status": "READY",
            "evidence_items": [{"evidence_id": "evidence-1029"}],
        },
    )
    intent_schema = _load_json(
        "contracts/schemas/service/nex_ae_api/intent_decision.v1.schema.json"
    )
    runtime_schema = _load_json(
        "contracts/schemas/service/nex_ae_api/runtime_policy.v1.schema.json"
    )
    package_schema = _load_json(
        "contracts/schemas/service/nex_ae_api/"
        "generation_policy_package.v1.schema.json"
    )
    Draft202012Validator(intent_schema).validate(runtime_policy["intent_decision"])
    Draft202012Validator(runtime_schema).validate(runtime_policy)
    Draft202012Validator(package_schema).validate(package)

    event_store = InMemoryOperationalEventStore()
    event = observe_workspace_chat_state(
        OperationalEventEmitter(service_id="nex-ae-api", store=event_store),
        {
            "interaction_id": "interaction-1029",
            "workspace_id": "workspace-1029",
            "status": "COMPLETED",
            "cx_status": "COMPLETED",
            "request_id": "request-1029",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "generation": {
                "output_preview": "private response",
                "policy": {
                    "runtime_policy_snapshot": runtime_policy,
                    "generation_policy_package": package,
                },
            },
            "retrieval": {"cx_retrieval_package_id": "private-retrieval"},
            "artifact_refs": [],
        },
    ).event
    openapi = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-ae-api.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    validation = validate_contract_tree(ROOT / "contracts")
    serialized_event = json.dumps(event, sort_keys=True)
    details = event["details"]
    checks = {
        "contract_tree_valid": validation.ok,
        "schema_count_hardened": validation.schema_count == 96,
        "positive_fixtures_hardened": validation.example_count == 150,
        "negative_fixtures_hardened": validation.negative_example_count == 113,
        "intent_contract_valid": runtime_policy["intent_decision"][
            "intent_decision_schema_version"
        ]
        == "ae_intent_decision.v1",
        "runtime_contract_valid": runtime_policy["runtime_policy_schema_version"]
        == "ae_runtime_policy.v1",
        "package_contract_valid": package[
            "generation_policy_package_schema_version"
        ]
        == "ae_generation_policy_package.v1",
        "openapi_version_hardened": openapi["info"]["version"] == "1.1.0",
        "runtime_routes_documented": all(
            route in openapi["paths"]
            for route in (
                "/api/v1/runtime-policies",
                "/api/v1/runtime-policies/resolve",
                "/api/v1/runtime-policies/prompt-bindings/{binding_key}",
            )
        ),
        "policy_event_metadata_bound": details["execution_mode"]
        == "DOCUMENT_SUMMARY"
        and details["policy_snapshot_hash"] == package["policy_snapshot_hash"]
        and details["generation_policy_package_hash"]
        == package["client_package_hash"],
        "event_privacy_flags_safe": details["prompt_content_included"] is False
        and details["response_content_included"] is False
        and details["provider_detail_included"] is False,
        "private_content_excluded": "private contract summary"
        not in serialized_event
        and "private response" not in serialized_event
        and "private-retrieval" not in serialized_event,
    }
    return {
        "smoke_schema_version": "ae_runtime_policy_contract_observability_smoke.v1",
        "slice": "1029",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "contract_counts": {
            "schemas": validation.schema_count,
            "examples": validation.example_count,
            "negative_examples": validation.negative_example_count,
            "openapi": validation.openapi_count,
        },
        "postgresql_required": False,
        "remote_provider_required": False,
        "next_slice": "1030",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks", {})
    return (
        "ae_runtime_policy_contract_observability="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_runtime_policy_contract_observability()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
