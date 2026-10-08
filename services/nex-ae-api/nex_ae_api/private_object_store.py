from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from nex_runtime.object_storage import (
    ObjectStorageError,
    S3ObjectStore,
    build_s3_client,
    object_storage_settings,
)


AE_PRIVATE_STORAGE_MODE_ENV = "NEX_AE_PRIVATE_STORAGE_MODE"
AE_PRIVATE_STORAGE_MODES = frozenset({"FILESYSTEM", "S3"})


@dataclass(frozen=True)
class AePrivateObjectStorageError(RuntimeError):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def ae_private_storage_mode(environ: Mapping[str, str]) -> str | None:
    raw = environ.get(AE_PRIVATE_STORAGE_MODE_ENV)
    if raw is None or not str(raw).strip():
        return None
    mode = str(raw).strip().upper()
    if mode not in AE_PRIVATE_STORAGE_MODES:
        raise AePrivateObjectStorageError(
            "ae.private_storage_mode_invalid",
            "AE private storage mode must be FILESYSTEM or S3.",
        )
    return mode


def build_ae_private_object_store(
    environ: Mapping[str, str] | None = None,
) -> S3ObjectStore:
    env = os.environ if environ is None else environ
    if ae_private_storage_mode(env) != "S3":
        raise AePrivateObjectStorageError(
            "ae.private_object_storage_not_selected",
            "AE S3-compatible private object storage is not selected.",
        )
    try:
        settings = object_storage_settings(
            "nex-ae-api",
            env,
            allow_insecure_endpoint=_allow_insecure(env),
        )
        return S3ObjectStore(build_s3_client(settings), settings)
    except ObjectStorageError as exc:
        raise AePrivateObjectStorageError(
            "ae.private_object_storage_configuration_invalid",
            "AE private object-storage configuration is invalid.",
            exc.retryable,
        ) from exc


def _allow_insecure(environ: Mapping[str, str]) -> bool:
    raw = str(
        environ.get("NEX_AE_OBJECT_STORAGE_ALLOW_INSECURE", "false")
    ).strip().lower()
    if raw not in {"true", "false"}:
        raise AePrivateObjectStorageError(
            "ae.private_object_storage_configuration_invalid",
            "AE object-storage insecure endpoint flag is invalid.",
        )
    if raw == "false":
        return False
    profile = str(environ.get("NEX_RUNTIME_PROFILE", "")).strip().lower()
    if profile not in {"development", "local_mock", "test", "protected_test"}:
        raise AePrivateObjectStorageError(
            "ae.private_object_storage_insecure_forbidden",
            "Insecure AE object-storage endpoints are forbidden for this profile.",
        )
    return True
