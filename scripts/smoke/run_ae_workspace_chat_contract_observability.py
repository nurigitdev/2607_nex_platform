#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "quality",
):
    sys.path.insert(0, str(path))

from nex_ae_api.workspace_chat_observability import (  # noqa: E402
    observe_workspace_chat_state,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
)
from validate_contracts import validate_contract_tree  # noqa: E402


def run_workspace_chat_contract_observability_smoke() -> dict[str, Any]:
    contract_summary = validate_contract_tree(ROOT / "contracts")
    openapi = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-ae-api.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ae-api", store=event_store)
    base_record = {
        "interaction_id": "interaction-1019",
        "workspace_id": "workspace-1019",
        "status": "PENDING",
        "cx_status": "PENDING",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "request-1019",
        "retrieval": None,
        "artifact_refs": [],
    }
    pending = observe_workspace_chat_state(emitter, base_record)
    completed = observe_workspace_chat_state(
        emitter,
        {
            **base_record,
            "status": "COMPLETED",
            "cx_status": "COMPLETED",
            "retrieval": {"cx_retrieval_package_id": "not-emitted"},
        },
    )
    events = event_store.list_events(service_id="nex-ae-api", limit=10)
    serialized_events = json.dumps(events, sort_keys=True)
    schemas = openapi.get("components", {}).get("schemas", {})
    checks = {
        "contract_tree_valid": contract_summary.ok,
        "workspace_activity_schema_registered": any(
            entry.get("schema", "").endswith("workspace_activity.v1.schema.json")
            for entry in json.loads(
                (ROOT / "contracts/examples/index.json").read_text(encoding="utf-8")
            )["examples"]
        ),
        "pending_chat_fixture_registered": any(
            entry.get("path", "").endswith("ae_chat_interaction.pending.json")
            for entry in json.loads(
                (ROOT / "contracts/examples/index.json").read_text(encoding="utf-8")
            )["examples"]
        ),
        "openapi_promoted": str(openapi.get("info", {}).get("version", "")).startswith(
            "1."
        ),
        "workspace_openapi_schema_present": "AeWorkspaceState" in schemas,
        "activity_openapi_schema_present": "AeWorkspaceActivity" in schemas,
        "chat_openapi_schema_present": "AeChatInteraction" in schemas,
        "pending_event_emitted": pending.ok,
        "completed_event_emitted": completed.ok,
        "state_events_persisted": len(events) == 2,
        "raw_content_absent": "not-emitted" not in serialized_events
        and "user_message" not in serialized_events,
        "privacy_flags_closed": all(
            event["details"]["prompt_content_included"] is False
            and event["details"]["response_content_included"] is False
            and event["details"]["owner_identity_included"] is False
            and event["details"]["provider_detail_included"] is False
            for event in events
        ),
    }
    return {
        "smoke_schema_version": "ae_workspace_chat_contract_observability_smoke.v1",
        "slice": "1019",
        "requirement": "S102",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "contract_counts": {
            "schemas": contract_summary.schema_count,
            "examples": contract_summary.example_count,
            "negative_examples": contract_summary.negative_example_count,
            "openapi": contract_summary.openapi_count,
        },
        "event_count": len(events),
        "postgres_required": False,
        "remote_provider_required": False,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    passed = sum(bool(value) for value in result.get("checks", {}).values())
    total = len(result.get("checks", {}))
    counts = result.get("contract_counts", {})
    return (
        "ae_workspace_chat_contract_observability="
        f"{str(result.get('status', 'FAIL')).lower()} checks={passed}/{total} "
        f"schemas={counts.get('schemas', 0)} examples={counts.get('examples', 0)} "
        f"negative={counts.get('negative_examples', 0)} "
        f"events={result.get('event_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_workspace_chat_contract_observability_smoke()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
