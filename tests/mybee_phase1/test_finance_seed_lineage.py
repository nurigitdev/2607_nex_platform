from __future__ import annotations

import copy
import json
from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import jsonschema
import pytest
import yaml
from mybee_ax.integrations.finance_inputs import (
    EosFinanceInputClient,
    FinanceInputApiError,
    FinanceInputBundleError,
    HttpEosFinanceInputTransport,
    load_approved_finance_input_bundle,
    validate_approved_fx_source_policy,
)
from nex_runtime.semantic_hashes import (
    eos_fx_policy_hash_ref,
    semantic_sha256_hash_ref,
)

ROOT = Path(__file__).resolve().parents[2]
FX_CONFIG = ROOT / "domains/mybee/config/fx"
FX_POLICY = FX_CONFIG / "approved_rate_source_policy.json"
FX_SCHEMA = FX_CONFIG / "approved_rate_source_policy.schema.json"
OPENAPI = ROOT / "contracts/openapi/nex-eos.openapi.yaml"

TENANT_ID = "tenant-mybee"
SUBJECT_ID = "finance-owner"
COMPANY_ID = "81000000-0000-4000-8000-000000000001"
POLICY_ID = "81000000-0000-4000-8000-000000000002"
RELEASE_ID = "81000000-0000-4000-8000-000000000003"
OPERATION_ID = "81000000-0000-4000-8000-000000000004"
PROOF_HASH = "sha256:" + "a" * 64


def _policy() -> dict:
    return json.loads(FX_POLICY.read_text(encoding="utf-8"))


def _bundle():
    return load_approved_finance_input_bundle(ROOT)


def test_mb1_03_fx_source_policy_matches_schema_and_immutable_hash() -> None:
    policy = _policy()

    jsonschema.Draft202012Validator(
        json.loads(FX_SCHEMA.read_text(encoding="utf-8"))
    ).validate(policy)
    validate_approved_fx_source_policy(policy)
    expected_hash = semantic_sha256_hash_ref(
        {key: value for key, value in policy.items() if key != "policy_contract_hash"}
    )
    assert policy["policy_contract_hash"] == expected_hash


def test_mb1_03_bundle_preserves_approved_coa_and_excludes_rate_values() -> None:
    bundle = _bundle()

    assert bundle.coa_admission.candidate_report.total_nodes == 166
    assert bundle.coa_admission.candidate_report.findings == ()
    assert bundle.coa_manifest["runtime_seed_allowed"] is True
    assert bundle.coa_manifest["automatic_publication_allowed"] is False
    assert bundle.coa_manifest["published"] is False
    assert bundle.coa_manifest["company_adoption_allowed"] is False
    assert bundle.fx_policy["source"] == {
        "provider_id": "SMBS_TODAY_EXRATE",
        "source_uri": "http://www.smbs.co.kr/ExRate/TodayExRate.jsp",
        "acquisition_mode": "MANUAL_APPROVED_IMPORT",
        "source_timezone": "Asia/Seoul",
        "calendar_ref": "KR_BUSINESS_DAY_V1",
        "automatic_fetch_enabled": False,
        "rate_values_included": False,
        "legal_rate_claim": "NONE",
    }
    assert bundle.bundle_hash.startswith("sha256:")


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        (lambda value: value.update({"unexpected": True}), "FX_POLICY_FIELDS_INVALID"),
        (
            lambda value: value.update({"schema_version": "future"}),
            "FX_POLICY_IDENTITY_INVALID",
        ),
        (
            lambda value: value["source"].update({"rate_values_included": True}),
            "FX_SOURCE_BOUNDARY_INVALID",
        ),
        (
            lambda value: value.update({"policy_contract_hash": "sha256:" + "0" * 64}),
            "FX_POLICY_HASH_MISMATCH",
        ),
    ),
)
def test_mb1_03_fx_policy_drift_fails_closed(mutation, code: str) -> None:
    value = copy.deepcopy(_policy())
    mutation(value)

    with pytest.raises(FinanceInputBundleError) as raised:
        validate_approved_fx_source_policy(value)
    assert raised.value.code == code


