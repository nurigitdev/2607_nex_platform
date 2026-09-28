from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError

from nex_ae_api.generation_policy import build_generation_policy_package
from nex_ae_api.prompts import seed_ae_prompt_registry
from nex_ae_api.runtime_policy import resolve_runtime_policy
from nex_ae_api.runtime_policy_api import resolve_safe_prompt_binding
from nex_runtime.prompts import PromptRegistryStore, render_prompt_from_binding
from run_ae_runtime_policy_contract_observability import (
    run_ae_runtime_policy_contract_observability,
)


ROOT = Path(__file__).resolve().parents[1]
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def _json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _production_policy_artifacts():
    payload = {
        "user_message": "Summarize this document",
        "tenant_id": "tenant-contract",
        "user_id": "user-contract",
    }
    runtime_policy = resolve_runtime_policy(payload)
    store = PromptRegistryStore()
    seed_ae_prompt_registry(store)
    binding = resolve_safe_prompt_binding(
        store,
        binding_key=runtime_policy["prompt_contract_ref"]["prompt_binding_key"],
        prompt_version=runtime_policy["prompt_contract_ref"]["prompt_version"],
    )
    render_event = render_prompt_from_binding(
        store,
        binding_key=binding["binding_key"],
        variables={},
        request_id="request-contract",
        trace_id=TRACE_ID,
        user_prompt=payload["user_message"],
    )["render_event"]
    package = build_generation_policy_package(
        payload,
        runtime_policy=runtime_policy,
        prompt_binding=binding,
        prompt_render_event=render_event,
        retrieval_package={
            "retrieval_package_id": "retrieval-contract",
            "package_hash": "b" * 64,
            "status": "READY",
            "evidence_items": [{"evidence_id": "evidence-contract"}],
        },
    )
    return runtime_policy, binding, render_event, package


def test_production_policy_artifacts_match_canonical_contracts() -> None:
    runtime_policy, _, _, package = _production_policy_artifacts()
    schemas = {
        "intent": _json(
            "contracts/schemas/service/nex_ae_api/intent_decision.v1.schema.json"
        ),
        "runtime": _json(
            "contracts/schemas/service/nex_ae_api/runtime_policy.v1.schema.json"
        ),
        "package": _json(
            "contracts/schemas/service/nex_ae_api/"
            "generation_policy_package.v1.schema.json"
        ),
    }

    Draft202012Validator(schemas["intent"]).validate(
        runtime_policy["intent_decision"]
    )
    Draft202012Validator(schemas["runtime"]).validate(runtime_policy)
    Draft202012Validator(schemas["package"]).validate(package)


@pytest.mark.parametrize(
    ("schema_path", "fixture_path"),
    [
        (
            "contracts/schemas/service/nex_ae_api/intent_decision.v1.schema.json",
            "contracts/tests/negative/generation/"
            "ae_intent_decision.raw_prompt_leak.json",
        ),
        (
            "contracts/schemas/service/nex_ae_api/runtime_policy.v1.schema.json",
            "contracts/tests/negative/generation/"
            "ae_runtime_policy.provider_runtime_leak.json",
        ),
        (
            "contracts/schemas/service/nex_ae_api/"
            "generation_policy_package.v1.schema.json",
            "contracts/tests/negative/generation/"
            "ae_generation_policy_package.raw_evidence_leak.json",
        ),
    ],
)
def test_policy_contracts_reject_private_runtime_fields(
    schema_path: str,
    fixture_path: str,
) -> None:
    with pytest.raises(ValidationError):
        Draft202012Validator(_json(schema_path)).validate(_json(fixture_path))


def test_chat_contract_accepts_policy_lineage_and_rejects_raw_prompt() -> None:
    runtime_policy, binding, render_event, package = _production_policy_artifacts()
    chat = _json("contracts/examples/generation/ae_chat_interaction.pending.json")
    chat["generation"] = {
        "policy": {
            "policy_summary_schema_version": "ae_chat_runtime_policy_summary.v1",
            "runtime_policy_snapshot": runtime_policy,
            "prompt_binding": binding,
            "prompt_render_event_ref": {
                "prompt_render_event_id": render_event["prompt_render_event_id"],
                "rendered_prompt_hash": render_event["rendered_prompt_hash"],
                "user_prompt_hash": render_event["user_prompt_hash"],
            },
            "generation_policy_package": package,
            "raw_prompt_included": False,
            "provider_runtime_included": False,
        }
    }
    validator = Draft202012Validator(
        _json("contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json")
    )

    validator.validate(chat)
    leaking = deepcopy(chat)
    leaking["generation"]["policy"]["runtime_policy_snapshot"]["raw_prompt"] = (
        "private prompt"
    )
    with pytest.raises(ValidationError):
        validator.validate(leaking)


def test_openapi_exposes_runtime_policy_contracts() -> None:
    spec = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-ae-api.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert spec["info"]["version"] == "1.5.0"
    assert {
        "/api/v1/runtime-policies",
        "/api/v1/runtime-policies/resolve",
        "/api/v1/runtime-policies/prompt-bindings/{binding_key}",
    }.issubset(spec["paths"])
    assert spec["components"]["schemas"]["AeRuntimePolicy"][
        "x-nex-canonical-json-schema"
    ].endswith("runtime_policy.v1.schema.json")
    assert spec["components"]["schemas"]["AeGenerationPolicyPackage"][
        "x-nex-canonical-json-schema"
    ].endswith("generation_policy_package.v1.schema.json")


def test_runtime_policy_observability_allows_additive_contract_growth() -> None:
    result = run_ae_runtime_policy_contract_observability()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["contract_counts"]["schemas"] >= 96
    assert result["contract_counts"]["examples"] >= 150
    assert result["contract_counts"]["negative_examples"] >= 113
    assert result["contract_counts"]["openapi"] >= 7
