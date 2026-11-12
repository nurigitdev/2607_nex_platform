from __future__ import annotations

import os
import uuid
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_eos import finance_v2_api
from nex_eos.account_catalog import (
    AccountCatalogReleaseInput,
    CompanyAccountPolicyInput,
    PostingRuleReleaseInput,
    SqlAlchemyEosAccountCatalogRepository,
)
from nex_eos.accounting_periods import (
    AccountingPeriodInput,
    SqlAlchemyEosAccountingPeriodRepository,
)
from nex_eos.accounting_rules import (
    AccountingRuleError,
    currency_minor_units,
    functionalize_candidate_lines,
)
from nex_eos.accounts import AccountInput
from nex_eos.candidate_validation import (
    EosCandidateValidationError,
    EosCandidateValidationService,
)
from nex_eos.finance_v2_api import register_finance_v2_routes
from nex_eos.fx_rates import (
    FxRatePolicyInput,
    FxRateSnapshotInput,
    SqlAlchemyEosFxRateRepository,
    fx_policy_hash,
)
from nex_eos.legal_entities import LegalEntityInput, SqlAlchemyEosLegalEntityRepository
from nex_eos.persistence import build_eos_database_runtime
from nex_eos.voucher_candidates import EosVoucherCandidateError
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import make_url

TENANT = "VO00"
CANDIDATE_ID = "33000000-0000-4000-8000-000000000001"
REVISION_ID = "33000000-0000-4000-8000-000000000002"
COMPANY_ID = "33000000-0000-4000-8000-000000000003"
PROJECT_ID = "33000000-0000-4000-8000-000000000004"
PERIOD_ID = "33000000-0000-4000-8000-000000000005"
DOCUMENT_ID = "33000000-0000-4000-8000-00000000000a"
DEBIT_ID = "33000000-0000-4000-8000-000000000006"
CREDIT_ID = "33000000-0000-4000-8000-000000000007"
RULE_ID = "33000000-0000-4000-8000-000000000008"
RELEASE_ID = "33000000-0000-4000-8000-000000000009"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
NOW = datetime(2026, 11, 12, 1, 0, tzinfo=UTC)
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S3_02_POSTGRES_SMOKE") == "1"


class CandidateSource:
    def __init__(self, candidate=None) -> None:
        self.candidate = _candidate() if candidate is None else candidate

    def get(self, *, tenant_id: str, candidate_id: str):
        assert tenant_id == TENANT
        assert candidate_id == CANDIDATE_ID
        return deepcopy(self.candidate)


class CompanySource:
    def __init__(self) -> None:
        self.company = {"company_id": COMPANY_ID, "functional_currency": "KRW"}

    def get_legal_entity(self, **kwargs):
        assert kwargs["active_only"] is True
        return deepcopy(self.company)


class PeriodSource:
    def __init__(self) -> None:
        self.period = {"period_id": PERIOD_ID, "state": "OPEN"}

    def find_period_for_date(self, **_kwargs):
        return deepcopy(self.period)


class CatalogSource:
    catalog = None

    def __init__(self) -> None:
        self.catalog = _catalog()

    def get_effective_catalog(self, **_kwargs):
        return deepcopy(self.catalog)


class FxSource:
    def __init__(self) -> None:
        self.calls = []
        self.rate = {
            "normalized_rate": "1350.25",
            "desired_rate_date": "2026-11-12",
            "selected_rate_date": "2026-11-11",
            "staleness_business_days": 1,
            "snapshot_hash": HASH_B,
            "policy_hash": HASH_C,
        }

    def resolve_rate(self, **kwargs):
        self.calls.append(kwargs)
        return deepcopy(self.rate)


