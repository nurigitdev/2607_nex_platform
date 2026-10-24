from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import validate_contracts

P8_SHARED_BINDINGS = (
    (
        "schemas/service/nex_wc/approval_decision.v1.schema.json",
        (("nex-wc.openapi.yaml", "ApprovalDecision"),
         ("nex-ae-api.openapi.yaml", "WcApprovalDecision")),
    ),
    (
        "schemas/service/nex_wc/approval_decision_request.v1.schema.json",
        (("nex-wc.openapi.yaml", "ApprovalDecisionRequest"),
         ("nex-ae-api.openapi.yaml", "WcApprovalDecisionRequest")),
    ),
    (
        "schemas/service/nex_wc/approval_gate_detail.v1.schema.json",
        (("nex-wc.openapi.yaml", "ApprovalGateDetail"),
         ("nex-ae-api.openapi.yaml", "WcApprovalGateDetail")),
    ),
    (
        "schemas/service/nex_wc/approval_inbox.v1.schema.json",
        (("nex-wc.openapi.yaml", "ApprovalInbox"),
         ("nex-ae-api.openapi.yaml", "WcApprovalInbox")),
    ),
)

P8_OPERATIONS = (
    ("nex-ae-api.openapi.yaml", "/api/v1/voucher-attachments/batches", "post", "createAeVoucherAttachmentBatch"),
    ("nex-ae-api.openapi.yaml", "/api/v1/voucher-attachments/batches/{attachment_batch_id}", "get", "getAeVoucherAttachmentBatch"),
    ("nex-ae-api.openapi.yaml", "/api/v1/voucher-attachments/batches/{attachment_batch_id}/items", "post", "uploadAeVoucherAttachmentItem"),
    ("nex-ae-api.openapi.yaml", "/api/v1/voucher-attachments/batches/{attachment_batch_id}/items/{attachment_id}", "delete", "removeAeVoucherAttachmentItem"),
    ("nex-ae-api.openapi.yaml", "/api/v1/voucher-attachments/batches/{attachment_batch_id}/items/{attachment_id}/content", "get", "getAeVoucherAttachmentContent"),
    ("nex-ae-api.openapi.yaml", "/api/v1/voucher-attachments/batches/{attachment_batch_id}/finalize", "post", "finalizeAeVoucherAttachmentBatch"),
    ("nex-ae-api.openapi.yaml", "/api/v1/voucher-attachments/batches/{attachment_batch_id}/lock", "post", "lockAeVoucherAttachmentManifest"),
    ("nex-ae-api.openapi.yaml", "/api/v1/approval-gates", "get", "listAeApprovalGates"),
    ("nex-ae-api.openapi.yaml", "/api/v1/approval-gates/{approval_work_item_id}", "get", "getAeApprovalGate"),
    ("nex-ae-api.openapi.yaml", "/api/v1/approval-gates/{approval_work_item_id}/decisions", "post", "decideAeApprovalGate"),
    ("nex-wc.openapi.yaml", "/api/v1/approval-gates", "get", "listWcApprovalGates"),
    ("nex-wc.openapi.yaml", "/api/v1/approval-gates/{approval_work_item_id}", "get", "getWcApprovalGate"),
    ("nex-wc.openapi.yaml", "/api/v1/approval-gates/{approval_work_item_id}/decisions", "post", "decideWcApprovalGate"),
    ("nex-eos.openapi.yaml", "/internal/v1/finance/voucher-drafts", "post", "createEosVoucherDraft"),
    ("nex-eos.openapi.yaml", "/internal/v1/organization/approver-resolutions", "post", "resolveEosApprover"),
    ("nex-eos.openapi.yaml", "/internal/v1/business-operations/{business_operation_id}", "get", "getEosBusinessOperation"),
    ("nex-eos.openapi.yaml", "/internal/v1/finance/voucher-drafts/{voucher_id}/verification", "get", "verifyEosVoucherDraft"),
)

P8_ENUMS = (
    (
        "schemas/service/nex_wc/approval_work_item.v1.schema.json",
        ("properties", "approval_domain", "enum"),
        ("AGENT_FORMAL", "NSL_WRITE", "BUSINESS_FORMAL"),
    ),
    (
        "schemas/service/nex_eos/approver_resolution_request.v1.schema.json",
        ("properties", "approval_domain", "enum"),
        ("AGENT_FORMAL", "NSL_WRITE", "BUSINESS_FORMAL"),
    ),
    (
        "schemas/service/nex_eos/approver_resolution.v1.schema.json",
        ("properties", "approval_domain", "enum"),
        ("AGENT_FORMAL", "NSL_WRITE", "BUSINESS_FORMAL"),
    ),
    (
        "schemas/service/nex_eos/create_voucher_draft_result.v1.schema.json",
        ("properties", "commit_state", "enum"),
        ("COMMITTED", "NOT_COMMITTED", "UNKNOWN_COMMIT_STATE"),
    ),
)

