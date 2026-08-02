from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

SUPPORTED_OPENAPI_SUFFIXES = {".json", ".yaml", ".yml"}


@dataclass
class ContractValidationSummary:
    schema_count: int = 0
    example_count: int = 0
    openapi_count: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def load_structured_file(path: Path) -> Any:
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))

    if path.suffix in {".yaml", ".yml"}:
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    raise ValueError(f"unsupported file type: {path}")


def iter_schema_files(root: Path) -> list[Path]:
    return sorted((root / "schemas").glob("**/*.schema.json"))


def iter_openapi_files(root: Path) -> list[Path]:
    openapi_root = root / "openapi"
    if not openapi_root.exists():
        return []

    return sorted(
        path
        for path in openapi_root.iterdir()
        if path.is_file() and path.suffix in SUPPORTED_OPENAPI_SUFFIXES
    )


def load_example_index(root: Path) -> list[dict[str, str]]:
    index_path = root / "examples" / "index.json"
    if not index_path.exists():
        return []

    payload = load_structured_file(index_path)
    examples = payload.get("examples", [])
    if not isinstance(examples, list):
        raise ValueError("examples/index.json must contain an examples list")

    return examples


def validate_json_schemas(root: Path, summary: ContractValidationSummary) -> None:
    for schema_path in iter_schema_files(root):
        try:
            Draft202012Validator.check_schema(load_structured_file(schema_path))
        except Exception as exc:  # pragma: no cover - exact validator errors vary.
            summary.failures.append(f"{schema_path}: invalid JSON Schema: {exc}")
        else:
            summary.schema_count += 1


def validate_examples(root: Path, summary: ContractValidationSummary) -> None:
    try:
        examples = load_example_index(root)
    except Exception as exc:
        summary.failures.append(f"{root / 'examples' / 'index.json'}: {exc}")
        return

    for entry in examples:
        try:
            example_path = root / entry["path"]
            schema_path = root / entry["schema"]
            schema = load_structured_file(schema_path)
            payload = load_structured_file(example_path)
            Draft202012Validator(schema).validate(payload)
        except KeyError as exc:
            summary.failures.append(f"examples/index.json: missing key {exc}")
        except Exception as exc:
            summary.failures.append(f"{entry.get('path', '<unknown>')}: {exc}")
        else:
            summary.example_count += 1


def validate_openapi_specs(root: Path, summary: ContractValidationSummary) -> None:
    for spec_path in iter_openapi_files(root):
        try:
            validate(load_structured_file(spec_path))
        except Exception as exc:
            summary.failures.append(f"{spec_path}: invalid OpenAPI spec: {exc}")
        else:
            summary.openapi_count += 1


def validate_contract_tree(root: Path) -> ContractValidationSummary:
    summary = ContractValidationSummary()
    validate_json_schemas(root, summary)
    validate_examples(root, summary)
    validate_openapi_specs(root, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate NeX contract JSON Schemas, examples, and OpenAPI specs."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default="contracts",
        help="Contract package root directory.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    summary = validate_contract_tree(root)

    if summary.ok:
        print(
            "contract_validation=pass "
            f"schemas={summary.schema_count} "
            f"examples={summary.example_count} "
            f"openapi={summary.openapi_count}"
        )
        return 0

    for failure in summary.failures:
        print(f"contract validation failure: {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