def _candidate(*, currency: str = "KRW") -> dict:
    return {
        "tenant_id": TENANT,
        "candidate_id": CANDIDATE_ID,
        "company_id": COMPANY_ID,
        "project_id": PROJECT_ID,
        "project_code": "VO00D260001",
        "state": "DRAFT",
        "version": 1,
        "current_revision_no": 1,
        "document_envelope_id": DOCUMENT_ID,
        "preparer_subject_id": "employee:preparer",
        "transaction_currency": currency,
        "recognition_date": date(2026, 11, 12),
        "revision": {
            "revision_id": REVISION_ID,
            "revision_no": 1,
            "candidate_hash": HASH_A,
            "approved_document_hash": HASH_B,
        },
        "lines": [
            {
                "line_no": 1,
                "account_id": DEBIT_ID,
                "debit_original": Decimal("100.0000"),
                "credit_original": Decimal("0.0000"),
            },
            {
                "line_no": 2,
                "account_id": CREDIT_ID,
                "debit_original": Decimal("0.0000"),
                "credit_original": Decimal("100.0000"),
            },
        ],
    }


def _catalog() -> dict:
    accounts = []
    for index, account_id in enumerate((DEBIT_ID, CREDIT_ID), start=1):
        accounts.append(
            {
                "policy_id": f"33000000-0000-4000-8000-{index:012d}",
                "account_id": account_id,
                "catalog_release_id": RELEASE_ID,
                "posting_rule_id": RULE_ID,
                "is_postable_leaf": True,
                "allowed_currencies": ["KRW", "USD"],
                "rule_revision": 1,
                "approved_proof_ref": HASH_C,
            }
        )
    return {
        "posting_rule": {"posting_rule_id": RULE_ID, "rule_hash": HASH_B},
        "accounts": accounts,
    }


def _request(**changes) -> dict:
    return {
        "schema_version": "eos_voucher_candidate_validate.v1",
        "tenant_id": TENANT,
        "expected_revision_no": 1,
        "expected_candidate_hash": HASH_A,
        "as_of": NOW.isoformat(),
        **changes,
    }


def _service(*, candidate=None):
    fx = FxSource()
    service = EosCandidateValidationService(
        candidates=CandidateSource(candidate),
        legal_entities=CompanySource(),
        periods=PeriodSource(),
        account_catalog=CatalogSource(),
        fx_rates=fx,
    )
    return service, fx


def test_accounting_rules_balance_rounding_and_currency_admission() -> None:
    result = functionalize_candidate_lines(
        _candidate()["lines"],
        transaction_currency="KRW",
        functional_currency="KRW",
        normalized_rate="1",
    )
    assert result.debit_functional == result.credit_functional == "100"
    assert result.functional_scale == 0
    assert result.rule_profile_hash.startswith("sha256:")
    assert currency_minor_units("usd") == 2
    assert currency_minor_units("JPY") == 0
    with pytest.raises(AccountingRuleError, match="not admitted"):
        currency_minor_units("ZZZ")


