from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import runpy
import sys

import pytest

from nex_runtime import DEFAULT_SERVICE_SCOPE, issue_mock_service_token
from nex_cx.access_context import (
    CX_ACCESS_CONTEXT_SCHEMA_VERSION,
    CxAccessContextError,
    build_access_context_ownership_ref,
    ownership_ref_matches_access_context,
    resolve_cx_access_context,
)
import run_cx_access_context_contract as contract


NOW = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)


def _authorization(
    service_id: str = "nex-ae-api",
    *,
    audience: str = "nex-cx",
    scopes: list[str] | None = None,
    ttl_seconds: int = 3600,
) -> str:
    issued = issue_mock_service_token(
        service_id=service_id,
        audience=audience,
        scopes=scopes,
        issued_at=NOW,
        ttl_seconds=ttl_seconds,
    )
    return f"Bearer {issued.access_token}"


def _resolve(**overrides: object):
    values: dict[str, object] = {
        "authorization": _authorization(),
        "tenant_id": "tenant-a",
        "subject_id": "employee-1004",
        "request_id": "request-0912",
        "trace_id": "91200000000000000000000000000001",
        "now": NOW + timedelta(seconds=1),
    }
    values.update(overrides)
    return resolve_cx_access_context(**values)  # type: ignore[arg-type]


def test_access_context_resolves_trusted_service_and_safe_wire_shape() -> None:
    context = _resolve()

    assert context.ownership_key == ("tenant-a", "employee-1004")
    assert context.to_wire() == {
        "access_context_schema_version": CX_ACCESS_CONTEXT_SCHEMA_VERSION,
        "propagation_mode": "trusted_service_asserted_subject",
        "caller_service_ref": {"type": "platform.service", "id": "nex-ae-api"},
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
        "subject_ref": {"type": "oa.user", "id": "employee-1004"},
        "request_id": "request-0912",
        "trace_id": "91200000000000000000000000000001",
        "scopes": [DEFAULT_SERVICE_SCOPE],
    }
    assert "Bearer" not in repr(context.to_wire())


@pytest.mark.parametrize("service_id", ["nex-ae-api", "nex-ag", "nex-cx"])
def test_access_context_accepts_explicit_trusted_callers(service_id: str) -> None:
    context = _resolve(authorization=_authorization(service_id))

    assert context.caller_service_id == service_id


@pytest.mark.parametrize(
    ("authorization", "expected_code"),
    [
        (None, "AUTHORIZATION_HEADER_MISSING"),
        ("Basic unsafe", "AUTHORIZATION_HEADER_INVALID"),
        (
            _authorization(scopes=["generation:request"]),
            "TOKEN_SCOPE_MISSING",
        ),
        (
            _authorization(ttl_seconds=1),
            "TOKEN_EXPIRED",
        ),
    ],
)
def test_access_context_rejects_invalid_service_claim(
    authorization: str | None,
    expected_code: str,
) -> None:
    with pytest.raises(CxAccessContextError) as caught:
        _resolve(authorization=authorization, now=NOW + timedelta(seconds=2))

    assert caught.value.status_code == 401
    assert caught.value.error_code == expected_code


def test_access_context_rejects_untrusted_service() -> None:
    with pytest.raises(CxAccessContextError) as caught:
        _resolve(authorization=_authorization("nex-mo"))

    assert caught.value.status_code == 403
    assert caught.value.error_code == "CX_CALLER_SERVICE_FORBIDDEN"
    assert "ownership context" in caught.value.detail


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("tenant_id", ""),
        ("tenant_id", "../tenant"),
        ("subject_id", object()),
        ("request_id", "has spaces"),
        ("trace_id", "x" * 129),
    ],
)
def test_access_context_rejects_unsafe_identifiers(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(CxAccessContextError) as caught:
        _resolve(**{field_name: value})

    assert caught.value.status_code == 422
    assert caught.value.error_code == "CX_ACCESS_CONTEXT_INVALID"
    assert field_name in caught.value.detail


def test_access_context_builds_matching_canonical_ownership_ref() -> None:
    context = _resolve()
    ownership_ref = build_access_context_ownership_ref(context)

    assert ownership_ref_matches_access_context(context, ownership_ref)
    assert ownership_ref["uploaded_by_subject_ref"]["id"] == "employee-1004"


@pytest.mark.parametrize(
    "ownership_ref",
    [
        None,
        {},
        {"tenant_ref": {}, "owner_subject_ref": {}},
        {
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-b"},
            "owner_subject_ref": {"type": "oa.user", "id": "employee-1004"},
        },
        {
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
            "owner_subject_ref": {"type": "oa.group", "id": "employee-1004"},
        },
    ],
)
def test_ownership_match_is_fail_closed(ownership_ref: object) -> None:
    assert not ownership_ref_matches_access_context(_resolve(), ownership_ref)


def test_access_context_contract_evidence_passes() -> None:
    evidence = contract.run_cx_access_context_contract()

    assert evidence["status"] == "PASS"
    assert evidence["summary"] == {
        "check_count": 5,
        "passed_check_count": 5,
        "dgx_required": False,
        "postgres_required": False,
    }
    assert contract.summary_line(evidence) == (
        "cx_access_context_contract=PASS checks=5/5 "
        "postgres_required=False dgx_required=False"
    )


def test_access_context_contract_cli_paths(monkeypatch, capsys) -> None:
    passing = contract.run_cx_access_context_contract()
    monkeypatch.setattr(contract, "run_cx_access_context_contract", lambda: passing)

    assert contract.main(["--summary"]) == 0
    assert "checks=5/5" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_cx_access_context_contract",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
    assert "checks=None/None" in contract.summary_line({"status": "FAIL"})


def test_access_context_contract_module_entrypoint(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", [contract.__file__, "--summary"])

    with pytest.raises(SystemExit) as caught:
        runpy.run_path(contract.__file__, run_name="__main__")

    assert caught.value.code == 0