P8_SCHEMA_PREFIXES = (
    "schemas/service/nex_ae_api/voucher_attachment_",
    "schemas/service/nex_eos/",
    "schemas/service/nex_wc/approval_",
    "schemas/service/nex_wc/delegation_",
    "schemas/service/nex_wc/human_gate_view.",
)

FORBIDDEN_TERMINOLOGY = (
    "DELETATION",
    "NSL-WRITE",
    "BUSINESS-FORMAL",
    "AGENT-FORMAL",
    "UNKNOWN COMMIT STATE",
    "UNKNOWN-COMMIT-STATE",
)


@dataclass
class P8ContractHygieneSummary:
    schema_count: int = 0
    example_count: int = 0
    negative_example_count: int = 0
    openapi_count: int = 0
    reference_count: int = 0
    parity_count: int = 0
    terminology_count: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _nested_value(payload: Any, path: tuple[str, ...]) -> Any:
    current = payload
    for part in path:
        if not isinstance(current, dict) or part not in current:
            raise KeyError(".".join(path))
        current = current[part]
    return current


def _walk_named_values(payload: Any, key: str) -> Iterable[Any]:
    if isinstance(payload, dict):
        for current_key, value in payload.items():
            if current_key == key:
                yield value
            yield from _walk_named_values(value, key)
    elif isinstance(payload, list):
        for value in payload:
            yield from _walk_named_values(value, key)


