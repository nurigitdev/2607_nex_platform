from __future__ import annotations

import copy
from pathlib import Path

import pytest
import validate_p8_contract_hygiene as hygiene

ROOT = Path(__file__).parents[1]
CONTRACTS = ROOT / "contracts"


def test_repository_p8_contract_hygiene_is_clean() -> None:
    summary = hygiene.validate_p8_contract_hygiene(ROOT, CONTRACTS)

    assert summary.ok, summary.failures
    assert summary.schema_count >= 191
    assert summary.example_count >= 255
    assert summary.negative_example_count >= 221
    assert summary.openapi_count == 9
    assert summary.reference_count >= 1000
    assert summary.parity_count == 25
    assert summary.terminology_count >= 21


def test_reference_resolver_supports_contract_and_repository_roots(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path
    contracts_root = tmp_path / "contracts"
    contract_schema = contracts_root / "schemas/sample.schema.json"
    document_schema = tmp_path / "docs/sample.schema.json"
    contract_schema.parent.mkdir(parents=True)
    document_schema.parent.mkdir(parents=True)
    contract_schema.write_text("{}", encoding="utf-8")
    document_schema.write_text("{}", encoding="utf-8")

    assert hygiene.resolve_repository_reference(
        repository_root, contracts_root, "schemas/sample.schema.json"
    ) == contract_schema
    assert hygiene.resolve_repository_reference(
        repository_root, contracts_root, "docs/sample.schema.json"
    ) == document_schema
    assert (
        hygiene.resolve_repository_reference(
            repository_root, contracts_root, "../outside.schema.json"
        )
        is None
    )
    assert (
        hygiene.resolve_repository_reference(
            repository_root, contracts_root, "schemas/missing.schema.json"
        )
        is None
    )


def test_index_hygiene_rejects_duplicate_and_unindexed_payloads(
    tmp_path: Path,
) -> None:
    contracts_root = tmp_path / "contracts"
    payload_root = contracts_root / "examples"
    schema = contracts_root / "schemas/sample.schema.json"
    payload = payload_root / "sample.json"
    orphan = payload_root / "orphan.json"
    schema.parent.mkdir(parents=True)
    payload_root.mkdir(parents=True)
    schema.write_text("{}", encoding="utf-8")
    payload.write_text("{}", encoding="utf-8")
    orphan.write_text("{}", encoding="utf-8")
    entries = [
        {
            "name": "sample",
            "path": "examples/sample.json",
            "schema": "schemas/sample.schema.json",
        },
        {
            "name": "sample",
            "path": "examples/sample.json",
            "schema": "schemas/missing.schema.json",
        },
        {
            "name": "unsafe",
            "path": "../outside.json",
            "schema": "schemas/sample.schema.json",
        },
        {"name": "incomplete"},
    ]
    summary = hygiene.P8ContractHygieneSummary()

    hygiene._validate_index(
        contracts_root=contracts_root,
        entries=entries,
        payload_root=payload_root,
        index_label="examples/index.json",
        summary=summary,
    )

    assert any("duplicate name" in failure for failure in summary.failures)
    assert any("duplicate path" in failure for failure in summary.failures)
    assert any("missing repository reference" in failure for failure in summary.failures)
    assert any("unsafe repository reference" in failure for failure in summary.failures)
    assert any("unindexed payload" in failure for failure in summary.failures)
    assert any("indexed payload missing" in failure for failure in summary.failures)
    assert any("incomplete entry" in failure for failure in summary.failures)


def test_reference_hygiene_rejects_unresolved_openapi_annotation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec_path = tmp_path / "contracts/openapi/sample.openapi.yaml"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text("openapi: 3.1.0", encoding="utf-8")
    monkeypatch.setattr(hygiene, "_validate_index", lambda **_kwargs: None)
    monkeypatch.setattr(hygiene.validate_contracts, "load_example_index", lambda _root: [])
    monkeypatch.setattr(
        hygiene.validate_contracts, "load_negative_example_index", lambda _root: []
    )
    monkeypatch.setattr(
        hygiene.validate_contracts, "iter_openapi_files", lambda _root: [spec_path]
    )
    monkeypatch.setattr(
        hygiene.validate_contracts,
        "load_structured_file",
        lambda _path: {"schema": {"x-nex-canonical-json-schema": 42}},
    )
    summary = hygiene.P8ContractHygieneSummary()

    hygiene.validate_reference_hygiene(tmp_path, tmp_path / "contracts", summary)

    assert summary.failures == [
        "sample.openapi.yaml: unresolved canonical schema 42"
    ]


def test_parity_scan_detects_shared_component_and_operation_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = hygiene.validate_contracts.load_structured_file

    def load_with_drift(path: Path):
        payload = original(path)
        if path.name == "nex-ae-api.openapi.yaml":
            payload = copy.deepcopy(payload)
            payload["components"]["schemas"]["WcApprovalDecision"][
                "x-nex-canonical-json-schema"
            ] = "schemas/service/nex_wc/drift.schema.json"
            payload["paths"]["/api/v1/approval-gates"]["get"][
                "operationId"
            ] = "driftedOperation"
        return payload

    monkeypatch.setattr(hygiene.validate_contracts, "load_structured_file", load_with_drift)
    summary = hygiene.P8ContractHygieneSummary()

    hygiene.validate_p8_parity(CONTRACTS, summary)

    assert any("WcApprovalDecision" in failure for failure in summary.failures)
    assert any("driftedOperation" in failure for failure in summary.failures)
    assert summary.parity_count == 23


def test_parity_scan_detects_missing_component_and_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = hygiene.validate_contracts.load_structured_file

    def load_with_missing_surface(path: Path):
        payload = original(path)
        if path.name == "nex-wc.openapi.yaml":
            payload = copy.deepcopy(payload)
            del payload["components"]["schemas"]["ApprovalDecision"]
            del payload["paths"]["/api/v1/approval-gates"]
        return payload

    monkeypatch.setattr(
        hygiene.validate_contracts, "load_structured_file", load_with_missing_surface
    )
    summary = hygiene.P8ContractHygieneSummary()

    hygiene.validate_p8_parity(CONTRACTS, summary)

    assert any("missing shared component ApprovalDecision" in failure for failure in summary.failures)
    assert any("missing GET /api/v1/approval-gates" in failure for failure in summary.failures)
    assert summary.parity_count == 23


def test_terminology_scan_detects_forbidden_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = hygiene.validate_contracts.load_structured_file

    def load_with_alias(path: Path):
        payload = original(path)
        if path.name == "wc_approval_work_item.nsl_write.json":
            payload = copy.deepcopy(payload)
            payload["display_safe_summary"] = "Legacy NSL-WRITE alias"
        return payload

    monkeypatch.setattr(hygiene.validate_contracts, "load_structured_file", load_with_alias)
    summary = hygiene.P8ContractHygieneSummary()

    hygiene.validate_p8_terminology(CONTRACTS, summary)

    assert any("NSL-WRITE" in failure for failure in summary.failures)


def test_terminology_scan_detects_schema_alias_and_enum_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = hygiene.validate_contracts.load_structured_file

    def load_with_schema_drift(path: Path):
        payload = original(path)
        if path.name == "approval_work_item.v1.schema.json":
            payload = copy.deepcopy(payload)
            payload["title"] = "Legacy BUSINESS-FORMAL contract"
            del payload["properties"]["approval_domain"]["enum"]
        elif path.name == "approver_resolution_request.v1.schema.json":
            payload = copy.deepcopy(payload)
            payload["properties"]["approval_domain"]["enum"] = ["NSL_WRITE"]
        return payload

    monkeypatch.setattr(
        hygiene.validate_contracts, "load_structured_file", load_with_schema_drift
    )
    summary = hygiene.P8ContractHygieneSummary()

    hygiene.validate_p8_terminology(CONTRACTS, summary)

    assert any("BUSINESS-FORMAL" in failure for failure in summary.failures)
    assert any("missing canonical enum" in failure for failure in summary.failures)
    assert any("canonical enum drift" in failure for failure in summary.failures)


def test_hygiene_runner_converts_scan_error_to_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hygiene.validate_contracts,
        "validate_contract_tree",
        lambda _root: hygiene.validate_contracts.ContractValidationSummary(),
    )
    monkeypatch.setattr(
        hygiene,
        "validate_reference_hygiene",
        lambda *_args: (_ for _ in ()).throw(ValueError("invalid index")),
    )

    summary = hygiene.validate_p8_contract_hygiene(ROOT, CONTRACTS)

    assert summary.failures == ["hygiene runner error: invalid index"]


