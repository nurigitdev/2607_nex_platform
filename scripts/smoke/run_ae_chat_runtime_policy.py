#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-ae-api", ROOT / "services" / "_shared"):
    sys.path.insert(0, str(path))

from fastapi.testclient import TestClient  # noqa: E402

from nex_ae_api.chat import ChatInteractionStore, register_chat_routes  # noqa: E402
from nex_ae_api.prompts import seed_ae_prompt_registry  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
from nex_runtime.prompts import PromptRegistryStore  # noqa: E402


class GenerationClient:
    def __init__(self) -> None:
        self.payload = None

    def create_generation(self, payload, *, request_id, trace_id):
        self.payload = payload
        retrieval = payload["retrieval_package_ref"]
        return {
            "cx_generation_id": "cx-smoke-policy",
            "status": "COMPLETED",
            "alias": payload["alias"],
            "provider_capability": payload["provider_capability"],
            "mo_generation_id": "mo-smoke-policy",
            "request_metadata": {
                "grounding_required": True,
                "retrieval_package_id": retrieval["retrieval_package_id"],
                "retrieval_package_hash": retrieval["package_hash"],
                "selected_evidence_count": 1,
            },
            "response_metadata": {
                "finish_reason": "STOP",
                "output_preview": "summary",
            },
            "usage": {"total_tokens": 5},
        }


class RetrievalClient:
    def create_retrieval_context(self, payload, *, request_id, trace_id):
        return {
            "retrieval_package_id": "retrieval-smoke-policy",
            "package_hash": "b" * 64,
            "status": "READY",
            "purpose": payload["purpose"],
            "evidence_items": [
                {
                    "evidence_id": "evidence-smoke-policy",
                    "citation_label": "[1]",
                    "text": "private smoke evidence",
                    "quality_flags": [],
                }
            ],
            "score_summary": {"best_score": 0.9, "confidence_bucket": "READY"},
            "warnings": [],
        }


def run_ae_chat_runtime_policy() -> dict[str, Any]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    chats = ChatInteractionStore()
    prompts = PromptRegistryStore()
    seed_ae_prompt_registry(prompts)
    generation = GenerationClient()
    register_chat_routes(
        app,
        store=chats,
        cx_client=generation,
        retrieval_client=RetrievalClient(),
        prompt_store=prompts,
    )
    token = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    response = TestClient(app).post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": "interaction-smoke-policy",
            "user_message": "private document summary please",
        },
        headers={"Authorization": f"Bearer {token.access_token}"},
    )
    body = response.json()
    policy = body.get("generation", {}).get("policy", {})
    package = policy.get("generation_policy_package", {})
    serialized_package = json.dumps(package, sort_keys=True)
    event_id = policy.get("prompt_render_event_ref", {}).get(
        "prompt_render_event_id"
    )
    checks = {
        "request_completed": response.status_code == 200
        and body.get("status") == "COMPLETED",
        "summary_mode": package.get("execution_mode") == "DOCUMENT_SUMMARY",
        "summary_prompt": package.get("prompt_contract_ref", {}).get(
            "prompt_binding_key"
        )
        == "ae.document_summary.default",
        "retrieval_bound": package.get("retrieval_package_ref", {}).get(
            "retrieval_package_id"
        )
        == "retrieval-smoke-policy",
        "evidence_ids_bound": package.get("selected_evidence_ids")
        == ["evidence-smoke-policy"],
        "policy_hash_bound": len(package.get("policy_snapshot_hash", "")) == 64,
        "package_hash_bound": len(package.get("client_package_hash", "")) == 64,
        "cx_hash_matches": generation.payload.get("client_package_hash")
        == package.get("client_package_hash"),
        "render_event_persisted": prompts.get_render_event(event_id) is not None,
        "chat_policy_persisted": chats.get("interaction-smoke-policy")["generation"][
            "policy"
        ]["generation_policy_package"]["client_package_hash"]
        == package.get("client_package_hash"),
        "raw_user_excluded": "private document summary please"
        not in serialized_package,
        "raw_evidence_excluded": "private smoke evidence" not in serialized_package,
        "provider_runtime_excluded": "api_key" not in serialized_package,
    }
    return {
        "smoke_schema_version": "ae_chat_runtime_policy_smoke.v1",
        "slice": "1028",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "remote_provider_required": False,
        "postgresql_required": False,
        "next_slice": "1029",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks", {})
    return (
        "ae_chat_runtime_policy="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_chat_runtime_policy()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
