from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "contracts" / "schemas" / "service"
EXAMPLE_ROOT = ROOT / "contracts" / "examples" / "service"
NEGATIVE_ROOT = ROOT / "contracts" / "tests" / "negative" / "service"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("schema_name", "example_name"),
    (
        (
            "nex_ae_api/voucher_attachment_batch.v1.schema.json",
            "ae_voucher_attachment_batch.ready.json",
        ),
        (
            "nex_ae_api/voucher_attachment_manifest.v1.schema.json",
            "ae_voucher_attachment_manifest.locked.json",
        ),
        (
            "nex_ae_api/voucher_attachment_resolution.v1.schema.json",
            "ae_voucher_attachment_resolution.ready.json",
        ),
    ),
)
def test_s75a_positive_contract_examples(schema_name, example_name) -> None:
    schema = _json(SCHEMA_ROOT / schema_name)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        _json(EXAMPLE_ROOT / example_name)
    )


@pytest.mark.parametrize(
    ("schema_name", "example_name"),
    (
        (
            "nex_ae_api/voucher_attachment_batch.v1.schema.json",
            "ae_voucher_attachment_batch.oversized_item.json",
        ),
        (
            "nex_ae_api/voucher_attachment_manifest.v1.schema.json",
            "ae_voucher_attachment_manifest.storage_url.json",
        ),
        (
            "nex_ae_api/voucher_attachment_resolution.v1.schema.json",
            "ae_voucher_attachment_resolution.unauthenticated.json",
        ),
    ),
)
def test_s75a_negative_contract_examples(schema_name, example_name) -> None:
    schema = _json(SCHEMA_ROOT / schema_name)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            _json(NEGATIVE_ROOT / example_name)
        )


def test_s75a_batch_limits_align_with_eos_command() -> None:
    batch = _json(
        SCHEMA_ROOT / "nex_ae_api/voucher_attachment_batch.v1.schema.json"
    )
    eos = _json(
        SCHEMA_ROOT / "nex_eos/create_voucher_draft_command.v1.schema.json"
    )
    assert batch["properties"]["items"]["maxItems"] == 20
    assert eos["properties"]["attachments"]["maxItems"] == 20
    assert batch["properties"]["total_size_bytes"]["maximum"] == 100 * 1024**2
    assert batch["$defs"]["item"]["properties"]["size_bytes"]["maximum"] == (
        25 * 1024**2
    )


def test_s75a_contracts_keep_raw_bytes_and_storage_identity_private() -> None:
    for schema_name in (
        "voucher_attachment_batch.v1.schema.json",
        "voucher_attachment_manifest.v1.schema.json",
        "voucher_attachment_resolution.v1.schema.json",
    ):
        compact = json.dumps(
            _json(SCHEMA_ROOT / "nex_ae_api" / schema_name),
            sort_keys=True,
        ).lower()
        for forbidden in (
            "raw_bytes",
            "content_base64",
            "presigned_url",
            "access_key",
            "secret_key",
            "filesystem_path",
        ):
            assert f'"{forbidden}"' not in compact


def test_s75a_resolution_is_exactly_ae_owned_eos_attachment_evidence() -> None:
    schema = _json(
        SCHEMA_ROOT / "nex_ae_api/voucher_attachment_resolution.v1.schema.json"
    )
    properties = schema["properties"]
    assert properties["storage_owner"] == {"const": "nex-ae-api"}
    assert properties["purpose"] == {"const": "EOS_VOUCHER_ATTACHMENT"}
    assert properties["status"] == {"const": "READY"}
    assert properties["authenticated"] == {"const": True}
    assert properties["immutable"] == {"const": True}
