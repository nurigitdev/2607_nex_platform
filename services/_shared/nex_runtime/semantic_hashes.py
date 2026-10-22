from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

_SHA256_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SHA256_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_NSL_WRITE_PAYLOAD_DOMAIN = b"NSL-WRITE-PAYLOAD-V1\0"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_sha256_digest(value: object) -> str:
    if not isinstance(value, str) or _SHA256_DIGEST.fullmatch(value) is None:
        raise ValueError("value must be a lowercase bare SHA-256 digest")
    return value


def validate_hash_ref(value: object) -> str:
    if not isinstance(value, str) or _SHA256_HASH_REF.fullmatch(value) is None:
        raise ValueError("value must be a lowercase sha256:<digest> hash reference")
    return value


def hash_ref_from_sha256(digest: object) -> str:
    return f"sha256:{validate_sha256_digest(digest)}"


def sha256_from_hash_ref(hash_ref: object) -> str:
    return validate_hash_ref(hash_ref)[len("sha256:") :]


def semantic_sha256_hash_ref(value: Any) -> str:
    return hash_ref_from_sha256(sha256_text(canonical_json(value)))


def nsl_write_payload_hash_ref(canonical_arguments: Mapping[str, Any]) -> str:
    """Hash canonical WRITE values with the frozen NSL v0.2 domain."""

    if not isinstance(canonical_arguments, Mapping):
        raise TypeError("canonical_arguments must be a mapping")
    projected = _nsl_write_json_value(canonical_arguments, path="$")
    canonical = canonical_json(projected).encode("utf-8")
    return hash_ref_from_sha256(
        hashlib.sha256(_NSL_WRITE_PAYLOAD_DOMAIN + canonical).hexdigest()
    )


def _nsl_write_json_value(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return value
    if isinstance(value, Mapping):
        projected: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"NSL WRITE object keys must be strings at {path}")
            projected[key] = _nsl_write_json_value(item, path=f"{path}.{key}")
        return projected
    if isinstance(value, (list, tuple)):
        return [
            _nsl_write_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise TypeError(
        f"unsupported canonical NSL WRITE value at {path}: {type(value).__name__}"
    )
