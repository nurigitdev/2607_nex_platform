from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import TextIO

from nex_wc.approvals import SqlAlchemyApprovalWorkItemRepository
from nex_wc.handoff_delivery import run_handoff_delivery_worker_once
from nex_wc.work_result_delivery import run_work_result_delivery_job


def build_check() -> dict[str, object]:
    return {
        "schema_version": "p8_demo_wc_runtime_check.v1",
        "status": "PASS",
        "process_id": "nex-wc-event-delivery-worker",
        "database_environment": "NEX_WC_DATABASE_URL",
        "pool_workload": "worker",
        "adapters": {
            "claim_handoff": run_handoff_delivery_worker_once.__name__,
            "work_result": run_work_result_delivery_job.__name__,
            "approval_outbox": SqlAlchemyApprovalWorkItemRepository.__name__,
        },
        "execution_enabled": False,
        "activation_slice": "P8-DEMO-S05",
    }


def main(argv: Sequence[str] | None = None, *, stdout: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(description="NeX WC Demo runtime process")
    parser.add_argument("process", choices=("events",))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    record = build_check()
    if not args.check:
        record = {
            **record,
            "status": "BLOCKED",
            "failure_code": "p8_demo.wc_runtime.execution_not_activated",
        }
    print(json.dumps(record, sort_keys=True), file=stdout or sys.stdout)
    return 0 if record["status"] == "PASS" else 2


if __name__ == "__main__":  # pragma: no cover - exercised by packaged command
    raise SystemExit(main())
