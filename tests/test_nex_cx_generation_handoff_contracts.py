from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT / "contracts/schemas/generation/cx_generation_handoff.v1.schema.json"
)
POSITIVE_PATHS = (
    ROOT / "contracts/examples/generation/cx_generation_handoff.pending.json",
    ROOT / "contracts/examples/generation/cx_generation_handoff.blocked.json",
    ROOT / "contracts/examples/generation/cx_generation_handoff.ready.json",
)
NEGATIVE_PATHS = (
    ROOT
    / "contracts/tests/negative/generation/cx_generation_handoff.raw_storage_leak.json",
    ROOT
    / "contracts/tests/negative/generation/cx_generation_handoff.owner_scope_disabled.json",
)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_generation_handoff_positive_examples_are_canonical() -> None:
    validator = Draft202012Validator(_json(SCHEMA_PATH))

    values = [_json(path) for path in POSITIVE_PATHS]

    for value in values:
        validator.validate(value)
    assert [value["handoff_status"] for value in values] == [
        "PENDING",
        "BLOCKED",
        "READY",
    ]
    assert values[0]["generation"] is values[0]["content"] is None
    assert values[1]["generation"] is values[1]["content"] is None
    assert values[2]["content"]["owner_scope_enforced"] is True


@pytest.mark.parametrize("path", NEGATIVE_PATHS)
def test_generation_handoff_negative_examples_are_rejected(path: Path) -> None:
    validator = Draft202012Validator(_json(SCHEMA_PATH))

    with pytest.raises(ValidationError):
        validator.validate(_json(path))


def test_generation_handoff_status_relationship_is_fail_closed() -> None:
    validator = Draft202012Validator(_json(SCHEMA_PATH))
    pending = _json(POSITIVE_PATHS[0])
    pending["job"]["status"] = "SUCCEEDED"

    with pytest.raises(ValidationError):
        validator.validate(pending)


def test_generation_handoff_openapi_component_is_canonical() -> None:
    openapi = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-cx.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    operation = openapi["paths"]["/api/v1/generation-jobs/{job_id}/handoff"][
        "get"
    ]

    assert openapi["info"]["version"] == "1.0.0"
    assert operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/CxGenerationHandoff"}
    component = openapi["components"]["schemas"]["CxGenerationHandoff"]
    assert component["additionalProperties"] is False
    assert component["properties"]["owner_scope_enforced"] == {"const": True}


def test_generation_handoff_contract_indexes_are_complete() -> None:
    examples = _json(ROOT / "contracts/examples/index.json")["examples"]
    negatives = _json(ROOT / "contracts/tests/negative/index.json")[
        "negative_examples"
    ]
    schema_ref = "schemas/generation/cx_generation_handoff.v1.schema.json"

    assert sum(item.get("schema") == schema_ref for item in examples) == 3
    assert sum(item.get("schema") == schema_ref for item in negatives) == 2
