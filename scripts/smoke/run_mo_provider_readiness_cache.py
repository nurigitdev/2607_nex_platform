#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_readiness import (  # noqa: E402
    build_mock_provider_readiness_snapshot,
)
from nex_mo.provider_readiness_cache import (  # noqa: E402
    InMemoryProviderReadinessStore,
)


CHECKED_AT = datetime(2026, 9, 30, tzinfo=UTC)


def run_mo_provider_readiness_cache() -> dict[str, Any]:
    store = InMemoryProviderReadinessStore()
    refresh_count = 0

    def refresh() -> Any:
        nonlocal refresh_count
        refresh_count += 1
        checked_at = CHECKED_AT + timedelta(seconds=31 * (refresh_count - 1))
        return build_mock_provider_readiness_snapshot(
            checked_at=checked_at.isoformat().replace("+00:00", "Z")
        )

    initial_lookup = store.read(now=CHECKED_AT)
    initial = store.resolve(refresh, now=CHECKED_AT)
    hit = store.resolve(refresh, now=CHECKED_AT + timedelta(seconds=5))
    refreshed = store.resolve(refresh, now=CHECKED_AT + timedelta(seconds=31))

    def failed_refresh() -> Any:
        raise RuntimeError("private provider failure detail")

    stale = store.resolve(
        failed_refresh,
        now=CHECKED_AT + timedelta(seconds=32),
        force_refresh=True,
    )
    checks = {
        "initial_cache_miss": initial_lookup.status == "MISS",
        "initial_snapshot_fresh": initial.cache_status == "FRESH",
        "fresh_hit_avoids_refresh": hit is initial and refresh_count == 2,
        "expired_snapshot_refreshed": refreshed.cache_status == "REFRESHED",
        "failed_refresh_returns_stale": stale.cache_status == "STALE",
        "stale_snapshot_not_ready": stale.readiness_status == "NOT_READY",
        "failure_detail_omitted": "private" not in json.dumps(stale.to_wire()),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_readiness_cache.v1",
        "slice": "1126",
        "requirement": "S113",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_readiness_cache_failed",
        "checks": checks,
        "summary": {
            "refresh_count": refresh_count,
            "final_cache_status": stale.cache_status,
            "final_readiness_status": stale.readiness_status,
        },
        "issues": [],
        "next_slice": "1127",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_readiness_cache="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"refreshes={summary.get('refresh_count', 0)} "
        f"cache={summary.get('final_cache_status', 'UNKNOWN')} "
        f"readiness={summary.get('final_readiness_status', 'UNKNOWN')} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_readiness_cache()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
