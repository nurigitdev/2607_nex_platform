from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from nex_ae_api import coa_semantic_resolution
from nex_ae_api.coa_semantic_resolution import (
    CoaSemanticResolutionError,
    HttpEosSemanticAccountResolver,
    build_nsl_semantic_account_result,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

TENANT_ID = "tenant-a"
SUBJECT_ID = "subject-a"
COMPANY_ID = "d1000000-0000-4000-8000-000000000001"
ACCOUNT_ID = "d6000000-0000-4000-8000-000000000001"
CONTRACT_ROOT = Path("domains/mybee/config/account_catalog")


def _payload(**changes: object) -> dict[str, object]:
    evidence = {
        "adoption_id": "d8000000-0000-4000-8000-000000000001",
        "binding_id": "d9000000-0000-4000-8000-000000000001",
        "entry_id": "d3000000-0000-4000-8000-000000000004",
        "account_id": ACCOUNT_ID,
    }
    payload: dict[str, object] = {
        "schema_version": "eos_coa_semantic_account_resolution.v1",
        "tenant_id": TENANT_ID,
        "company_id": COMPANY_ID,
        "effective_on": "2026-11-11",
        "currency": "KRW",
        "semantic_key": "MB-COA-CASH",
        "account_ref": {"type": "eos.account", "id": ACCOUNT_ID},
        "account_code": "CASH",
        "account_name": "Cash",
        "category": "ASSET",
        "account_type": "CASH",
        "statement_line_ref": "ASSET.CASH",
        "definition_account_code": "10101001",
        "evidence": evidence,
        "evidence_hash": semantic_sha256_hash_ref(evidence),
    }
    payload.update(changes)
    return payload


def _response(status_code: int, body: object) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "http://eos.test"),
    )


def test_semantic_account_resolver_sends_closed_signed_request() -> None:
    observed: dict[str, object] = {}

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        observed.update(method=method, url=url, **kwargs)
        return _response(200, _payload())

    resolver = HttpEosSemanticAccountResolver(
        base_url="http://eos.test/",
        service_token="signed-token",
        timeout_seconds=7,
        requester=request,
    )
    resolved = resolver.resolve(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        company_id=COMPANY_ID,
        semantic_key="mb-coa-cash",
        effective_on=date(2026, 11, 11),
        currency="krw",
    )

    assert observed["method"] == "GET"
    assert observed["url"] == (
        "http://eos.test/internal/v2/finance/accounts/resolve-semantic"
    )
    assert observed["params"] == {
        "company_id": COMPANY_ID,
        "semantic_key": "MB-COA-CASH",
        "effective_on": "2026-11-11",
        "currency": "KRW",
    }
    assert observed["headers"] == {
        "Authorization": "Bearer signed-token",
        "Accept": "application/json",
        "X-NeX-Tenant-Id": TENANT_ID,
        "X-NeX-Subject-Id": SUBJECT_ID,
        "X-Service-ID": "nex-ae-api",
    }
    assert observed["timeout"] == 7
    assert observed["follow_redirects"] is False
    assert resolved["account_ref"]["id"] == ACCOUNT_ID


def test_mybee_semantic_account_tool_contract_is_closed_and_not_admitted() -> None:
    contract = json.loads(
        (CONTRACT_ROOT / "semantic_account_resolution.v1.json").read_text()
    )
    schema = json.loads(
        (CONTRACT_ROOT / "semantic_account_resolution.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(contract)
    assert contract["tool_id"] == "FINANCE.ACCOUNT.RESOLVE_SEMANTIC"
    assert contract["operation_kind"] == "READ"
    assert contract["agent_constraints"] == {
        "account_code_generation": "FORBIDDEN",
        "account_uuid_authority": "EOS_ONLY",
        "ambiguous_resolution": "FAIL_CLOSED",
    }
    assert contract["runtime_admission"]["state"] == "CONTRACT_ONLY"


def test_nsl_result_builder_accepts_only_explicit_semantic_inputs() -> None:
    resolver = HttpEosSemanticAccountResolver(
        service_token="token", requester=lambda *args, **kwargs: _response(200, _payload())
    )
    result = build_nsl_semantic_account_result(
        resolver,
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        arguments={
            "company_id": COMPANY_ID,
            "semantic_key": "MB-COA-CASH",
            "effective_on": "2026-11-11",
            "currency": "KRW",
        },
    )
    assert result["definition_account_code"] == "10101001"

    with pytest.raises(CoaSemanticResolutionError) as invalid:
        build_nsl_semantic_account_result(
            resolver,
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            arguments="not-an-object",  # type: ignore[arg-type]
        )
    assert invalid.value.error_code == "ae.coa_semantic.arguments_invalid"

    with pytest.raises(CoaSemanticResolutionError) as invalid_date:
        build_nsl_semantic_account_result(
            resolver,
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            arguments={
                "company_id": COMPANY_ID,
                "semantic_key": "MB-COA-CASH",
                "effective_on": "not-a-date",
                "currency": "KRW",
            },
        )
    assert invalid_date.value.error_code == "ae.coa_semantic.arguments_invalid"


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": "tenant-b"},
        {"company_id": "d1000000-0000-4000-8000-000000000002"},
        {"currency": "USD"},
        {"semantic_key": "MB-COA-OTHER"},
        {"account_ref": {"type": "wrong", "id": ACCOUNT_ID}},
        {"account_ref": {"type": "eos.account", "id": "bad"}},
        {"evidence": {}},
        {"evidence_hash": "bad"},
        {"unexpected": True},
    ],
)
def test_semantic_account_resolver_rejects_response_drift(changes) -> None:
    resolver = HttpEosSemanticAccountResolver(
        service_token="token",
        requester=lambda *args, **kwargs: _response(200, _payload(**changes)),
    )
    with pytest.raises(CoaSemanticResolutionError) as raised:
        resolver.resolve(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            company_id=COMPANY_ID,
            semantic_key="MB-COA-CASH",
            effective_on=date(2026, 11, 11),
            currency="KRW",
        )
    assert raised.value.error_code == "ae.coa_semantic.response_invalid"


