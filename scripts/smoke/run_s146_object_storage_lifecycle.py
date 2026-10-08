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
from nex_runtime.object_storage_lifecycle import (  # noqa: E402
    ObjectLifecycleError,
    PrivateBucketLifecyclePolicy,
    bootstrap_private_bucket,
)


_OWNERS = ("nex-cx", "nex-ae-api")


def run_object_storage_lifecycle(
    *,
    owner: str,
    environ: Mapping[str, str],
    client: Any | None = None,
    retention_days: int = 30,
    multipart_abort_days: int = 7,
) -> dict[str, Any]:
    if owner not in _OWNERS:
        raise ObjectLifecycleError(
            "BUCKET_OWNER_UNSUPPORTED",
            "Private bucket owner is not supported.",
        )
    settings = _bootstrap_settings(owner, environ)
    try:
        lifecycle_client = client or build_s3_client(settings)
        receipt = bootstrap_private_bucket(
            lifecycle_client,
            bucket=settings.bucket,
            policy=PrivateBucketLifecyclePolicy(
                noncurrent_retention_days=retention_days,
                multipart_abort_days=multipart_abort_days,
            ),
        )
        S3ObjectStore(lifecycle_client, settings).check_ready()
    except ObjectLifecycleError:
        raise
    except ObjectStorageError as exc:
        raise ObjectLifecycleError(
            "BUCKET_READINESS_FAILED",
            "Private bucket readiness check failed.",
            exc.retryable,
        ) from exc
    except Exception as exc:
        raise ObjectLifecycleError(
            "BUCKET_CLIENT_UNAVAILABLE",
            "Private bucket client is unavailable.",
            True,
        ) from exc
    return {
        "schema_version": "s146_object_storage_lifecycle.v1",
        "requirement": "S146",
        "slice": "1459",
        "status": "PASS",
        "owner": owner,
        "bucket": receipt.evidence(),
        "credentials_disclosed": False,
        "endpoint_disclosed": False,
    }


def _bootstrap_settings(owner: str, environ: Mapping[str, str]):
    endpoint = str(environ.get("NEX_OBJECT_STORAGE_BOOTSTRAP_ENDPOINT", "")).strip()
    access_key = str(environ.get("NEX_OBJECT_STORAGE_BOOTSTRAP_ACCESS_KEY", "")).strip()
    secret_key = str(environ.get("NEX_OBJECT_STORAGE_BOOTSTRAP_SECRET_KEY", "")).strip()
    ca_bundle = str(environ.get("NEX_OBJECT_STORAGE_BOOTSTRAP_CA_BUNDLE", "")).strip()
    region = str(environ.get("NEX_OBJECT_STORAGE_BOOTSTRAP_REGION", "us-east-1")).strip()
    insecure = _allow_insecure(environ)
    prefix = "NEX_CX" if owner == "nex-cx" else "NEX_AE"
    scoped = {
        f"{prefix}_OBJECT_STORAGE_BACKEND": "S3",
        f"{prefix}_OBJECT_STORAGE_ENDPOINT": endpoint,
        f"{prefix}_OBJECT_STORAGE_ACCESS_KEY": access_key,
        f"{prefix}_OBJECT_STORAGE_SECRET_KEY": secret_key,
        f"{prefix}_OBJECT_STORAGE_REGION": region,
    }
    bucket = str(environ.get(f"{prefix}_OBJECT_STORAGE_BUCKET", "")).strip()
    if bucket:
        scoped[f"{prefix}_OBJECT_STORAGE_BUCKET"] = bucket
    if ca_bundle:
        scoped[f"{prefix}_OBJECT_STORAGE_CA_BUNDLE"] = ca_bundle
    try:
        return object_storage_settings(
            owner,
            scoped,
            allow_insecure_endpoint=insecure,
        )
    except ObjectStorageError as exc:
        raise ObjectLifecycleError(
            "BUCKET_BOOTSTRAP_CONFIGURATION_INVALID",
            "Private bucket bootstrap configuration is invalid.",
            exc.retryable,
        ) from exc


def _allow_insecure(environ: Mapping[str, str]) -> bool:
    raw = str(
        environ.get("NEX_OBJECT_STORAGE_BOOTSTRAP_ALLOW_INSECURE", "false")
    ).strip().lower()
    if raw not in {"true", "false"}:
        raise ObjectLifecycleError(
            "BUCKET_BOOTSTRAP_CONFIGURATION_INVALID",
            "Private bucket bootstrap configuration is invalid.",
        )
    if raw == "false":
        return False
    profile = str(environ.get("NEX_RUNTIME_PROFILE", "")).strip().lower()
    if profile not in {"development", "local_mock", "test", "protected_test"}:
        raise ObjectLifecycleError(
            "BUCKET_BOOTSTRAP_INSECURE_FORBIDDEN",
            "Insecure bucket bootstrap endpoints are forbidden for this profile.",
        )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True, choices=_OWNERS)
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--multipart-abort-days", type=int, default=7)
    args = parser.parse_args(argv)
    try:
        result = run_object_storage_lifecycle(
            owner=args.owner,
            environ=os.environ,
            retention_days=args.retention_days,
            multipart_abort_days=args.multipart_abort_days,
        )
    except ObjectLifecycleError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "s146_object_storage_lifecycle.v1",
                    "status": "FAIL",
                    "error_code": exc.code,
                    "retryable": exc.retryable,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