def _walk_strings(payload: Any) -> Iterable[str]:
    if isinstance(payload, str):
        yield payload
    elif isinstance(payload, dict):
        for value in payload.values():
            yield from _walk_strings(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _walk_strings(value)


def resolve_repository_reference(
    repository_root: Path,
    contracts_root: Path,
    reference: str,
) -> Path | None:
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    for candidate in (contracts_root / relative, repository_root / relative):
        if candidate.is_file():
            return candidate
    return None


def _validate_index(
    *,
    contracts_root: Path,
    entries: list[dict[str, str]],
    payload_root: Path,
    index_label: str,
    summary: P8ContractHygieneSummary,
) -> None:
    names: set[str] = set()
    paths: set[str] = set()
    for entry in entries:
        name = entry.get("name")
        payload_reference = entry.get("path")
        schema_reference = entry.get("schema")
        if not name or not payload_reference or not schema_reference:
            summary.failures.append(f"{index_label}: incomplete entry {entry!r}")
            continue
        if name in names:
            summary.failures.append(f"{index_label}: duplicate name {name}")
        if payload_reference in paths:
            summary.failures.append(
                f"{index_label}: duplicate path {payload_reference}"
            )
        names.add(name)
        paths.add(payload_reference)
        for reference in (payload_reference, schema_reference):
            path = Path(reference)
            if path.is_absolute() or ".." in path.parts:
                summary.failures.append(
                    f"{index_label}: unsafe repository reference {reference}"
                )
            elif not (contracts_root / path).is_file():
                summary.failures.append(
                    f"{index_label}: missing repository reference {reference}"
                )
            else:
                summary.reference_count += 1

    actual_paths = {
        str(path.relative_to(contracts_root))
        for path in payload_root.glob("**/*.json")
        if path.name != "index.json"
    }
    for orphan in sorted(actual_paths - paths):
        summary.failures.append(f"{index_label}: unindexed payload {orphan}")
    for missing in sorted(paths - actual_paths):
        summary.failures.append(f"{index_label}: indexed payload missing {missing}")


def validate_reference_hygiene(
    repository_root: Path,
    contracts_root: Path,
    summary: P8ContractHygieneSummary,
) -> None:
    _validate_index(
        contracts_root=contracts_root,
        entries=validate_contracts.load_example_index(contracts_root),
        payload_root=contracts_root / "examples",
        index_label="examples/index.json",
        summary=summary,
    )
    _validate_index(
        contracts_root=contracts_root,
        entries=validate_contracts.load_negative_example_index(contracts_root),
        payload_root=contracts_root / "tests" / "negative",
        index_label="tests/negative/index.json",
        summary=summary,
    )

    for spec_path in validate_contracts.iter_openapi_files(contracts_root):
        spec = validate_contracts.load_structured_file(spec_path)
        for reference in _walk_named_values(spec, "x-nex-canonical-json-schema"):
            if not isinstance(reference, str) or not resolve_repository_reference(
                repository_root, contracts_root, reference
            ):
                summary.failures.append(
                    f"{spec_path.name}: unresolved canonical schema {reference!r}"
                )
            else:
                summary.reference_count += 1


def validate_p8_parity(
    contracts_root: Path,
    summary: P8ContractHygieneSummary,
) -> None:
    specs = {
        name: validate_contracts.load_structured_file(contracts_root / "openapi" / name)
        for name in {item[0] for item in P8_OPERATIONS}
    }
    for schema_reference, exposures in P8_SHARED_BINDINGS:
        for spec_name, component_name in exposures:
            try:
                actual = specs[spec_name]["components"]["schemas"][component_name][
                    "x-nex-canonical-json-schema"
                ]
            except KeyError:
                summary.failures.append(
                    f"{spec_name}: missing shared component {component_name}"
                )
            else:
                if actual != schema_reference:
                    summary.failures.append(
                        f"{spec_name}:{component_name}: expected {schema_reference}, "
                        f"found {actual}"
                    )
                else:
                    summary.parity_count += 1

    for spec_name, route, method, operation_id in P8_OPERATIONS:
        try:
            actual = specs[spec_name]["paths"][route][method]["operationId"]
        except KeyError:
            summary.failures.append(f"{spec_name}: missing {method.upper()} {route}")
        else:
            if actual != operation_id:
                summary.failures.append(
                    f"{spec_name}:{method.upper()} {route}: expected operationId "
                    f"{operation_id}, found {actual}"
                )
            else:
                summary.parity_count += 1


def validate_p8_terminology(
    contracts_root: Path,
    summary: P8ContractHygieneSummary,
) -> None:
    schema_paths: set[str] = set()
    for entry in (
        validate_contracts.load_example_index(contracts_root)
        + validate_contracts.load_negative_example_index(contracts_root)
    ):
        schema_reference = entry.get("schema", "")
        if schema_reference.startswith(P8_SCHEMA_PREFIXES):
            schema_paths.add(schema_reference)
            payload = validate_contracts.load_structured_file(
                contracts_root / entry["path"]
            )
            for value in _walk_strings(payload):
                for forbidden in FORBIDDEN_TERMINOLOGY:
                    if forbidden in value:
                        summary.failures.append(
                            f"{entry['path']}: forbidden terminology {forbidden!r}"
                        )

    for schema_reference in sorted(schema_paths):
        payload = validate_contracts.load_structured_file(
            contracts_root / schema_reference
        )
        for value in _walk_strings(payload):
            for forbidden in FORBIDDEN_TERMINOLOGY:
                if forbidden in value:
                    summary.failures.append(
                        f"{schema_reference}: forbidden terminology {forbidden!r}"
                    )
        summary.terminology_count += 1

    for schema_reference, path, expected in P8_ENUMS:
        schema = validate_contracts.load_structured_file(
            contracts_root / schema_reference
        )
        try:
            actual = tuple(_nested_value(schema, path))
        except (KeyError, TypeError):
            summary.failures.append(
                f"{schema_reference}: missing canonical enum {'.'.join(path)}"
            )
        else:
            if actual != expected:
                summary.failures.append(
                    f"{schema_reference}: canonical enum drift: {actual!r}"
                )
            else:
                summary.terminology_count += 1


def validate_p8_contract_hygiene(
    repository_root: Path,
    contracts_root: Path,
) -> P8ContractHygieneSummary:
    base = validate_contracts.validate_contract_tree(contracts_root)
    summary = P8ContractHygieneSummary(
        schema_count=base.schema_count,
        example_count=base.example_count,
        negative_example_count=base.negative_example_count,
        openapi_count=base.openapi_count,
        failures=list(base.failures),
    )
    try:
        validate_reference_hygiene(repository_root, contracts_root, summary)
        validate_p8_parity(contracts_root, summary)
        validate_p8_terminology(contracts_root, summary)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        summary.failures.append(f"hygiene runner error: {exc}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate P8 contract, OpenAPI, example, and reference hygiene."
    )
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--contracts-root", default="contracts")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = validate_p8_contract_hygiene(
        Path(args.repository_root), Path(args.contracts_root)
    )
    if not summary.ok:
        for failure in summary.failures:
            print(f"P8 contract hygiene failure: {failure}")
        return 1
    print(
        "p8_contract_hygiene=pass "
        f"schemas={summary.schema_count} examples={summary.example_count} "
        f"negative_examples={summary.negative_example_count} "
        f"openapi={summary.openapi_count} references={summary.reference_count} "
        f"parity={summary.parity_count} terminology={summary.terminology_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
