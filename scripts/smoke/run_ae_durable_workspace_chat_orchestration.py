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
from nex_ae_api.workspace import WorkspaceStateStore  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_service_app,
    issue_mock_user_token,
)


class CountingCxClient:
    def __init__(self) -> None:
        self.call_count = 0

    def create_generation(self, payload, *, request_id, trace_id):
        self.call_count += 1
        return {
            "cx_generation_id": "cx-generation-1018",
            "status": "COMPLETED",
            "alias": payload["alias"],
            "provider_capability": "generation",
            "mo_generation_id": "mo-generation-1018",
            "request_metadata": {"grounding_required": False},
            "response_metadata": {
                "finish_reason": "STOP",
                "output_preview": "Durable answer.",
            },
            "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
        }


class DeterministicRetrievalClient:
    def create_retrieval_context(self, payload, *, request_id, trace_id):
        return {
            "retrieval_package_id": "retrieval-1018",
            "package_hash": "b" * 64,
            "status": "READY",
            "purpose": payload["purpose"],
            "evidence_items": [
                {
                    "evidence_id": "evidence-1018",
                    "citation_label": "[1]",
                    "text": "deterministic private evidence",
                    "quality_flags": [],
                }
            ],
            "score_summary": {"best_score": 0.9, "confidence_bucket": "HIGH"},
            "warnings": [],
            "no_answer_reason": None,
        }


def run_durable_workspace_chat_orchestration_smoke() -> dict[str, Any]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    workspace_store = WorkspaceStateStore()
    workspace_store.create_workspace(
        payload={
            "workspace_id": "11111111-1111-4111-8111-111111111111",
            "chat_document_id": "22222222-2222-4222-8222-222222222222",
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
        },
        request_id="workspace-request-1018",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )
    app.state.ae_workspace_store = workspace_store
    chat_store = ChatInteractionStore()
    cx_client = CountingCxClient()
    register_chat_routes(
        app,
        store=chat_store,
        cx_client=cx_client,
        retrieval_client=DeterministicRetrievalClient(),
    )
    client = TestClient(app)
    payload = {
        "interaction_id": "chat-interaction-1018",
        "workspace_id": "11111111-1111-4111-8111-111111111111",
        "user_message": "Summarize the workspace.",
    }
    owner = _headers("tenant-a", "user-a")
    first = client.post("/api/v1/chat/interactions", json=payload, headers=owner)
    repeated = client.post("/api/v1/chat/interactions", json=payload, headers=owner)
    cross_owner = client.post(
        "/api/v1/chat/interactions",
        json={**payload, "interaction_id": "cross-owner"},
        headers=_headers("tenant-a", "user-b"),
    )
    activities = workspace_store.list_activities(payload["workspace_id"])
    record = first.json()
    activity_types = [item["activity_type"] for item in activities]
    checks = {
        "first_completed": first.status_code == 200
        and record.get("status") == "COMPLETED",
        "workspace_linked": record.get("workspace_id") == payload["workspace_id"],
        "workspace_document_derived": record.get("chat_document_id")
        == "22222222-2222-4222-8222-222222222222",
        "retry_returns_same_record": repeated.json() == record,
        "retry_skips_provider": cx_client.call_count == 1,
        "cross_owner_hidden": cross_owner.status_code == 404,
        "pending_persisted_before_terminal": activity_types[1]
        == "chat.interaction.started",
        "terminal_activity_persisted": activity_types[-1]
        == "chat.interaction.completed",
        "retry_skips_duplicate_activity": len(activities) == 3,
        "activity_metadata_private": "Summarize the workspace." not in str(activities),
        "interaction_restart_readable": chat_store.get_for_owner(
            "chat-interaction-1018",
            tenant_id="tenant-a",
            owner_user_id="user-a",
        )
        == record,
        "raw_token_excluded": "access_token" not in str(record),
    }
    return {
        "smoke_schema_version": "ae_durable_workspace_chat_orchestration_smoke.v1",
        "slice": "1018",
        "requirement": "S102",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "interaction_count": len(chat_store.records),
        "activity_count": len(activities),
        "provider_call_count": cx_client.call_count,
        "postgres_required": False,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    passed = sum(bool(value) for value in result.get("checks", {}).values())
    total = len(result.get("checks", {}))
    return (
        "ae_durable_workspace_chat_orchestration="
        f"{str(result.get('status', 'FAIL')).lower()} checks={passed}/{total} "
        f"interactions={result.get('interaction_count', 0)} "
        f"activities={result.get('activity_count', 0)} "
        f"provider_calls={result.get('provider_call_count', 0)}"
    )


def _headers(tenant_id: str, user_id: str) -> dict[str, str]:
    issued = issue_mock_user_token(tenant_id=tenant_id, user_id=user_id)
    return {"Authorization": f"Bearer {issued.access_token}"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_durable_workspace_chat_orchestration_smoke()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