@pytest.mark.parametrize(
    ("lines", "rate", "code"),
    [
        ([], "1", "MYBEE_CANDIDATE_LINES_REQUIRED"),
        (
            [{"line_no": 2, "debit_original": "1", "credit_original": "0"}],
            "1",
            "MYBEE_CANDIDATE_LINE_ORDER_INVALID",
        ),
        (
            [{"line_no": 1, "debit_original": "1", "credit_original": "1"}],
            "1",
            "MYBEE_CANDIDATE_LINE_SIDE_INVALID",
        ),
        (
            [{"line_no": 1, "debit_original": "x", "credit_original": "0"}],
            "1",
            "MYBEE_AMOUNT_INVALID",
        ),
        (
            [{"line_no": True, "debit_original": "1", "credit_original": "0"}],
            "1",
            "MYBEE_CANDIDATE_LINE_INVALID",
        ),
        (
            [{"line_no": object(), "debit_original": "1", "credit_original": "0"}],
            "1",
            "MYBEE_CANDIDATE_LINE_INVALID",
        ),
        (
            [{"line_no": 1, "debit_original": "-1", "credit_original": "0"}],
            "1",
            "MYBEE_AMOUNT_INVALID",
        ),
        (
            [{"line_no": 1, "debit_original": "1", "credit_original": "0"}],
            "0",
            "MYBEE_FX_RATE_INVALID",
        ),
        (
            [
                {"line_no": 1, "debit_original": "1", "credit_original": "0"},
                {"line_no": 2, "debit_original": "0", "credit_original": "2"},
            ],
            "1",
            "MYBEE_ORIGINAL_BALANCE_INVALID",
        ),
        (
            [
                {"line_no": 1, "debit_original": ".5", "credit_original": "0"},
                {"line_no": 2, "debit_original": ".5", "credit_original": "0"},
                {"line_no": 3, "debit_original": "0", "credit_original": "1"},
            ],
            "1",
            "MYBEE_FUNCTIONAL_BALANCE_INVALID",
        ),
    ],
)
def test_accounting_rules_reject_invalid_candidates(lines, rate, code) -> None:
    with pytest.raises(AccountingRuleError) as captured:
        functionalize_candidate_lines(
            lines,
            transaction_currency="USD",
            functional_currency="KRW",
            normalized_rate=rate,
        )
    assert captured.value.error_code == code


def test_accounting_rules_reject_invalid_currency_and_same_currency_rate() -> None:
    with pytest.raises(AccountingRuleError) as currency:
        functionalize_candidate_lines(
            _candidate()["lines"],
            transaction_currency="K1",
            functional_currency="KRW",
            normalized_rate="1",
        )
    assert currency.value.error_code == "MYBEE_CURRENCY_INVALID"
    with pytest.raises(AccountingRuleError) as rate:
        functionalize_candidate_lines(
            _candidate()["lines"],
            transaction_currency="KRW",
            functional_currency="KRW",
            normalized_rate="1.1",
        )
    assert rate.value.error_code == "MYBEE_SAME_CURRENCY_RATE_INVALID"


def test_candidate_validation_same_currency_is_deterministic_and_side_effect_free() -> (
    None
):
    service, fx = _service()
    first = service.validate(CANDIDATE_ID, _request())
    second = service.validate(CANDIDATE_ID, _request())

    assert first == second
    assert first["status"] == "PASS"
    assert first["totals"]["debit_functional"] == "100"
    assert first["fx_evidence"]["mode"] == "SAME_CURRENCY"
    assert first["project_ref"]["code"] == "VO00D260001"
    assert fx.calls == []


def test_candidate_validation_uses_approved_foreign_currency_snapshot() -> None:
    service, fx = _service(candidate=_candidate(currency="USD"))
    result = service.validate(CANDIDATE_ID, _request())

    assert result["fx_evidence"]["mode"] == "APPROVED_SNAPSHOT"
    assert result["fx_evidence"]["selected_rate_date"] == "2026-11-11"
    assert result["totals"]["debit_functional"] == "135025"
    assert fx.calls[0]["purpose"] == "TRANSACTION_SPOT"
    assert fx.calls[0]["as_of"] == NOW


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda sources: setattr(sources[0], "candidate", None),
            "EOS_VOUCHER_CANDIDATE_NOT_FOUND",
        ),
        (
            lambda sources: sources[0].candidate.update(state="VALIDATED"),
            "EOS_CANDIDATE_STATE_NOT_VALIDATABLE",
        ),
        (
            lambda sources: sources[1].company.clear(),
            "EOS_CANDIDATE_COMPANY_UNAVAILABLE",
        ),
        (
            lambda sources: sources[2].period.update(state="CLOSED"),
            "EOS_CANDIDATE_PERIOD_NOT_OPEN",
        ),
        (
            lambda sources: setattr(sources[3], "catalog", None),
            "EOS_CANDIDATE_ACCOUNT_CATALOG_UNAVAILABLE",
        ),
        (
            lambda sources: sources[3].catalog["accounts"].pop(),
            "EOS_CANDIDATE_ACCOUNT_UNAVAILABLE",
        ),
        (
            lambda sources: (
                sources[3].catalog["accounts"][0].update(is_postable_leaf=False)
            ),
            "EOS_CANDIDATE_ACCOUNT_NOT_POSTABLE",
        ),
        (
            lambda sources: (
                sources[3].catalog["accounts"][0].update(allowed_currencies=["KRW"])
            ),
            "EOS_CANDIDATE_ACCOUNT_CURRENCY_DENIED",
        ),
    ],
)
def test_candidate_validation_fail_closed_authoritative_boundaries(
    mutate, code
) -> None:
    candidate = CandidateSource(_candidate(currency="USD"))
    company = CompanySource()
    period = PeriodSource()
    catalog = CatalogSource()
    sources = [candidate, company, period, catalog]
    mutate(sources)
    service = EosCandidateValidationService(
        candidates=candidate,
        legal_entities=company,
        periods=period,
        account_catalog=catalog,
        fx_rates=FxSource(),
    )
    with pytest.raises(EosCandidateValidationError) as captured:
        service.validate(CANDIDATE_ID, _request())
    assert captured.value.error_code == code


