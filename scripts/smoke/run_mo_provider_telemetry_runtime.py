#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_telemetry import InMemoryProviderTelemetryStore  # noqa: E402
from nex_mo.provider_telemetry_runtime import (  # noqa: E402
    build_provider_telemetry_store,
)
from nex_mo.provider_telemetry_store import DurableProviderTelemetryStore  # noqa: E402
import nex_mo.remote_provider as remote_provider  # noqa: E402


def run_mo_provider_telemetry_runtime() -> dict[str, Any]:
    memory_store = build_provider_telemetry_store(
        SimpleNamespace(mode="memory", api_session_factory=None)
    )
    durable_store = build_provider_telemetry_store(
        SimpleNamespace(mode="postgres", api_session_factory=object())
    )
    prior = remote_provider.current_remote_provider_telemetry_store()
    injected = InMemoryProviderTelemetryStore()
    try:
        remote_provider.configure_remote_provider_telemetry_store(injected)
        observed = remote_provider.current_remote_provider_telemetry_store()
        item_count = len(remote_provider.list_remote_provider_telemetry(environ={}))
    finally:
        remote_provider.configure_remote_provider_telemetry_store(prior)
    checks = {
        "memory_mode_preserved": memory_store.__class__.__name__
        == "InMemoryProviderTelemetryStore",
        "postgres_mode_is_durable": isinstance(
            durable_store,
            DurableProviderTelemetryStore,
        ),
        "remote_execution_uses_injected_store": observed is injected,
        "all_capabilities_projected": item_count == 3,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_provider_telemetry_runtime_smoke.v1",
        "slice": "1156",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "runtime_mode_count": 2,
            "capability_count": item_count,
            "durable_store_count": int(isinstance(durable_store, DurableProviderTelemetryStore)),
        },
        "next_slice": "1157" if passed else None,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_telemetry_runtime="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"modes={summary.get('runtime_mode_count', 0)} "
        f"capabilities={summary.get('capability_count', 0)} "
        f"durable_stores={summary.get('durable_store_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_telemetry_runtime()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
