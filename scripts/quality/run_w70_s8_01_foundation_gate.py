from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for source_root in (ROOT / "domains/mybee", ROOT / "services/_shared"):
    sys.path.insert(0, str(source_root))

from mybee_ax.integrations.nex_skill_foundation_gate import (
    build_w70_foundation_gate_receipt,
    render_foundation_gate_json,
)

DEFAULT_RECEIPT = Path(
    "reports/quality/mybee-w70-s8-01-foundation-gate.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run or verify the deterministic W70 S8-01 Foundation Gate."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the deterministic receipt instead of checking it.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RECEIPT,
        help="Repository-relative receipt path.",
    )
    args = parser.parse_args()

    output = args.output if args.output.is_absolute() else ROOT / args.output
    expected = render_foundation_gate_json(
        build_w70_foundation_gate_receipt(ROOT)
    )
    if args.write:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(expected)
    elif not output.is_file() or output.read_bytes() != expected:
        print(f"w70_s8_01_foundation_gate=drift receipt={output}")
        return 1

    print(
        "w70_s8_01_foundation_gate=pass "
        f"mode={'write' if args.write else 'check'} receipt={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