def test_candidate_validation_rejects_revision_drift_and_malformed_requests() -> None:
    service, _fx = _service()
    with pytest.raises(EosCandidateValidationError) as conflict:
        service.validate(CANDIDATE_ID, _request(expected_revision_no=2))
    assert conflict.value.error_code == "EOS_CANDIDATE_REVISION_CONFLICT"
    assert conflict.value.status_code == 409

    invalid_requests = [
        _request(schema_version="wrong"),
        _request(tenant_id=""),
        _request(expected_revision_no=True),
        _request(expected_candidate_hash="bad"),
        _request(as_of="2026-11-12T01:00:00"),
        _request(as_of="not-a-date-time"),
        {**_request(), "unexpected": True},
    ]
    for payload in invalid_requests:
        with pytest.raises(EosCandidateValidationError) as invalid:
            service.validate(CANDIDATE_ID, payload)
        assert invalid.value.status_code == 422
    with pytest.raises(EosCandidateValidationError, match="candidate_id"):
        service.validate("not-a-uuid", _request())


def test_candidate_validation_maps_rule_source_and_stored_date_failures() -> None:
    unbalanced = _candidate()
    unbalanced["lines"][1]["credit_original"] = Decimal(99)
    service, _fx = _service(candidate=unbalanced)
    with pytest.raises(EosCandidateValidationError) as rule:
        service.validate(CANDIDATE_ID, _request())
    assert rule.value.error_code == "MYBEE_ORIGINAL_BALANCE_INVALID"

    class BrokenCandidates:
        def get(self, **_kwargs):
            raise EosVoucherCandidateError(
                "EOS_CANDIDATE_PERSISTENCE_UNAVAILABLE",
                "persistence unavailable",
                status_code=503,
                retryable=True,
            )

    broken = EosCandidateValidationService(
        candidates=BrokenCandidates(),
        legal_entities=CompanySource(),
        periods=PeriodSource(),
        account_catalog=CatalogSource(),
        fx_rates=FxSource(),
    )
    with pytest.raises(EosCandidateValidationError) as source:
        broken.validate(CANDIDATE_ID, _request())
    assert source.value.status_code == 503
    assert source.value.retryable is True

    for stored in (datetime(2026, 11, 12, tzinfo=UTC), "2026-11-12"):
        candidate = _candidate()
        candidate["recognition_date"] = stored
        result, _fx = _service(candidate=candidate)
        assert result.validate(CANDIDATE_ID, _request())["status"] == "PASS"
    invalid_date = _candidate()
    invalid_date["recognition_date"] = "not-a-date"
    invalid, _fx = _service(candidate=invalid_date)
    with pytest.raises(EosCandidateValidationError) as date_error:
        invalid.validate(CANDIDATE_ID, _request())
    assert date_error.value.status_code == 422