def test_mb1_03_coa_publication_request_uses_only_admitted_lineage() -> None:
    request = _bundle().coa_publication_request(
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        definition_release_id=RELEASE_ID,
        business_operation_id=OPERATION_ID,
        idempotency_key="mb1-03-coa-v1",
    )

    assert request.path == f"/internal/v2/finance/coa/releases/{RELEASE_ID}/publish"
    assert request.payload == {
        "business_operation_id": OPERATION_ID,
        "idempotency_key": "mb1-03-coa-v1",
        "source_reference": (
            "domains/mybee/config/account_catalog/approved_standard_chart.v1.json"
        ),
        "source_hash": (
            "sha256:7782f96ea7445c6b0c9d82bc4d3c431175e4f32c22a968c1430aea55f736e61c"
        ),
        "approved_proof_ref": (
            "sha256:f16c845b752b8c6a810bc1c75f069c211030e3530996e87bb11f08fb99541d6e"
        ),
        "content_hash": (
            "sha256:e988aaf0f5eccb9578591d8e4f678cb8d751019583389346178a427771be7c13"
        ),
    }


def test_mb1_03_fx_request_matches_shared_eos_policy_hash_contract() -> None:
    request = _bundle().fx_policy_request(
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        company_id=COMPANY_ID,
        policy_id=POLICY_ID,
        effective_from=date(2026, 11, 11),
        approved_by=SUBJECT_ID,
        approval_proof_hash=PROOF_HASH,
    )

    assert request.path == "/internal/v2/finance/fx-rate-policies/approved"
    assert request.payload["source_provider_id"] == "SMBS_TODAY_EXRATE"
    assert request.payload["publication_selector"] == "FINAL"
    semantics = {"tenant_id": TENANT_ID, **dict(request.payload)}
    policy_hash = semantics.pop("policy_hash")
    assert policy_hash == eos_fx_policy_hash_ref(semantics)


@pytest.mark.parametrize(
    ("overrides", "code"),
    (
        ({"base_currency": "EUR"}, "FX_PAIR_NOT_ADMITTED"),
        ({"effective_to": date(2026, 11, 11)}, "FX_EFFECTIVE_PERIOD_INVALID"),
        ({"version": True}, "FX_VERSION_INVALID"),
        ({"approval_proof_hash": "bad"}, "APPROVAL_PROOF_HASH_INVALID"),
        ({"company_id": "bad"}, "COMPANY_ID_INVALID"),
    ),
)
def test_mb1_03_fx_runtime_binding_rejections(overrides: dict, code: str) -> None:
    values = {
        "tenant_id": TENANT_ID,
        "subject_id": SUBJECT_ID,
        "company_id": COMPANY_ID,
        "policy_id": POLICY_ID,
        "effective_from": date(2026, 11, 11),
        "approved_by": SUBJECT_ID,
        "approval_proof_hash": PROOF_HASH,
    }
    values.update(overrides)

    with pytest.raises(FinanceInputBundleError) as raised:
        _bundle().fx_policy_request(**values)
    assert raised.value.code == code


def test_mb1_03_static_openapi_exposes_provider_consumer_contracts() -> None:
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    expected = {
        "/internal/v2/finance/coa/releases/{definition_release_id}/publish": (
            "FINANCE.COA.PUBLISH_APPROVED"
        ),
        "/internal/v2/finance/fx-rate-policies/approved": (
            "FINANCE.FX_POLICY.CREATE_APPROVED"
        ),
        "/internal/v2/finance/fx-rate-batches": "FINANCE.FX_RATE.IMPORT",
        "/internal/v2/finance/fx-rates:resolve": "FINANCE.FX_RATE.RESOLVE",
        "/internal/v2/finance/fx-rate-snapshots": "FINANCE.FX_RATE.HISTORY",
    }
    for path, operation in expected.items():
        method = "get" if operation.endswith(("RESOLVE", "HISTORY")) else "post"
        assert spec["paths"][path][method]["operationId"] == operation
    assert (
        spec["paths"]["/internal/v2/finance/fx-rate-policies/approved"]["post"][
            "x-nex-business-scope"
        ]
        == "finance:fx:publish"
    )


class RecordingTransport:
    def __init__(self) -> None:
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return {"accepted": True, "path": request.path}


