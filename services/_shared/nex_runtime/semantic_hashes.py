from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_SHA256_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SHA256_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")


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
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return hash_ref_from_sha256(digest)
