from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
import pytest
import yaml

from nex_mo.contract_api_drift_audit import build_mo_contract_api_drift_audit
import run_mo_catalog_lifecycle_contracts as runner


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "contracts/schemas/service/nex_mo"
EXAMPLE_ROOT = ROOT / "contracts/examples/provider"
NEGATIVE_ROOT = ROOT / "contracts/tests/negative/provider"
CONTRACTS = (
    ("model_catalog_entry.v1.schema.json", "mo_model_catalog_entry.active.json", "mo_model_catalog_entry.changed_by.json"),
    ("model_catalog_collection.v1.schema.json", "mo_model_catalog_collection.active.json", "mo_model_catalog_collection.private_field.json"),
    ("model_catalog_registration.v1.schema.json", "mo_model_catalog_registration.generation.json", "mo_model_catalog_registration.endpoint.json"),
    ("model_catalog_transition.v1.schema.json", "mo_model_catalog_transition.activate.json", "mo_model_catalog_transition.draft.json"),
    ("alias_binding.v1.schema.json", "mo_alias_binding.active.json", "mo_alias_binding.changed_by.json"),
    ("alias_binding_collection.v1.schema.json", "mo_alias_binding_collection.active.json", "mo_alias_binding_collection.changed_by.json"),
    ("alias_activation.v1.schema.json", "mo_alias_activation.generation.json", "mo_alias_activation.changed_by.json"),
    ("alias_rollback.v1.schema.json", "mo_alias_rollback.generation.json", "mo_alias_rollback.zero_revision.json"),
)


@pytest.mark.parametrize("schema_name,example_name,negative_name", CONTRACTS)
def test_catalog_lifecycle_contract_examples(
    schema_name: str,
    example_name: str,
    negative_name: str,
) -> None:
    schema = json.loads((SCHEMA_ROOT / schema_name).read_text(encoding="utf-8"))
    example = json.loads((EXAMPLE_ROOT / example_name).read_text(encoding="utf-8"))
    negative = json.loads((NEGATIVE_ROOT / negative_name).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    validator.validate(example)
    with pytest.raises(ValidationError):
        validator.validate(negative)


def test_catalog_lifecycle_openapi_and_runtime_inventory_are_aligned() -> None:
    document = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-mo.openapi.yaml").read_text(encoding="utf-8")
    )
    paths = document["paths"]
    expected = {
        ("/api/v1/model-catalog", "get"),
        ("/api/v1/model-catalog", "post"),
        ("/api/v1/model-catalog/{catalog_id}", "get"),
        ("/api/v1/model-catalog/{catalog_id}/transitions", "post"),
        ("/api/v1/provider-alias-bindings", "get"),
        ("/api/v1/provider-alias-bindings/activate", "post"),
        ("/api/v1/provider-alias-bindings/rollback", "post"),
    }
    for path, method in expected:
        operation = paths[path][method]
        assert operation["security"] == [{"serviceBearer": []}]
        assert "operationId" in operation
        if method == "post":
            assert operation["requestBody"]["required"] is True

    drift = build_mo_contract_api_drift_audit(ROOT)
    assert drift["status"] == "PASS"
    assert drift["summary"]["runtime_operation_count"] == 35
    assert drift["summary"]["openapi_operation_count"] == 35
    assert drift["summary"]["drift_count"] == 0


def test_catalog_lifecycle_contract_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_catalog_lifecycle_contracts()
    assert passing["status"] == "PASS"
    assert "contracts=pass" in runner.summary_line(passing)
    assert "auth=7/7" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_catalog_lifecycle_contracts", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "drift=0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        runner,
        "run_mo_catalog_lifecycle_contracts",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