@pytest.mark.parametrize(
    ("requester", "error_code", "retryable"),
    [
        (
            lambda *args, **kwargs: (_ for _ in ()).throw(
                httpx.ReadTimeout("slow")
            ),
            "ae.coa_semantic.timeout",
            True,
        ),
        (
            lambda *args, **kwargs: (_ for _ in ()).throw(
                httpx.ConnectError("down")
            ),
            "ae.coa_semantic.transport_failed",
            True,
        ),
        (
            lambda *args, **kwargs: _response(
                503, {"error_code": "EOS_COA_AUTHORITY_UNAVAILABLE"}
            ),
            "EOS_COA_AUTHORITY_UNAVAILABLE",
            True,
        ),
        (
            lambda *args, **kwargs: _response(403, {}),
            "ae.coa_semantic.rejected",
            False,
        ),
    ],
)
def test_semantic_account_resolver_preserves_failure_taxonomy(
    requester, error_code, retryable
) -> None:
    resolver = HttpEosSemanticAccountResolver(
        service_token="token", requester=requester
    )
    with pytest.raises(CoaSemanticResolutionError) as raised:
        resolver.resolve(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            company_id=COMPANY_ID,
            semantic_key="MB-COA-CASH",
            effective_on=date(2026, 11, 11),
            currency="KRW",
        )
    assert raised.value.error_code == error_code
    assert raised.value.retryable is retryable


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": ""},
        {"requester_subject_id": ""},
        {"company_id": "bad"},
        {"semantic_key": "CASH"},
        {"effective_on": datetime(2026, 11, 11, tzinfo=UTC)},
        {"currency": "KR"},
    ],
)
def test_semantic_account_resolver_rejects_untrusted_request_inputs(changes) -> None:
    values = {
        "tenant_id": TENANT_ID,
        "requester_subject_id": SUBJECT_ID,
        "company_id": COMPANY_ID,
        "semantic_key": "MB-COA-CASH",
        "effective_on": date(2026, 11, 11),
        "currency": "KRW",
    }
    values.update(changes)
    resolver = HttpEosSemanticAccountResolver(
        service_token="token",
        requester=lambda *args, **kwargs: pytest.fail("HTTP must not be called"),
    )
    with pytest.raises(CoaSemanticResolutionError):
        resolver.resolve(**values)


def test_semantic_account_resolver_configuration_and_json_are_fail_closed(
    monkeypatch,
) -> None:
    with pytest.raises(ValueError):
        HttpEosSemanticAccountResolver(base_url="not-a-url")
    with pytest.raises(ValueError):
        HttpEosSemanticAccountResolver(timeout_seconds=0)

    monkeypatch.setenv("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "SIGNED_ONLY")
    resolver = HttpEosSemanticAccountResolver(
        requester=lambda *args, **kwargs: pytest.fail("HTTP must not be called")
    )
    with pytest.raises(CoaSemanticResolutionError) as token_error:
        resolver.resolve(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            company_id=COMPANY_ID,
            semantic_key="MB-COA-CASH",
            effective_on=date(2026, 11, 11),
            currency="KRW",
        )
    assert token_error.value.error_code == "ae.coa_semantic.service_token_unavailable"

    malformed = HttpEosSemanticAccountResolver(
        service_token="token",
        requester=lambda *args, **kwargs: httpx.Response(
            200,
            content=b"not-json",
            request=httpx.Request("GET", "http://eos.test"),
        ),
    )
    with pytest.raises(CoaSemanticResolutionError) as response_error:
        malformed.resolve(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            company_id=COMPANY_ID,
            semantic_key="MB-COA-CASH",
            effective_on=date(2026, 11, 11),
            currency="KRW",
        )
    assert response_error.value.error_code == "ae.coa_semantic.response_invalid"

    list_response = _response(200, [])
    with pytest.raises(CoaSemanticResolutionError):
        coa_semantic_resolution._response_object(list_response)
    with pytest.raises(CoaSemanticResolutionError) as direct_invalid:
        coa_semantic_resolution._resolution([], expected={})
    assert str(direct_invalid.value) == "EOS semantic Account response is invalid."