def test_candidate_validation_api_and_openapi_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        finance_v2_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(
            subject="nex-ae-api", audience="nex-eos", scopes=("service:call",)
        ),
    )
    service, _fx = _service()
    app = FastAPI()
    register_finance_v2_routes(app)
    app.state.eos_candidate_validation_service = service
    client = TestClient(app)

    passed = client.post(
        f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}/validation",
        json=_request(),
        headers={"Authorization": "Bearer service-token"},
    )
    assert passed.status_code == 200
    assert passed.json()["validation_hash"].startswith("sha256:")

    del app.state.eos_candidate_validation_service
    unavailable = client.post(
        f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}/validation",
        json=_request(),
        headers={"Authorization": "Bearer service-token"},
    )
    assert unavailable.status_code == 503

    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    route = spec["paths"][
        "/internal/v2/finance/voucher-candidates/{candidate_id}/validation"
    ]["post"]
    assert route["operationId"] == "FINANCE.VOUCHER_CANDIDATE.VALIDATE"
    assert route["x-nex-side-effect-free"] is True


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W30-S3-02 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_authoritative_validation_and_zero_residue() -> None:
    schema_name = f"mybee_w30s302_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_eos_test", "nex_eos_user")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    runtime = None
    try:
        migration = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2534_eos_voucher_candidate_v2" in migration.applied
        runtime = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        legal_entities = SqlAlchemyEosLegalEntityRepository(runtime.session_factory)
        legal_entities.create_legal_entity(
            LegalEntityInput(
                TENANT,
                COMPANY_ID,
                "NURI-S302",
                "NURI S3-02",
                "KRW",
                "KRW",
                "Asia/Seoul",
                date(2026, 1, 1),
            )
        )
        periods = SqlAlchemyEosAccountingPeriodRepository(runtime.session_factory)
        periods.create_open_period(
            AccountingPeriodInput(
                TENANT,
                COMPANY_ID,
                PERIOD_ID,
                2026,
                11,
                date(2026, 11, 1),
                date(2026, 11, 30),
            )
        )
        catalog = SqlAlchemyEosAccountCatalogRepository(runtime.session_factory)
        catalog.create_catalog_release(
            AccountCatalogReleaseInput(
                TENANT,
                RELEASE_ID,
                "urn:mybee:s3-02:coa",
                "2026.11",
                HASH_A,
                date(2026, 1, 1),
                "accounting-controller",
                HASH_B,
            )
        )
        catalog.create_posting_rule_release(
            PostingRuleReleaseInput(
                TENANT,
                RULE_ID,
                COMPANY_ID,
                RELEASE_ID,
                "KIFRS-S302",
                1,
                HASH_B,
                date(2026, 1, 1),
                HASH_C,
                HASH_A,
            )
        )
        for index, account_id in enumerate((DEBIT_ID, CREDIT_ID), start=1):
            catalog.create_approved_account(
                account=AccountInput(
                    TENANT,
                    account_id,
                    f"S302-{index}",
                    f"S3-02 Account {index}",
                    "EXPENSE" if index == 1 else "ASSET",
                    "GENERAL",
                    date(2026, 1, 1),
                ),
                policy=CompanyAccountPolicyInput(
                    TENANT,
                    f"33000000-0000-4000-8000-{100 + index:012d}",
                    COMPANY_ID,
                    account_id,
                    RELEASE_ID,
                    RULE_ID,
                    True,
                    False,
                    "PL-S302" if index == 1 else "BS-S302",
                    ("KRW", "JPY"),
                    date(2026, 1, 1),
                    HASH_C,
                ),
            )
        fx_rates = SqlAlchemyEosFxRateRepository(runtime.session_factory)
        fx_policy_id = "33000000-0000-4000-8000-000000000110"
        policy_semantics = {
            "tenant_id": TENANT,
            "company_id": COMPANY_ID,
            "policy_id": fx_policy_id,
            "version": 1,
            "purpose": "TRANSACTION_SPOT",
            "base_currency": "JPY",
            "quote_currency": "KRW",
            "rate_kind": "MARKET_BASE",
            "source_provider_id": "SMBS_TODAY_EXRATE",
            "publication_selector": "FINAL",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "allow_previous_business_day": True,
            "max_staleness_business_days": 1,
            "rounding_mode": "HALF_EVEN",
            "rate_decimal_scale": 6,
            "approved_by": "accounting-controller",
            "approval_proof_hash": HASH_C,
        }
        fx_rates.create_approved_policy(
            FxRatePolicyInput(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                policy_id=fx_policy_id,
                version=1,
                purpose="TRANSACTION_SPOT",
                base_currency="JPY",
                quote_currency="KRW",
                rate_kind="MARKET_BASE",
                source_provider_id="SMBS_TODAY_EXRATE",
                publication_selector="FINAL",
                effective_from=date(2026, 1, 1),
                effective_to=None,
                allow_previous_business_day=True,
                max_staleness_business_days=1,
                rounding_mode="HALF_EVEN",
                rate_decimal_scale=6,
                approved_by="accounting-controller",
                approval_proof_hash=HASH_C,
                policy_hash=fx_policy_hash(policy_semantics),
            )
        )
        fx_rates.import_approved_snapshot(
            FxRateSnapshotInput(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                rate_snapshot_id="33000000-0000-4000-8000-000000000111",
                rate_policy_id=fx_policy_id,
                rate_policy_version=1,
                source_provider_id="SMBS_TODAY_EXRATE",
                base_currency="JPY",
                quote_currency="KRW",
                quote_unit=Decimal(100),
                published_rate=Decimal("960.50"),
                desired_rate_date=date(2026, 11, 12),
                rate_date=date(2026, 11, 11),
                rate_as_of=datetime(2026, 11, 11, 10, 0, tzinfo=UTC),
                published_at=datetime(2026, 11, 11, 9, 0, tzinfo=UTC),
                publication_issue="FINAL",
                is_final=True,
                source_record_id="smbs:2026-11-11:jpy:final",
                source_uri="http://www.smbs.co.kr/ExRate/TodayExRate.jsp",
                source_sha256="sha256:" + "1" * 64,
                calendar_ref="KR_BUSINESS_DAY_V1",
                source_timezone="Asia/Seoul",
                provenance={"acquisition_mode": "S3_02_PROTECTED_SMOKE"},
            )
        )
        service = EosCandidateValidationService(
            candidates=CandidateSource(_candidate(currency="JPY")),
            legal_entities=legal_entities,
            periods=periods,
            account_catalog=catalog,
            fx_rates=fx_rates,
        )
        passed = service.validate(CANDIDATE_ID, _request())
        assert passed["status"] == "PASS"
        assert passed["fx_evidence"]["mode"] == "APPROVED_SNAPSHOT"
        assert passed["fx_evidence"]["normalized_rate"] == "9.605"
        assert passed["totals"]["debit_functional"] == "960"

        periods.advance_close(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            period_id=PERIOD_ID,
            expected_version=1,
        )
        with pytest.raises(EosCandidateValidationError) as closed:
            service.validate(CANDIDATE_ID, _request())
        assert closed.value.error_code == "EOS_CANDIDATE_PERIOD_NOT_OPEN"
    finally:
        if runtime is not None:
            runtime.dispose()
        with (
            psycopg.connect(psycopg_url, autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            cursor.execute(
                "SELECT count(*) FROM information_schema.schemata WHERE schema_name=%s",
                (schema_name,),
            )
            assert cursor.fetchone()[0] == 0
