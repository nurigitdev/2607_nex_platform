from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]


def _json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_workspace_chat_positive_and_privacy_contracts() -> None:
    chat_schema = _json(
        "contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json"
    )
    activity_schema = _json(
        "contracts/schemas/service/nex_ae_api/workspace_activity.v1.schema.json"
    )
    Draft202012Validator(chat_schema).validate(
        _json("contracts/examples/generation/ae_chat_interaction.pending.json")
    )
    Draft202012Validator(activity_schema).validate(
        _json("contracts/examples/generation/ae_workspace_activity.chat_started.json")
    )

    with pytest.raises(ValidationError):
        Draft202012Validator(activity_schema).validate(
            _json(
                "contracts/tests/negative/generation/"
                "ae_workspace_activity.raw_prompt_leak.json"
            )
        )


def test_openapi_exposes_canonical_workspace_chat_contracts() -> None:
    spec = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-ae-api.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    schemas = spec["components"]["schemas"]

    assert spec["info"]["version"] == "1.3.0"
    assert schemas["AeWorkspaceState"]["x-nex-canonical-json-schema"].endswith(
        "workspace_state.v1.schema.json"
    )
    assert schemas["AeWorkspaceActivity"]["x-nex-canonical-json-schema"].endswith(
        "workspace_activity.v1.schema.json"
    )
    assert schemas["AeChatInteraction"]["x-nex-canonical-json-schema"].endswith(
        "chat_interaction.v1.schema.json"
    )
    assert spec["paths"]["/api/v1/chat/interactions"]["post"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]["$ref"].endswith(
        "AeChatInteraction"
    )
