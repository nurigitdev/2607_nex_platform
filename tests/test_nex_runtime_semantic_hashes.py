from __future__ import annotations

import hashlib

import pytest
from nex_runtime.prompts import sha256_text as prompt_sha256_text
from nex_runtime.semantic_hashes import (
    canonical_json,
    hash_ref_from_sha256,
    semantic_sha256_hash_ref,
    sha256_text,
    sha256_from_hash_ref,
    validate_hash_ref,
    validate_sha256_digest,
)


def test_hash_representation_round_trip_never_rehashes_digest() -> None:
    digest = hashlib.sha256(b"P5-S1").hexdigest()
    hash_ref = hash_ref_from_sha256(digest)

    assert hash_ref == f"sha256:{digest}"
    assert sha256_from_hash_ref(hash_ref) == digest
    assert sha256_from_hash_ref(hash_ref) != hashlib.sha256(
        digest.encode("ascii")
    ).hexdigest()


def test_semantic_hash_uses_canonical_json_and_unicode_bytes() -> None:
    first = semantic_sha256_hash_ref({"b": "한글", "a": [2, 1]})
    second = semantic_sha256_hash_ref({"a": [2, 1], "b": "한글"})

    assert first == second
    assert validate_hash_ref(first) == first
    assert validate_sha256_digest(sha256_from_hash_ref(first)) == first[7:]


def test_bare_and_semantic_hashes_share_one_canonical_sha256_primitive() -> None:
    value = {"b": "한글", "a": [2, 1]}
    canonical = canonical_json(value)
    digest = sha256_text(canonical)

    assert canonical == '{"a":[2,1],"b":"한글"}'
    assert semantic_sha256_hash_ref(value) == hash_ref_from_sha256(digest)
    assert prompt_sha256_text is sha256_text


def test_sha256_text_rejects_non_text_input() -> None:
    with pytest.raises(TypeError, match="value must be a string"):
        sha256_text(b"P5")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("validator", "value"),
    [
        (validate_sha256_digest, "A" * 64),
        (validate_sha256_digest, "a" * 63),
        (validate_sha256_digest, None),
        (validate_hash_ref, "a" * 64),
        (validate_hash_ref, "sha256:" + "G" * 64),
        (validate_hash_ref, 1),
    ],
)
def test_hash_validators_reject_ambiguous_or_invalid_representations(
    validator, value
) -> None:
    with pytest.raises(ValueError):
        validator(value)


def test_semantic_hash_rejects_non_json_numbers() -> None:
    with pytest.raises(ValueError):
        semantic_sha256_hash_ref({"bad": float("nan")})