def test_hygiene_main_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        hygiene,
        "validate_p8_contract_hygiene",
        lambda *_args: hygiene.P8ContractHygieneSummary(failures=["drift"]),
    )

    assert hygiene.main([]) == 1
    assert "P8 contract hygiene failure: drift" in capsys.readouterr().out


def test_hygiene_main_reports_inventory(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        hygiene,
        "validate_p8_contract_hygiene",
        lambda *_args: hygiene.P8ContractHygieneSummary(
            schema_count=1,
            example_count=2,
            negative_example_count=3,
            openapi_count=4,
            reference_count=5,
            parity_count=6,
            terminology_count=7,
        ),
    )

    assert hygiene.main([]) == 0
    output = capsys.readouterr().out
    assert "p8_contract_hygiene=pass" in output
    assert "references=5 parity=6 terminology=7" in output


def test_nested_value_rejects_missing_path() -> None:
    with pytest.raises(KeyError, match="properties.missing.enum"):
        hygiene._nested_value({}, ("properties", "missing", "enum"))


def test_walk_helpers_cover_nested_lists_and_scalars() -> None:
    payload = {"items": [{"target": "value"}, "text", 1]}

    assert list(hygiene._walk_named_values(payload, "target")) == ["value"]
    assert list(hygiene._walk_strings(payload)) == ["value", "text"]


def test_repository_indexes_have_unique_names_and_paths() -> None:
    positive = hygiene.validate_contracts.load_example_index(CONTRACTS)
    negative = hygiene.validate_contracts.load_negative_example_index(CONTRACTS)

    for entries in (positive, negative):
        assert len(entries) == len({entry["name"] for entry in entries})
        assert len(entries) == len({entry["path"] for entry in entries})


def test_p8_example_schema_references_are_explicit() -> None:
    entries = (
        hygiene.validate_contracts.load_example_index(CONTRACTS)
        + hygiene.validate_contracts.load_negative_example_index(CONTRACTS)
    )
    p8_entries = [
        entry
        for entry in entries
        if entry["schema"].startswith(hygiene.P8_SCHEMA_PREFIXES)
    ]

    assert len(p8_entries) >= 34
    assert all((CONTRACTS / entry["schema"]).is_file() for entry in p8_entries)
    assert all((CONTRACTS / entry["path"]).is_file() for entry in p8_entries)
