from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from nex_eos import business_voucher_drafts as drafts

HASH = "sha256:" + "a" * 64
PROJECT_CODE = "VO00D260001"


def _line(*, debit: object = "100", credit: object = "0") -> dict[str, object]:
    return {
        "account_code": "TRAVEL",
        "debit_original": debit,
        "credit_original": credit,
        "source_record_line_ref": "line-1",
        "evidence_hash": HASH,
    }


@pytest.mark.parametrize(
    "operation",
    [
        lambda: drafts._draft_lines(None),
        lambda: drafts._draft_lines([_line(), "not-an-object"]),
        lambda: drafts._draft_lines([_line(debit="1", credit="1"), _line()]),
        lambda: drafts._draft_lines([_line(), _line(debit="0", credit="99")]),
        lambda: drafts._draft_lines([_line(debit="-1"), _line(debit="0", credit="1")]),
        lambda: drafts._uuid("candidate_id", "bad"),
        lambda: drafts._date("recognition_date", "bad"),
        lambda: drafts._aware(datetime.fromisoformat("2026-11-26T00:00:00")),
        lambda: drafts._positive_int("expected_version", True),
        lambda: drafts._money("amount", "bad"),
        lambda: drafts._project_code("SHORT"),
        lambda: drafts._code("source_kind", "bad-code"),
        lambda: drafts._text("description", "", 10),
        lambda: drafts._hash_ref("evidence_hash", "short"),
        lambda: drafts._hash_ref("evidence_hash", "sha256:" + "z" * 64),
        lambda: drafts._trace("not-an-object", fallback="fallback"),
    ],
)
def test_input_admission_rejects_malformed_business_values(operation) -> None:
    with pytest.raises(drafts.EosBusinessVoucherDraftError) as error:
        operation()
    assert error.value.status_code == 422


def test_input_projection_helpers_cover_optional_and_provider_neutral_branches() -> None:
    assert drafts._trace(None, fallback="fallback")["trace_id"] == "fallback"
    assert drafts._trace(
        {"trace_id": "t", "correlation_id": "c", "causation_id": "a"},
        fallback="unused",
    ) == {"trace_id": "t", "correlation_id": "c", "causation_id": "a"}
    assert drafts._rate_publication(
        {
            "mode": "MARKET_BASE_RATE",
            "selected_rate_date": "2026-11-26",
            "base_currency": "USD",
            "quote_currency": "KRW",
        }
    ) == "MARKET_BASE_RATE:2026-11-26:USD/KRW"
    assert drafts._timestamp(datetime.fromisoformat("2026-11-26T01:02:03")) == (
        "2026-11-26T01:02:03Z"
    )
    lines = drafts._draft_lines(
        [
            {**_line(), "description": "Travel"},
            _line(debit="0", credit="100"),
        ]
    )
    assert lines[0].description == "Travel"
    assert lines[1].description is None


def _service(*, candidate=None, envelope=None, project=None, account=None):
    return drafts.EosBusinessVoucherDraftService(
        coordinator=SimpleNamespace(),
        candidates=SimpleNamespace(get=lambda **_kwargs: candidate),
        candidate_reviews=SimpleNamespace(),
        create_service=SimpleNamespace(),
        validation_service=SimpleNamespace(),
        scoped_approvals=SimpleNamespace(
            replay_accounting_case=lambda **_kwargs: None
        ),
        approval_policies=SimpleNamespace(),
        approved_documents=SimpleNamespace(get=lambda **_kwargs: envelope),
        projects=SimpleNamespace(get_project_by_code=lambda **_kwargs: project),
        accounts=SimpleNamespace(
            get_effective_account_by_code=lambda **_kwargs: account,
            get_account=lambda **_kwargs: account,
        ),
        clock=lambda: datetime(2026, 11, 26, tzinfo=UTC),
    )


def test_owner_envelope_project_and_account_boundaries_fail_closed() -> None:
    candidate_id = "00000000-0000-4000-8000-000000000001"
    with pytest.raises(drafts.EosBusinessVoucherDraftError) as missing:
        _service()._require_owner("VO00", "employee-1", candidate_id)
    assert missing.value.status_code == 404

    wrong_owner = {"preparer_subject_id": "employee-2"}
    with pytest.raises(drafts.EosBusinessVoucherDraftError):
        _service(candidate=wrong_owner)._require_owner(
            "VO00", "employee-1", candidate_id
        )
    with pytest.raises(drafts.EosBusinessVoucherDraftError):
        _service(envelope={"usable": False})._require_envelope("VO00", "envelope-1")

    envelope = {
        "allowed_project_ids": ["project-1"],
        "allowed_project_codes": [PROJECT_CODE],
    }
    with pytest.raises(drafts.EosBusinessVoucherDraftError):
        _service(envelope=envelope)._require_project(
            "VO00", PROJECT_CODE, envelope=envelope
        )
    with pytest.raises(drafts.EosBusinessVoucherDraftError):
        _service(project={"project_id": "project-2", "project_code": PROJECT_CODE})._require_project(
            "VO00", PROJECT_CODE, envelope=envelope
        )
    with pytest.raises(drafts.EosBusinessVoucherDraftError):
        _service()._resolve_lines(
            "VO00",
            date(2026, 11, 26),
            drafts._draft_lines([_line(), _line(debit="0", credit="100")]),
        )