def test_mb1_03_client_delegates_to_transport_without_database_access() -> None:
    transport = RecordingTransport()
    result = EosFinanceInputClient(transport).create_fx_policy(
        _bundle(),
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        company_id=COMPANY_ID,
        policy_id=POLICY_ID,
        effective_from=date(2026, 11, 11),
        approved_by=SUBJECT_ID,
        approval_proof_hash=PROOF_HASH,
    )

    assert result == {
        "accepted": True,
        "path": "/internal/v2/finance/fx-rate-policies/approved",
    }
    assert len(transport.requests) == 1


def test_mb1_03_client_delegates_coa_publication_to_transport() -> None:
    transport = RecordingTransport()
    result = EosFinanceInputClient(transport).publish_coa(
        _bundle(),
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        definition_release_id=RELEASE_ID,
        business_operation_id=OPERATION_ID,
        idempotency_key="coa",
    )

    assert result["accepted"] is True
    assert transport.requests[0].path.endswith(f"/{RELEASE_ID}/publish")


def test_mb1_03_missing_coa_evidence_is_reported_as_bundle_failure(
    tmp_path: Path,
) -> None:
    with pytest.raises(FinanceInputBundleError) as raised:
        load_approved_finance_input_bundle(tmp_path)
    assert raised.value.code == "COA_INPUT_NOT_ADMITTED"


def test_mb1_03_non_object_fx_source_is_rejected() -> None:
    value = _policy()
    value["source"] = []

    with pytest.raises(FinanceInputBundleError) as raised:
        validate_approved_fx_source_policy(value)
    assert raised.value.code == "FX_SOURCE_INVALID"


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self.body


