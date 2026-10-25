from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import TextIO

from nex_eos.outbox_publication import SqlAlchemyEosOutboxPublisher


def build_check() -> dict[str, object]:
    return {
        "schema_version": "p8_demo_eos_runtime_check.v1",
        "status": "PASS",
        "process_id": "nex-eos-outbox-publisher",
        "publisher": SqlAlchemyEosOutboxPublisher.__name__,
        "database_environment": "NEX_EOS_DATABASE_URL",
        "pool_workload": "worker",
        "execution_enabled": False,
        "activation_slice": "P8-DEMO-S05",
    }


def main(argv: Sequence[str] | None = None, *, stdout: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(description="NeX EOS Demo runtime process")
    parser.add_argument("process", choices=("outbox",))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    record = build_check()
    if not args.check:
        record = {
            **record,
            "status": "BLOCKED",
            "failure_code": "p8_demo.eos_runtime.execution_not_activated",
        }
    print(json.dumps(record, sort_keys=True), file=stdout or sys.stdout)
    return 0 if record["status"] == "PASS" else 2


if __name__ == "__main__":  # pragma: no cover - exercised by packaged command
    raise SystemExit(main())
