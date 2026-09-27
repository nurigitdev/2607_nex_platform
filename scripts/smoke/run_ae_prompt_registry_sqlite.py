#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-ae-api", ROOT / "services" / "_shared"):
    sys.path.insert(0, str(path))

from nex_ae_api.prompt_persistence import SqlAlchemyAePromptRegistryStore  # noqa: E402
from nex_ae_api.prompts import (  # noqa: E402
    AE_GENERAL_ANSWER_BINDING,
    seed_ae_prompt_registry,
)
from nex_runtime.prompts import render_prompt_from_binding  # noqa: E402


def run_ae_prompt_registry_sqlite() -> dict[str, Any]:
    engine = create_engine("sqlite+pysqlite://", future=True)
    with engine.begin() as connection:
        for statement in _schema_statements():
            connection.execute(text(statement))
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    store = SqlAlchemyAePromptRegistryStore(factory)
    first = seed_ae_prompt_registry(store)
    second = seed_ae_prompt_registry(store)
    rendered = render_prompt_from_binding(
        store,
        binding_key=AE_GENERAL_ANSWER_BINDING,
        variables={},
        request_id="request-1024-smoke",
        trace_id="10240000000000000000000000000001",
        user_prompt="private smoke prompt",
    )
    restarted = SqlAlchemyAePromptRegistryStore(factory)
    loaded = restarted.get_render_event(
        rendered["render_event"]["prompt_render_event_id"]
    )
    checks = {
        "four_bindings_seeded": len(first) == 4,
        "seed_is_idempotent": [item["prompt_binding_id"] for item in first]
        == [item["prompt_binding_id"] for item in second],
        "restart_lists_bindings": len(restarted.list_bindings()) == 4,
        "general_binding_available": (
            restarted.get_binding(AE_GENERAL_ANSWER_BINDING) is not None
        ),
        "render_event_reloaded": loaded == rendered["render_event"],
        "raw_user_prompt_excluded": "private smoke prompt" not in str(loaded),
    }
    return {
        "smoke_schema_version": "ae_prompt_registry_sqlite.v1",
        "slice": "1024",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "binding_count": len(restarted.list_bindings()),
        "render_event_count": 1 if loaded is not None else 0,
        "actual_postgres": False,
        "next_slice": "1025",
    }


def _schema_statements() -> tuple[str, ...]:
    return (
        "CREATE TABLE ae_prompt_templates (prompt_template_id TEXT PRIMARY KEY, service_id TEXT NOT NULL, purpose TEXT NOT NULL, name TEXT NOT NULL, owner_domain TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE (service_id, purpose, name))",
        "CREATE TABLE ae_prompt_template_versions (prompt_template_version_id TEXT PRIMARY KEY, prompt_template_id TEXT NOT NULL, version TEXT NOT NULL, role TEXT NOT NULL, segment_order INTEGER NOT NULL, content TEXT NOT NULL, content_sha256 TEXT NOT NULL, model_capability TEXT NOT NULL, metadata TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE (prompt_template_id, version, role, segment_order))",
        "CREATE TABLE ae_prompt_bindings (prompt_binding_id TEXT PRIMARY KEY, binding_key TEXT NOT NULL UNIQUE, prompt_template_version_id TEXT NOT NULL, service_id TEXT NOT NULL, purpose TEXT NOT NULL, status TEXT NOT NULL, bound_at TEXT NOT NULL)",
        "CREATE TABLE ae_prompt_render_events (prompt_render_event_id TEXT PRIMARY KEY, prompt_binding_id TEXT, prompt_template_version_id TEXT, trace_id TEXT NOT NULL, request_id TEXT NOT NULL, rendered_prompt_hash TEXT NOT NULL, rendered_prompt_preview TEXT, user_prompt_hash TEXT, output_hash TEXT, metadata TEXT NOT NULL, created_at TEXT NOT NULL)",
    )


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks", {})
    return (
        "ae_prompt_registry_sqlite="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"bindings={result.get('binding_count', 0)} "
        f"events={result.get('render_event_count', 0)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_prompt_registry_sqlite()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
