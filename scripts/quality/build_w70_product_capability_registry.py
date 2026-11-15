from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for source_root in (
    ROOT / "domains/mybee",
    ROOT / "services/_shared",
    ROOT / "services/nex-ae-api",
):
    sys.path.insert(0, str(source_root))

from mybee_ax.integrations.nex_skill_pack_release import (
    build_w70_registry_release_artifacts,
    render_release_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify the immutable W70 candidate registry release."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write generated lock and registry artifacts instead of checking them.",
    )
    args = parser.parse_args()
    artifacts = build_w70_registry_release_artifacts(ROOT)
    drift: list[str] = []
    for relative, value in artifacts.items():
        expected = render_release_json(value)
        path = ROOT / relative
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected)
        elif not path.is_file() or path.read_bytes() != expected:
            drift.append(relative.as_posix())
    if drift:
        print("w70_registry_release=drift files=" + ",".join(drift))
        return 1
    print(
        "w70_registry_release=pass "
        f"mode={'write' if args.write else 'check'} artifacts={len(artifacts)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
