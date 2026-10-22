from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest
from nex_ae_api import nsl_v02_public_api as adapter_module
from nex_ae_api.nsl_v02_public_api import (
    NSL_V02_PUBLIC_API_ADAPTER_SCHEMA_VERSION,
    NSL_V02_REQUIRED_PUBLIC_SYMBOLS,
    NslV02PublicApiError,
    load_nsl_v02_public_api,
)

HASH = "sha256:" + "a" * 64


def _readiness() -> dict[str, object]:
    return {
        "schema_version": "nsl_installed_package_readiness.v2",
        "status": "PASS",
        "lock_schema_version": "nsl_wheel_lock.v2",
        "distribution": "nex-skill-language",
        "package_version": "0.2.0",
        "runtime_import_origin": "installed_distribution",
        "public_api_complete": True,
        "in_process_profile_admissible": True,
        "public_api_symbols": list(NSL_V02_REQUIRED_PUBLIC_SYMBOLS),
        "release_admission_hash": HASH,
    }


def _symbols(*, changed_name: str | None = None) -> tuple[type, ...]:
    names = list(NSL_V02_REQUIRED_PUBLIC_SYMBOLS)
    if changed_name is not None:
        names[-1] = changed_name
    return tuple(type(name, (), {}) for name in names)


def test_adapter_exposes_only_admitted_v02_public_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported = _symbols()
    monkeypatch.setattr(adapter_module, "_import_public_api", lambda: imported)

    adapter = load_nsl_v02_public_api(_readiness())

    assert adapter.schema_version == NSL_V02_PUBLIC_API_ADAPTER_SCHEMA_VERSION
    assert tuple(adapter.symbols()) == NSL_V02_REQUIRED_PUBLIC_SYMBOLS
    assert tuple(adapter.symbols().values()) == imported
    assert adapter.resume_token is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("ResumeToken")
    ]
    assert adapter.runtime_policy_port is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("RuntimePolicyPort")
    ]
    assert adapter.policy_decision is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("PolicyDecision")
    ]
    assert adapter.idempotency_evidence_port is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("IdempotencyEvidencePort")
    ]
    assert adapter.idempotency_reservation is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("IdempotencyReservation")
    ]
    assert adapter.write_evidence_port is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("WriteEvidencePort")
    ]
    assert adapter.write_attempt_record is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("WriteAttemptRecord")
    ]
    assert adapter.write_requested_receipt is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("WriteRequestedReceipt")
    ]
    assert adapter.write_call_request is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("WriteCallRequest")
    ]
    assert adapter.write_outcome_identity is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("WriteOutcomeIdentity")
    ]
    assert adapter.write_result_envelope is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("WriteResultEnvelope")
    ]
    assert adapter.write_committed is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("WriteCommitted")
    ]
    assert adapter.write_not_committed is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("WriteNotCommitted")
    ]
    assert adapter.write_commit_unknown is imported[
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS.index("WriteCommitUnknown")
    ]
    assert adapter.release_admission_hash == HASH
    assert adapter.api_contract_hash.startswith("sha256:")


def test_adapter_imports_the_admitted_public_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_api = types.ModuleType("nsl.api")
    imported = _symbols()
    for name, symbol in zip(NSL_V02_REQUIRED_PUBLIC_SYMBOLS, imported, strict=True):
        setattr(public_api, name, symbol)
    monkeypatch.setitem(sys.modules, "nsl.api", public_api)

    adapter = load_nsl_v02_public_api(_readiness())

    assert tuple(adapter.symbols().values()) == imported


def test_public_api_error_string_is_its_safe_detail() -> None:
    error = NslV02PublicApiError("ae.nsl_v02.example", "safe detail")

    assert str(error) == "safe detail"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "other"),
        ("status", "FAIL"),
        ("lock_schema_version", "nsl_wheel_lock.v1"),
        ("distribution", "other"),
        ("package_version", "0.1.0"),
        ("runtime_import_origin", "source_checkout"),
        ("public_api_complete", False),
        ("in_process_profile_admissible", False),
    ],
)
def test_adapter_rejects_non_exact_readiness(field: str, value: object) -> None:
    readiness = _readiness()
    readiness[field] = value

    with pytest.raises(NslV02PublicApiError) as caught:
        load_nsl_v02_public_api(readiness)
    assert caught.value.error_code == "ae.nsl_v02.readiness_invalid"


def test_adapter_rejects_unadmitted_or_mismatched_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness = _readiness()
    readiness["public_api_symbols"] = list(NSL_V02_REQUIRED_PUBLIC_SYMBOLS[:-1])
    with pytest.raises(NslV02PublicApiError) as not_admitted:
        load_nsl_v02_public_api(readiness)
    assert not_admitted.value.error_code == "ae.nsl_v02.public_api_not_admitted"

    monkeypatch.setattr(
        adapter_module,
        "_import_public_api",
        lambda: _symbols(changed_name="PrivateReplacement"),
    )
    with pytest.raises(NslV02PublicApiError) as mismatch:
        load_nsl_v02_public_api(_readiness())
    assert mismatch.value.error_code == "ae.nsl_v02.public_api_mismatch"


def test_adapter_rejects_invalid_release_identity_and_non_mapping() -> None:
    readiness = _readiness()
    readiness["release_admission_hash"] = "bad"
    with pytest.raises(NslV02PublicApiError) as invalid_hash:
        load_nsl_v02_public_api(readiness)
    assert invalid_hash.value.error_code == "ae.nsl_v02.release_identity_invalid"

    with pytest.raises(NslV02PublicApiError) as invalid_readiness:
        load_nsl_v02_public_api(None)  # type: ignore[arg-type]
    assert invalid_readiness.value.error_code == "ae.nsl_v02.readiness_invalid"


def test_adapter_architecture_imports_no_private_nsl_modules() -> None:
    source_path = Path(adapter_module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    nsl_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and (
            (isinstance(node, ast.ImportFrom) and str(node.module).startswith("nsl"))
            or (
                isinstance(node, ast.Import)
                and any(alias.name.startswith("nsl") for alias in node.names)
            )
        )
    ]

    assert len(nsl_imports) == 1
    public_import = nsl_imports[0]
    assert isinstance(public_import, ast.ImportFrom)
    assert public_import.module == "nsl.api"
    assert {alias.name for alias in public_import.names} == set(
        NSL_V02_REQUIRED_PUBLIC_SYMBOLS
    )
    assert "ResumeToken" in {alias.name for alias in public_import.names}
    assert {
        "RuntimePolicyPort",
        "WritePolicyRequest",
        "PolicyDecision",
        "PolicyEffect",
        "IdempotencyEvidencePort",
        "IdempotencyEvidenceRecord",
        "IdempotencyReservation",
        "IdempotencyDisposition",
        "WriteEvidencePort",
        "WriteAttemptRecord",
        "WriteRequestedReceipt",
        "WriteCallRequest",
        "WriteOutcomeIdentity",
        "WriteResultEnvelope",
        "WriteCommitted",
        "WriteNotCommitted",
        "WriteCommitUnknown",
    }.issubset({alias.name for alias in public_import.names})
