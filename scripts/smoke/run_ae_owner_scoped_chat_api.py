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


class DeterministicCxClient:
    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return {
            "cx_generation_id": "cx-generation-1017",
            "status": "COMPLETED",
            "alias": payload["alias"],
            "provider_capability": "generation",
            "mo_generation_id": "mo-generation-1017",
            "request_metadata": {"grounding_required": False},
            "response_metadata": {
                "finish_reason": "STOP",
                "output_preview": "Deterministic answer.",
            },
            "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
        }


class DeterministicRetrievalClient:
    def create_retrieval_context(self, payload, *, request_id, trace_id):
        return {
            "retrieval_package_id": "retrieval-1017",
            "package_hash": "b" * 64,
            "status": "READY",
            "purpose": payload["purpose"],
            "evidence_items": [
                {
                    "evidence_id": "evidence-1017",
                    "citation_label": "[1]",
                    "text": "deterministic private evidence",
                    "quality_flags": [],
                }
            ],
            "score_summary": {"best_score": 0.9, "confidence_bucket": "HIGH"},
            "warnings": [],
            "no_answer_reason": None,
        }


def run_owner_scoped_chat_api_smoke() -> dict[str, Any]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = ChatInteractionStore()
    register_chat_routes(
        app,
        store=store,
        cx_client=DeterministicCxClient(),
        retrieval_client=DeterministicRetrievalClient(),
    )
    workspace_store = WorkspaceStateStore()
    workspace_store.create_workspace(
        payload={
            "workspace_id": "11111111-1111-4111-8111-111111111111",
            "chat_document_id": "22222222-2222-4222-8222-222222222222",
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
        },
        request_id="workspace-request-1017",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )
    app.state.ae_workspace_store = workspace_store
    client = TestClient(app)
    owner = _headers("tenant-a", "user-a")
    other = _headers("tenant-a", "user-b")
    created = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": "chat-interaction-1017",
            "workspace_id": "11111111-1111-4111-8111-111111111111",
            "chat_document_id": "22222222-2222-4222-8222-222222222222",
            "user_message": "Summarize the workspace.",
        },
        headers=owner,
    )
    record = created.json()
    interaction_id = record.get("interaction_id", "missing")
    owner_read = client.get(f"/api/v1/chat/interactions/{interaction_id}", headers=owner)
    cross_owner_read = client.get(
        f"/api/v1/chat/interactions/{interaction_id}",
        headers=other,
    )
    cross_owner_links = client.get(
        f"/api/v1/chat/interactions/{interaction_id}/artifact-links",
        headers=other,
    )
    mismatch = client.post(
        "/api/v1/chat/interactions",
        json={"user_message": "Mismatch", "user_id": "user-b"},
        headers=owner,
    )
    checks = {
        "create_accepted": created.status_code == 200,
        "claim_owner_applied": record.get("tenant_id") == "tenant-a"
        and record.get("owner_user_id") == "user-a",
        "workspace_link_retained": record.get("workspace_id")
        == "11111111-1111-4111-8111-111111111111",
        "owner_read_accepted": owner_read.status_code == 200,
        "cross_owner_read_hidden": cross_owner_read.status_code == 404,
        "cross_owner_links_hidden": cross_owner_links.status_code == 404,
        "payload_mismatch_rejected": mismatch.status_code == 403,
        "repository_owner_filter": store.get_for_owner(
            interaction_id,
            tenant_id="tenant-a",
            owner_user_id="user-b",
        )
        is None,
        "app_store_exposed": app.state.ae_chat_store is store,
        "raw_token_excluded": "access_token" not in str(record),
    }
    return {
        "smoke_schema_version": "ae_owner_scoped_chat_api_smoke.v1",
        "slice": "1017",
        "requirement": "S102",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "interaction_count": len(store.records),
        "private_content_included": False,
        "postgres_required": False,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    passed = sum(bool(value) for value in result.get("checks", {}).values())
    total = len(result.get("checks", {}))
    return (
        "ae_owner_scoped_chat_api="
        f"{str(result.get('status', 'FAIL')).lower()} checks={passed}/{total} "
        f"interactions={result.get('interaction_count', 0)}"
    )


def _headers(tenant_id: str, user_id: str) -> dict[str, str]:
    issued = issue_mock_user_token(tenant_id=tenant_id, user_id=user_id)
    return {"Authorization": f"Bearer {issued.access_token}"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_owner_scoped_chat_api_smoke()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