def test_review_state_staleness_amount_and_unknown_account_branches() -> None:
    service = _service(
        candidate={"preparer_subject_id": "employee-1", "state": "READY_FOR_REVIEW"}
    )
    with pytest.raises(drafts.EosBusinessVoucherDraftError) as state_error:
        service.revise(
            tenant_id="VO00",
            subject_id="employee-1",
            candidate_id="00000000-0000-4000-8000-000000000001",
            payload={},
        )
    assert state_error.value.status_code == 409

    with pytest.raises(drafts.EosBusinessVoucherDraftError):
        service.submit(
            tenant_id="VO00",
            subject_id="employee-1",
            candidate_id="00000000-0000-4000-8000-000000000001",
            payload={"confirmed": False},
            caller=SimpleNamespace(),
        )
    with pytest.raises(drafts.EosBusinessVoucherDraftError):
        drafts._require_amount_within_envelope(
            [SimpleNamespace(debit_original=Decimal(101))],
            {"remaining_amount": "100"},
        )
    projected = _service()._project_line(
        "VO00",
        {
            "line_no": 1,
            "account_id": "account-1",
            "debit_original": Decimal(1),
            "credit_original": Decimal(0),
            "source_record_line_ref": "line-1",
            "description": None,
            "evidence_hash": HASH,
        },
    )
    assert projected["account_code"] == "UNKNOWN"


def test_list_stale_submit_and_missing_policy_are_explicit() -> None:
    candidate_id = "00000000-0000-4000-8000-000000000001"
    candidate_hash = "sha256:" + "b" * 64
    candidate = {
        "preparer_subject_id": "employee-1",
        "version": 2,
        "current_revision_no": 2,
        "revision": {"candidate_hash": candidate_hash},
        "lines": [{"account_id": "account-1"}],
        "project_id": "project-1",
    }
    service = _service(candidate=candidate)
    service._candidates.list_preparer = lambda **_kwargs: []
    assert service.list_owner(
        tenant_id="VO00", subject_id="employee-1"
    )["items"] == []
    with pytest.raises(drafts.EosBusinessVoucherDraftError) as stale:
        service.submit(
            tenant_id="VO00",
            subject_id="employee-1",
            candidate_id=candidate_id,
            payload={
                "confirmed": True,
                "client_command_id": "00000000-0000-4000-8000-000000000003",
                "expected_version": 1,
                "expected_revision": 2,
                "expected_candidate_hash": candidate_hash,
            },
            caller=SimpleNamespace(),
        )
    assert stale.value.status_code == 409

    service._validation_service = SimpleNamespace(
        validate=lambda *_args, **_kwargs: {
            "totals": {"debit_original": "100.0000"}
        }
    )
    service._approval_policies = SimpleNamespace(resolve_policy=lambda _selection: None)
    with pytest.raises(drafts.EosBusinessVoucherDraftError) as no_policy:
        service.submit(
            tenant_id="VO00",
            subject_id="employee-1",
            candidate_id=candidate_id,
            payload={
                "confirmed": True,
                "client_command_id": "00000000-0000-4000-8000-000000000004",
                "expected_version": 2,
                "expected_revision": 2,
                "expected_candidate_hash": candidate_hash,
            },
            caller=SimpleNamespace(),
        )
    assert no_policy.value.error_code == "EOS_ACCOUNTING_APPROVAL_POLICY_NOT_FOUND"


