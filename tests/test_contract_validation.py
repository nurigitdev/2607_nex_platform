from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import validate_contracts


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def minimal_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }


def minimal_openapi() -> dict[str, object]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "0.0.0"},
        "paths": {},
    }


def build_contract_fixture(root: Path) -> None:
    write_json(root / "schemas" / "common" / "sample.v1.schema.json", minimal_schema())
    write_json(root / "examples" / "sample.json", {"name": "valid"})
    write_json(
        root / "examples" / "index.json",
        {
            "examples": [
                {
                    "name": "sample",
                    "path": "examples/sample.json",
                    "schema": "schemas/common/sample.v1.schema.json",
                }
            ]
        },
    )
    write_json(root / "tests" / "negative" / "sample.invalid.json", {})
    write_json(
        root / "tests" / "negative" / "index.json",
        {
            "negative_examples": [
                {
                    "name": "sample_invalid",
                    "path": "tests/negative/sample.invalid.json",
                    "schema": "schemas/common/sample.v1.schema.json",
                }
            ]
        },
    )
    write_yaml(root / "openapi" / "sample.openapi.yaml", minimal_openapi())


def test_validate_contract_tree_accepts_valid_contract_package(tmp_path: Path) -> None:
    build_contract_fixture(tmp_path)

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert summary.ok
    assert summary.schema_count == 1
    assert summary.example_count == 1
    assert summary.negative_example_count == 1
    assert summary.openapi_count == 1


def test_validate_contract_tree_reports_invalid_example(tmp_path: Path) -> None:
    build_contract_fixture(tmp_path)
    write_json(tmp_path / "examples" / "sample.json", {"unexpected": "value"})

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert summary.example_count == 0
    assert "examples/sample.json" in summary.failures[0]


def test_validate_contract_tree_reports_bad_example_index(tmp_path: Path) -> None:
    build_contract_fixture(tmp_path)
    write_json(tmp_path / "examples" / "index.json", {"examples": "not-a-list"})

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "examples/index.json" in summary.failures[0]


def test_validate_contract_tree_reports_missing_index_keys(tmp_path: Path) -> None:
    build_contract_fixture(tmp_path)
    write_json(tmp_path / "examples" / "index.json", {"examples": [{"path": "x"}]})

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "missing key" in summary.failures[0]


def test_validate_contract_tree_reports_invalid_openapi(tmp_path: Path) -> None:
    build_contract_fixture(tmp_path)
    write_yaml(tmp_path / "openapi" / "sample.openapi.yaml", {"openapi": "3.1.0"})

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "invalid OpenAPI spec" in summary.failures[0]


def test_validate_contract_tree_reports_negative_fixture_that_validates(
    tmp_path: Path,
) -> None:
    build_contract_fixture(tmp_path)
    write_json(tmp_path / "tests" / "negative" / "sample.invalid.json", {"name": "valid"})

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "negative example validated" in summary.failures[0]


def test_validate_contract_tree_reports_bad_negative_index(tmp_path: Path) -> None:
    build_contract_fixture(tmp_path)
    write_json(
        tmp_path / "tests" / "negative" / "index.json",
        {"negative_examples": "not-a-list"},
    )

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "tests/negative/index.json" in summary.failures[0]


def test_validate_contract_tree_reports_missing_negative_index_keys(
    tmp_path: Path,
) -> None:
    build_contract_fixture(tmp_path)
    write_json(
        tmp_path / "tests" / "negative" / "index.json",
        {"negative_examples": [{"path": "x"}]},
    )

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "missing key" in summary.failures[0]


def test_validate_contract_tree_reports_unreadable_negative_fixture(
    tmp_path: Path,
) -> None:
    build_contract_fixture(tmp_path)
    write_json(
        tmp_path / "tests" / "negative" / "index.json",
        {
            "negative_examples": [
                {
                    "name": "missing",
                    "path": "tests/negative/missing.json",
                    "schema": "schemas/common/sample.v1.schema.json",
                }
            ]
        },
    )

    summary = validate_contracts.validate_contract_tree(tmp_path)

    assert not summary.ok
    assert "tests/negative/missing.json" in summary.failures[0]


def test_iter_openapi_files_handles_missing_directory(tmp_path: Path) -> None:
    assert validate_contracts.iter_openapi_files(tmp_path) == []


def test_load_structured_file_rejects_unsupported_suffix(tmp_path: Path) -> None:
    unsupported = tmp_path / "payload.txt"
    unsupported.write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError):
        validate_contracts.load_structured_file(unsupported)


def test_main_returns_success_for_valid_package(tmp_path: Path, capsys) -> None:
    build_contract_fixture(tmp_path)

    assert validate_contracts.main([str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "contract_validation=pass" in output
    assert "negative_examples=1" in output


def test_main_returns_failure_for_invalid_package(tmp_path: Path, capsys) -> None:
    build_contract_fixture(tmp_path)
    write_json(tmp_path / "examples" / "sample.json", {"unexpected": "value"})

    assert validate_contracts.main([str(tmp_path)]) == 1
    assert "contract validation failure" in capsys.readouterr().out