def test_mb1_03_http_transport_sends_trust_and_owner_headers(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(b'{"created":true}')

    monkeypatch.setattr("mybee_ax.integrations.finance_inputs.urlopen", fake_urlopen)
    request = _bundle().coa_publication_request(
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        definition_release_id=RELEASE_ID,
        business_operation_id=OPERATION_ID,
        idempotency_key="coa",
    )
    result = HttpEosFinanceInputTransport(
        base_url="http://eos.internal:8107",
        service_token="signed-token",
    ).send(request)

    assert result == {"created": True}
    assert captured["request"].get_header("Authorization") == "Bearer signed-token"
    assert captured["request"].get_header("X-nex-tenant-id") == TENANT_ID
    assert captured["request"].get_header("X-nex-subject-id") == SUBJECT_ID
    assert captured["timeout"] == 15.0


@pytest.mark.parametrize("body", (b"not-json", b"[]"))
def test_mb1_03_http_transport_rejects_malformed_success_response(
    monkeypatch, body: bytes
) -> None:
    monkeypatch.setattr(
        "mybee_ax.integrations.finance_inputs.urlopen",
        lambda *_args, **_kwargs: _Response(body),
    )
    request = _bundle().coa_publication_request(
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        definition_release_id=RELEASE_ID,
        business_operation_id=OPERATION_ID,
        idempotency_key="coa",
    )

    with pytest.raises(FinanceInputApiError) as raised:
        HttpEosFinanceInputTransport(
            base_url="http://eos.internal:8107", service_token="token"
        ).send(request)
    assert raised.value.code == "EOS_FINANCE_INPUT_RESPONSE_INVALID"
    assert raised.value.status_code == 502


@pytest.mark.parametrize(
    ("error", "code", "status", "retryable"),
    (
        (
            HTTPError(
                "http://eos",
                409,
                "conflict",
                {},
                BytesIO(b'{"error_code":"EOS_POLICY_CONFLICT","retryable":false}'),
            ),
            "EOS_POLICY_CONFLICT",
            409,
            False,
        ),
        (URLError("offline"), "EOS_FINANCE_INPUT_UNAVAILABLE", 503, True),
    ),
)
def test_mb1_03_http_transport_redacts_failures(
    monkeypatch, error, code: str, status: int, retryable: bool
) -> None:
    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr("mybee_ax.integrations.finance_inputs.urlopen", fail)
    transport = HttpEosFinanceInputTransport(
        base_url="http://eos.internal:8107",
        service_token="signed-token",
    )
    request = _bundle().coa_publication_request(
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        definition_release_id=RELEASE_ID,
        business_operation_id=OPERATION_ID,
        idempotency_key="coa",
    )

    with pytest.raises(FinanceInputApiError) as raised:
        transport.send(request)
    assert raised.value.code == code
    assert raised.value.status_code == status
    assert raised.value.retryable is retryable
    assert "signed-token" not in str(raised.value)


@pytest.mark.parametrize("body", (b"not-json", b"[]"))
def test_mb1_03_http_error_without_problem_object_uses_safe_defaults(
    monkeypatch, body: bytes
) -> None:
    def fail(*_args, **_kwargs):
        raise HTTPError("http://eos", 503, "failed", {}, BytesIO(body))

    monkeypatch.setattr("mybee_ax.integrations.finance_inputs.urlopen", fail)
    request = _bundle().coa_publication_request(
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        definition_release_id=RELEASE_ID,
        business_operation_id=OPERATION_ID,
        idempotency_key="coa",
    )

    with pytest.raises(FinanceInputApiError) as raised:
        HttpEosFinanceInputTransport(
            base_url="http://eos.internal:8107", service_token="token"
        ).send(request)
    assert raised.value.code == "EOS_FINANCE_INPUT_REJECTED"
    assert raised.value.retryable is True


@pytest.mark.parametrize(
    ("builder", "code"),
    (
        (
            lambda bundle: bundle.coa_publication_request(
                tenant_id="bad tenant",
                subject_id=SUBJECT_ID,
                definition_release_id=RELEASE_ID,
                business_operation_id=OPERATION_ID,
                idempotency_key="coa",
            ),
            "TENANT_ID_INVALID",
        ),
        (
            lambda bundle: bundle.coa_publication_request(
                tenant_id=TENANT_ID,
                subject_id=SUBJECT_ID,
                definition_release_id=RELEASE_ID,
                business_operation_id=OPERATION_ID,
                idempotency_key=" ",
            ),
            "IDEMPOTENCY_KEY_INVALID",
        ),
        (
            lambda bundle: bundle.fx_policy_request(
                tenant_id=TENANT_ID,
                subject_id="bad subject",
                company_id=COMPANY_ID,
                policy_id=POLICY_ID,
                effective_from=date(2026, 11, 11),
                approved_by=SUBJECT_ID,
                approval_proof_hash=PROOF_HASH,
            ),
            "SUBJECT_ID_INVALID",
        ),
        (
            lambda bundle: bundle.fx_policy_request(
                tenant_id=TENANT_ID,
                subject_id=SUBJECT_ID,
                company_id=COMPANY_ID,
                policy_id=POLICY_ID,
                effective_from="2026-11-11",
                approved_by=SUBJECT_ID,
                approval_proof_hash=PROOF_HASH,
            ),
            "EFFECTIVE_FROM_INVALID",
        ),
        (
            lambda bundle: bundle.fx_policy_request(
                tenant_id=TENANT_ID,
                subject_id=SUBJECT_ID,
                company_id=COMPANY_ID,
                policy_id=POLICY_ID,
                effective_from=date(2026, 11, 11),
                approved_by=SUBJECT_ID,
                approval_proof_hash=PROOF_HASH,
                quote_currency="krw",
            ),
            "QUOTE_CURRENCY_INVALID",
        ),
    ),
)
def test_mb1_03_common_runtime_binding_rejections(builder, code: str) -> None:
    with pytest.raises(FinanceInputBundleError) as raised:
        builder(_bundle())
    assert raised.value.code == code


@pytest.mark.parametrize(
    ("arguments", "code"),
    (
        (
            {"base_url": "file:///tmp/eos", "service_token": "token"},
            "EOS_BASE_URL_INVALID",
        ),
        ({"base_url": "http://eos", "service_token": " "}, "EOS_SERVICE_TOKEN_MISSING"),
        (
            {"base_url": "http://eos", "service_token": "token", "timeout_seconds": 0},
            "EOS_TIMEOUT_INVALID",
        ),
    ),
)
def test_mb1_03_http_transport_configuration_fails_closed(
    arguments: dict, code: str
) -> None:
    with pytest.raises(FinanceInputBundleError) as raised:
        HttpEosFinanceInputTransport(**arguments)
    assert raised.value.code == code