def test_revision_requires_a_real_business_transaction() -> None:
    candidate_id = "00000000-0000-4000-8000-000000000001"
    envelope_id = "00000000-0000-4000-8000-000000000002"
    candidate_hash = "sha256:" + "b" * 64
    candidate = {
        "preparer_subject_id": "employee-1",
        "state": "DRAFT",
        "document_envelope_id": envelope_id,
    }
    envelope = {"usable": True, "remaining_amount": "1000"}
    account = {"account_id": "account-1"}
    service = _service(candidate=candidate, envelope=envelope, account=account)
    service._coordinator = SimpleNamespace(
        execute=lambda _request, mutation: mutation(None)
    )
    with pytest.raises(drafts.EosBusinessVoucherDraftError) as error:
        service.revise(
            tenant_id="VO00",
            subject_id="employee-1",
            candidate_id=candidate_id,
            payload={
                "client_command_id": "00000000-0000-4000-8000-000000000003",
                "expected_version": 1,
                "expected_revision": 1,
                "expected_candidate_hash": candidate_hash,
                "recognition_date": "2026-11-26",
                "lines": [_line(), _line(debit="0", credit="100")],
            },
        )
    assert error.value.error_code == "EOS_BUSINESS_VOUCHER_TRANSACTION_REQUIRED"


@pytest.mark.parametrize(
    ("state", "expected_method", "expects_return_event"),
    [
        ("DRAFT", "append_draft_revision_in_session", False),
        ("RETURNED_FOR_CORRECTION", "append_revision_in_session", True),
    ],
)
def test_revision_uses_state_specific_immutable_append_path(
    state, expected_method, expects_return_event
) -> None:
    candidate_id = "00000000-0000-4000-8000-000000000001"
    envelope_id = "00000000-0000-4000-8000-000000000002"
    candidate_hash = "sha256:" + "b" * 64
    candidate = {
        "preparer_subject_id": "employee-1",
        "state": state,
        "document_envelope_id": envelope_id,
    }
    service = _service(
        candidate=candidate,
        envelope={"usable": True, "remaining_amount": "1000"},
        account={"account_id": "account-1"},
    )
    calls = []
    service._coordinator = SimpleNamespace(
        execute=lambda _request, mutation: mutation(object())
    )
    service._candidate_reviews = SimpleNamespace(
        require_latest_return_event_in_session=lambda *_args, **kwargs: calls.append(
            ("return_event", kwargs["candidate_revision"])
        )
    )

    def append(method):
        def invoke(_session, value):
            calls.append((method, value.expected_revision_no))
            return {
                "revision": {
                    "revision_no": 2,
                    "candidate_hash": "sha256:" + "c" * 64,
                }
            }

        return invoke

    service._candidates.append_draft_revision_in_session = append(
        "append_draft_revision_in_session"
    )
    service._candidates.append_revision_in_session = append(
        "append_revision_in_session"
    )
    service.get_owner = lambda **_kwargs: {"state": "DRAFT"}

    result = service.revise(
        tenant_id="VO00",
        subject_id="employee-1",
        candidate_id=candidate_id,
        payload={
            "client_command_id": "00000000-0000-4000-8000-000000000003",
            "expected_version": 3,
            "expected_revision": 1,
            "expected_candidate_hash": candidate_hash,
            "recognition_date": "2026-11-26",
            "lines": [_line(), _line(debit="0", credit="100")],
        },
    )

    assert result == {"state": "DRAFT"}
    assert (expected_method, 1) in calls
    assert (("return_event", 1) in calls) is expects_return_event


def test_returned_revision_requires_immutable_return_evidence() -> None:
    candidate_id = "00000000-0000-4000-8000-000000000001"
    service = _service(
        candidate={
            "preparer_subject_id": "employee-1",
            "state": "RETURNED_FOR_CORRECTION",
            "document_envelope_id": "00000000-0000-4000-8000-000000000002",
        },
        envelope={"usable": True, "remaining_amount": "1000"},
        account={"account_id": "account-1"},
    )
    service._coordinator = SimpleNamespace(
        execute=lambda _request, mutation: mutation(object())
    )

    def reject(*_args, **_kwargs):
        raise drafts.EosCandidateReviewError(
            "EOS_CANDIDATE_REVIEW_CONFLICT",
            "Candidate correction requires an immutable return event.",
            status_code=409,
        )

    service._candidate_reviews = SimpleNamespace(
        require_latest_return_event_in_session=reject
    )
    with pytest.raises(drafts.EosBusinessVoucherDraftError) as error:
        service.revise(
            tenant_id="VO00",
            subject_id="employee-1",
            candidate_id=candidate_id,
            payload={
                "client_command_id": "00000000-0000-4000-8000-000000000003",
                "expected_version": 3,
                "expected_revision": 1,
                "expected_candidate_hash": "sha256:" + "b" * 64,
                "recognition_date": "2026-11-26",
                "lines": [_line(), _line(debit="0", credit="100")],
            },
        )
    assert error.value.error_code == "EOS_CANDIDATE_REVIEW_CONFLICT"
    assert error.value.status_code == 409
