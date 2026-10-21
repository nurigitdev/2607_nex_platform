from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
REQUEST_SCHEMA = CONTRACTS / "schemas/service/nex_eos/create_voucher_draft_command.v1.schema.json"
RESULT_SCHEMA = CONTRACTS / "schemas/service/nex_eos/create_voucher_draft_result.v1.schema.json"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_positive_command_and_result_examples_validate():
    for schema_path, example_path in (
        (REQUEST_SCHEMA, CONTRACTS / "examples/service/eos_create_voucher_draft_command.golden_a.json"),
        (RESULT_SCHEMA, CONTRACTS / "examples/service/eos_create_voucher_draft_result.committed.json"),
    ):
        schema = _json(schema_path)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            _json(example_path)
        )


@pytest.mark.parametrize(
    "schema_path,payload_path",
    (
        (REQUEST_SCHEMA, CONTRACTS / "tests/negative/service/eos_create_voucher_draft_command.float_amount.json"),
        (REQUEST_SCHEMA, CONTRACTS / "tests/negative/service/eos_create_voucher_draft_command.missing_approval.json"),
        (RESULT_SCHEMA, CONTRACTS / "tests/negative/service/eos_create_voucher_draft_result.committed_without_voucher.json"),
    ),
)
def test_negative_contract_examples_are_rejected(schema_path, payload_path):
    with pytest.raises(ValidationError):
        Draft202012Validator(
            _json(schema_path), format_checker=FormatChecker()
        ).validate(_json(payload_path))


def test_contract_indexes_and_openapi_bind_canonical_schemas():
    examples = _json(CONTRACTS / "examples/index.json")["examples"]
    negatives = _json(CONTRACTS / "tests/negative/index.json")["negative_examples"]
    example_names = {item["name"] for item in examples}
    negative_names = {item["name"] for item in negatives}
    assert {
        "eos_create_voucher_draft_command_golden_a",
        "eos_create_voucher_draft_result_committed",
    } <= example_names
    assert {
        "eos_create_voucher_draft_command_float_amount",
        "eos_create_voucher_draft_command_missing_approval",
        "eos_create_voucher_draft_result_committed_without_voucher",
    } <= negative_names

    spec = yaml.safe_load((CONTRACTS / "openapi/nex-eos.openapi.yaml").read_text())
    operation = spec["paths"]["/internal/v1/finance/voucher-drafts"]["post"]
    assert operation["x-nex-business-scope"] == "finance:voucher-draft:create"
    assert operation["responses"]["201"]
    assert spec["components"]["schemas"]["CreateVoucherDraftCommand"][
        "x-nex-canonical-json-schema"
    ].endswith("create_voucher_draft_command.v1.schema.json")


def test_contract_rejects_zero_amount_wrong_refs_and_secret_attachment_fields():
    validator = Draft202012Validator(
        _json(REQUEST_SCHEMA), format_checker=FormatChecker()
    )
    payload = _json(
        CONTRACTS / "examples/service/eos_create_voucher_draft_command.golden_a.json"
    )
    for mutate in (
        lambda value: value["lines"][0].update(signed_amount="0.00"),
        lambda value: value["project_ref"].update(type="external.project"),
        lambda value: value["lines"][0]["account_ref"].update(type="external.account"),
        lambda value: value.update(attachments=[{
            "attachment_id": "85000000-0000-4000-8000-000000000001",
            "object_ref": "objref:ownerissuedopaque0001",
            "display_name": "receipt.pdf",
            "media_type": "application/pdf",
            "size_bytes": 1,
            "content_sha256": "b" * 64,
            "presigned_url": "https://private.example/object"
        }]),
    ):
        candidate = json.loads(json.dumps(payload))
        mutate(candidate)
        with pytest.raises(ValidationError):
            validator.validate(candidate)
