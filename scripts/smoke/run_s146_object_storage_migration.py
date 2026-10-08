#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))

from nex_runtime.object_storage import (  # noqa: E402
    ObjectStorageError,
    S3ObjectStore,
    build_s3_client,
    object_storage_settings,
)
from nex_runtime.object_storage_migration import (  # noqa: E402
    ObjectMigrationError,
    ObjectMigrationTarget,
    assess_migration_cutover,
    build_migration_inventory,
    configured_migration_read_mode,
    copy_and_verify_migration,
    migration_items_from_manifest,
)


_OWNER_ROOT_ENV = {
    "nex-cx": "NEX_CX_OBJECT_STORAGE_MIGRATION_ROOT",
    "nex-ae-api": "NEX_AE_OBJECT_STORAGE_MIGRATION_ROOT",
}
_OWNER_INSECURE_ENV = {
    "nex-cx": "NEX_CX_OBJECT_STORAGE_ALLOW_INSECURE",
    "nex-ae-api": "NEX_AE_OBJECT_STORAGE_ALLOW_INSECURE",
}


def run_object_storage_migration(
    *,
    owner: str,
    manifest_path: str | Path,
    environ: Mapping[str, str],
    inventory_only: bool,
    rollback_window_elapsed: bool = False,
    purge_decision_recorded: bool = False,
    target: ObjectMigrationTarget | None = None,
) -> dict[str, Any]:
    if owner not in _OWNER_ROOT_ENV:
        raise ObjectMigrationError(
            "MIGRATION_OWNER_UNSUPPORTED",
            "Migration owner is not supported.",
        )
    source_root = str(environ.get(_OWNER_ROOT_ENV[owner], "")).strip()
    if not source_root:
        raise ObjectMigrationError(
            "MIGRATION_SOURCE_ROOT_REQUIRED",
            "Migration source root is required.",
        )
    manifest = _load_manifest(manifest_path)
    items = migration_items_from_manifest(manifest)
    inventory = build_migration_inventory(source_root, items)
    result: dict[str, Any] = {
        "schema_version": "s146_object_storage_migration.v1",
        "requirement": "S146",
        "slice": "1458",
        "owner": owner,
        "inventory": inventory.evidence(),
        "source_delete_performed": False,
    }
    if inventory_only:
        result.update({"status": "PASS", "phase": "INVENTORY_VERIFIED"})
        return result

    object_target = target or _build_target(owner, environ)
    copied = copy_and_verify_migration(source_root, inventory, object_target)
    read_mode = configured_migration_read_mode(owner, environ)
    decision = assess_migration_cutover(
        inventory,
        copied,
        requested_read_mode=read_mode,
        rollback_window_elapsed=rollback_window_elapsed,
        purge_decision_recorded=purge_decision_recorded,
    )
    result.update(
        {
            "status": "PASS" if decision.admitted else "BLOCKED",
            "phase": "CUTOVER_ADMITTED" if decision.admitted else "COPY_VERIFIED",
            "copy": copied.evidence(),
            "decision": decision.evidence(),
        }
    )
    return result


def _build_target(owner: str, environ: Mapping[str, str]) -> S3ObjectStore:
    allow_insecure = _allow_insecure(owner, environ)
    try:
        settings = object_storage_settings(
            owner,
            environ,
            allow_insecure_endpoint=allow_insecure,
        )
        return S3ObjectStore(build_s3_client(settings), settings)
    except ObjectStorageError as exc:
        raise ObjectMigrationError(
            "MIGRATION_TARGET_CONFIGURATION_INVALID",
            "Migration target configuration is invalid.",
            exc.retryable,
        ) from exc
    except Exception as exc:
        raise ObjectMigrationError(
            "MIGRATION_TARGET_UNAVAILABLE",
            "Migration target client is unavailable.",
            True,
        ) from exc


def _allow_insecure(owner: str, environ: Mapping[str, str]) -> bool:
    raw = str(environ.get(_OWNER_INSECURE_ENV[owner], "false")).strip().lower()
    if raw not in {"true", "false"}:
        raise ObjectMigrationError(
            "MIGRATION_CONFIGURATION_INVALID",
            "Migration object-storage configuration is invalid.",
        )
    if raw == "false":
        return False
    profile = str(environ.get("NEX_RUNTIME_PROFILE", "")).strip().lower()
    if profile not in {"development", "local_mock", "test", "protected_test"}:
        raise ObjectMigrationError(
            "MIGRATION_INSECURE_ENDPOINT_FORBIDDEN",
            "Insecure migration endpoints are forbidden for this profile.",
        )
    return True


def _load_manifest(path: str | Path) -> object:
    candidate = Path(path).expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise ObjectMigrationError(
            "MIGRATION_MANIFEST_UNAVAILABLE",
            "Migration manifest is unavailable.",
        )
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ObjectMigrationError(
            "MIGRATION_MANIFEST_INVALID",
            "Migration manifest is invalid.",
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True, choices=tuple(_OWNER_ROOT_ENV))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--rollback-window-elapsed", action="store_true")
    parser.add_argument("--purge-decision-recorded", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_object_storage_migration(
            owner=args.owner,
            manifest_path=args.manifest,
            environ=os.environ,
            inventory_only=args.inventory_only,
            rollback_window_elapsed=args.rollback_window_elapsed,
            purge_decision_recorded=args.purge_decision_recorded,
        )
    except ObjectMigrationError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "s146_object_storage_migration.v1",
                    "status": "FAIL",
                    "error_code": exc.code,
                    "retryable": exc.retryable,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
