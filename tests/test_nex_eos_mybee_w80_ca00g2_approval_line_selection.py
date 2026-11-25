from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from nex_eos import (
    ApprovalLineSelectionInput,
    EosBusinessProposalApprovalError,
    EosBusinessProposalApprovalService,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

TENANT = "VO00"
PROPOSAL = str(uuid.UUID("00000000-0000-0000-0000-000000008001"))
COMPANY = str(uuid.UUID("00000000-0000-0000-0000-000000008002"))
PROJECT_A = str(uuid.UUID("00000000-0000-0000-0000-000000008003"))
PROJECT_B = str(uuid.UUID("00000000-0000-0000-0000-000000008004"))
POLICY = str(uuid.UUID("00000000-0000-0000-0000-000000008005"))
REQUESTER = "employee-requester"
NOW = datetime(2026, 11, 26, 1, 2, 3, tzinfo=UTC)


def _hash(value: str) -> str:
    return semantic_sha256_hash_ref({"value": value})


def _proposal(*, currency="KRW", state="DRAFT", projects=(PROJECT_A,)):
    return {
        "tenant_id": TENANT,
        "proposal_id": PROPOSAL,
        "company_id": COMPANY,
        "requester_subject_id": REQUESTER,
        "state": state,
        "version": 2,
        "current_revision": {
            "revision_no": 3,
            "transaction_type": "OPERATING_EXPENSE",
            "requested_amount": "1500000.0000",
            "original_currency": currency,
            "project_ids": list(projects),
            "content_hash": _hash("content"),
            "policy_selection_input_hash": _hash("policy-input"),
        },
    }


class Proposals:
    def __init__(self, value=None, *, failure=None):
        self.value = _proposal() if value is None else value
        self.failure = failure

    def get(self, **kwargs):
        if self.failure:
            raise self.failure
        if self.value == {}:
            return None
        if kwargs["requester_subject_id"] != REQUESTER:
            return None
        return copy.deepcopy(self.value)


class Companies:
    def __init__(self, currency="KRW", value=True):
        self.currency = currency
        self.value = value

    def get_legal_entity(self, **kwargs):
        return (
            {"company_id": COMPANY, "functional_currency": self.currency}
            if self.value
            else None
        )


class FxRates:
    def __init__(self, *, failure=None, response=None):
        self.failure = failure
        self.response = response
        self.calls = []

    def resolve_rate(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return self.response or {
            "rate_snapshot_id": str(uuid.UUID("00000000-0000-0000-0000-000000008006")),
            "snapshot_hash": _hash("fx"),
            "normalized_rate": "1400.25",
            "quote_unit": "1",
            "selected_rate_date": "2026-11-26",
        }


def _policy(*, stages=("TEAM_LEAD",), marker="policy"):
    return {
        "approval_policy_id": POLICY,
        "policy_hash": _hash(marker),
        "stages": [
            {
                "stage_order": order,
                "position_type": position,
                "quorum_count": 1,
                "separation_policy": "REQUESTER_EXCLUDED",
            }
            for order, position in enumerate(stages, start=1)
        ],
    }


class Policies:
    def __init__(self, values=None):
        self.values = list(values) if values is not None else [_policy()]
        self.calls = []

    def resolve_policy(self, selection):
        self.calls.append(selection)
        index = min(len(self.calls) - 1, len(self.values) - 1)
        return copy.deepcopy(self.values[index])


class Candidates:
    def __init__(self, *, failure=None, values=None):
        self.failure = failure
        self.values = values
        self.calls = []

    def list_eligible_candidates(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        if self.values is not None:
            return copy.deepcopy(self.values)
        position = kwargs["position_type"]
        return [
            {
                "subject_id": f"approver-{position.lower()}",
                "display_name": f"{position} Approver",
                "position_type": position,
                "authority_hash": _hash(position),
                "active": True,
            }
        ]


def _runtime(*, proposal=None, company=None, fx=None, policies=None, candidates=None):
    return EosBusinessProposalApprovalService(
        proposal or Proposals(),
        company or Companies(),
        fx or FxRates(),
        policies or Policies(),
        candidates or Candidates(),
    )


def _preview(runtime=None, **kwargs):
    return (runtime or _runtime()).preview(
        tenant_id=TENANT,
        proposal_id=PROPOSAL,
        requester_subject_id=REQUESTER,
        effective_at=NOW,
        **kwargs,
    )


def test_identity_currency_preview_and_exact_line_selection_are_deterministic():
    fx = FxRates()
    runtime = _runtime(fx=fx)
    preview = _preview(runtime, risk_level="LOW")

    assert fx.calls == []
    assert preview["normalized_amount_evidence"]["conversion_kind"] == "IDENTITY"
    assert preview["normalized_amount_evidence"]["normalized_amount"] == "1500000"
    assert preview["approval_policy"]["stages"][0]["position_type"] == "TEAM_LEAD"
    assert preview["required_stages"][0]["candidates"][0]["subject_id"] == (
        "approver-team_lead"
    )

    selection = ApprovalLineSelectionInput(
        preview_hash=preview["preview_hash"],
        proposal_id=PROPOSAL,
        revision_no=3,
        selected_approvers=({"stage_order": 1, "subject_id": "approver-team_lead"},),
    )
    first = runtime.select_line(preview=preview, selection=selection)
    second = runtime.select_line(preview=preview, selection=selection)
    assert first == second
    assert first["approval_line_hash"].startswith("sha256:")


def test_fx_normalization_and_three_stage_route_use_authoritative_inputs():
    fx = FxRates()
    policies = Policies([_policy(stages=("TEAM_LEAD", "GROUP_LEAD", "CEO"))])
    runtime = _runtime(
        proposal=Proposals(_proposal(currency="USD")), fx=fx, policies=policies
    )
    preview = _preview(runtime)

    amount = preview["normalized_amount_evidence"]
    assert amount["conversion_kind"] == "FX_SNAPSHOT"
    assert amount["normalized_amount"] == "2100375000"
    assert amount["rate_snapshot_hash"] == _hash("fx")
    assert fx.calls[0]["base_currency"] == "USD"
    assert fx.calls[0]["quote_currency"] == "KRW"
    assert policies.calls[0].amount == Decimal(2100375000)
    assert [item["position_type"] for item in preview["required_stages"]] == [
        "TEAM_LEAD",
        "GROUP_LEAD",
        "CEO",
    ]


def test_project_set_requires_one_policy_semantics_and_passes_scope_to_oa():
    candidates = Candidates()
    runtime = _runtime(
        proposal=Proposals(_proposal(projects=(PROJECT_A, PROJECT_B))),
        policies=Policies([_policy(), _policy()]),
        candidates=candidates,
    )
    preview = _preview(runtime)
    assert preview["approval_policy_id"] == POLICY
    assert candidates.calls[0]["project_ids"] == (PROJECT_A, PROJECT_B)

    with pytest.raises(EosBusinessProposalApprovalError) as caught:
        _preview(
            _runtime(
                proposal=Proposals(_proposal(projects=(PROJECT_A, PROJECT_B))),
                policies=Policies([_policy(marker="a"), _policy(marker="b")]),
            )
        )
    assert caught.value.error_code == "BUSINESS_PROPOSAL_APPROVAL_CONFLICT"


@pytest.mark.parametrize(
    ("runtime", "expected"),
    [
        (_runtime(proposal=Proposals(value={})), "NOT_FOUND"),
        (_runtime(proposal=Proposals(_proposal(state="SUBMITTED"))), "CONFLICT"),
        (_runtime(company=Companies(value=False)), "UNAVAILABLE"),
        (_runtime(policies=Policies([None])), "UNAVAILABLE"),
        (_runtime(candidates=Candidates(values=[])), "UNAVAILABLE"),
        (
            _runtime(
                fx=FxRates(failure=RuntimeError("offline")),
                proposal=Proposals(_proposal(currency="USD")),
            ),
            "UNAVAILABLE",
        ),
        (
            _runtime(candidates=Candidates(failure=RuntimeError("offline"))),
            "UNAVAILABLE",
        ),
    ],
)
def test_preview_fails_closed_for_missing_or_unavailable_authority(runtime, expected):
    with pytest.raises(EosBusinessProposalApprovalError) as caught:
        _preview(runtime)
    assert caught.value.error_code.endswith(expected)


def test_candidate_filter_excludes_requester_inactive_duplicate_and_wrong_role():
    valid = {
        "subject_id": "approver-valid",
        "display_name": "Valid Approver",
        "position_type": "TEAM_LEAD",
        "authority_hash": _hash("valid"),
        "active": True,
    }
    values = [
        {**valid, "subject_id": REQUESTER},
        {**valid, "subject_id": "inactive", "active": False},
        {**valid, "subject_id": "wrong", "position_type": "CEO"},
        valid,
        valid,
    ]
    preview = _preview(_runtime(candidates=Candidates(values=values)))
    assert [
        item["subject_id"] for item in preview["required_stages"][0]["candidates"]
    ] == ["approver-valid"]


def test_preview_changes_when_oa_candidate_evidence_changes():
    first = _preview()
    changed = _preview(
        _runtime(
            candidates=Candidates(
                values=[
                    {
                        "subject_id": "approver-team_lead",
                        "display_name": "Changed Authority",
                        "position_type": "TEAM_LEAD",
                        "authority_hash": _hash("changed"),
                        "active": True,
                    }
                ]
            )
        )
    )
    assert first["candidate_evidence_hash"] != changed["candidate_evidence_hash"]
    assert first["preview_hash"] != changed["preview_hash"]


def test_public_methods_rethrow_typed_authority_failures():
    failure = EosBusinessProposalApprovalError(
        "UPSTREAM_TYPED", "typed", status_code=503, retryable=True
    )
    with pytest.raises(EosBusinessProposalApprovalError) as fx_caught:
        _preview(
            _runtime(
                proposal=Proposals(_proposal(currency="USD")),
                fx=FxRates(failure=failure),
            )
        )
    assert fx_caught.value is failure

    with pytest.raises(EosBusinessProposalApprovalError) as oa_caught:
        _preview(_runtime(candidates=Candidates(failure=failure)))
    assert oa_caught.value is failure


@pytest.mark.parametrize(
    "mutator",
    [
        lambda proposal: proposal.pop("current_revision"),
        lambda proposal: proposal["current_revision"].update(requested_amount="bad"),
        lambda proposal: proposal["current_revision"].update(requested_amount="0"),
        lambda proposal: proposal["current_revision"].update(original_currency="K1"),
    ],
)
def test_preview_rejects_malformed_authoritative_proposal(mutator):
    proposal = _proposal()
    mutator(proposal)
    with pytest.raises(EosBusinessProposalApprovalError) as caught:
        _preview(_runtime(proposal=Proposals(proposal)))
    assert caught.value.error_code == "BUSINESS_PROPOSAL_APPROVAL_INVALID"


@pytest.mark.parametrize(
    "response",
    [
        {"normalized_rate": "bad", "quote_unit": "1"},
        {"normalized_rate": "0", "quote_unit": "1"},
        {"normalized_rate": "1", "quote_unit": "bad"},
        {"normalized_rate": "1", "quote_unit": "0"},
    ],
)
def test_preview_rejects_malformed_fx_snapshot(response):
    with pytest.raises(EosBusinessProposalApprovalError) as caught:
        _preview(
            _runtime(
                proposal=Proposals(_proposal(currency="USD")),
                fx=FxRates(response=response),
            )
        )
    assert caught.value.error_code == "BUSINESS_PROPOSAL_APPROVAL_INVALID"


def test_preview_rejects_naive_time_invalid_company_currency_and_candidate_shape():
    runtime = _runtime()
    with pytest.raises(EosBusinessProposalApprovalError):
        runtime.preview(
            tenant_id=TENANT,
            proposal_id=PROPOSAL,
            requester_subject_id=REQUESTER,
            effective_at=datetime(2026, 11, 26),  # noqa: DTZ001 - rejection case
        )
    with pytest.raises(EosBusinessProposalApprovalError):
        _preview(_runtime(company=Companies(currency="K1")))
    with pytest.raises(EosBusinessProposalApprovalError):
        _preview(
            _runtime(
                candidates=Candidates(
                    values=[
                        {
                            "subject_id": "bad subject",
                            "display_name": "Bad",
                            "position_type": "TEAM_LEAD",
                            "authority_hash": _hash("bad"),
                            "active": True,
                        }
                    ]
                )
            )
        )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            lambda preview, selection: selection.__class__(
                **{**selection.__dict__, "preview_hash": _hash("stale")}
            ),
            "CONFLICT",
        ),
        (
            lambda preview, selection: selection.__class__(
                **{**selection.__dict__, "proposal_id": str(uuid.uuid4())}
            ),
            "CONFLICT",
        ),
        (
            lambda preview, selection: selection.__class__(
                **{**selection.__dict__, "revision_no": 2}
            ),
            "CONFLICT",
        ),
        (
            lambda preview, selection: selection.__class__(
                **{**selection.__dict__, "selected_approvers": ()}
            ),
            "INVALID",
        ),
        (
            lambda preview, selection: selection.__class__(
                **{
                    **selection.__dict__,
                    "selected_approvers": (
                        {"stage_order": 2, "subject_id": "approver-team_lead"},
                    ),
                }
            ),
            "INVALID",
        ),
        (
            lambda preview, selection: selection.__class__(
                **{
                    **selection.__dict__,
                    "selected_approvers": (
                        {"stage_order": 1, "subject_id": "unknown"},
                    ),
                }
            ),
            "DENIED",
        ),
    ],
)
def test_line_selection_rejects_stale_malformed_or_ineligible_choices(
    mutation, expected
):
    runtime = _runtime()
    preview = _preview(runtime)
    selection = ApprovalLineSelectionInput(
        preview_hash=preview["preview_hash"],
        proposal_id=PROPOSAL,
        revision_no=3,
        selected_approvers=({"stage_order": 1, "subject_id": "approver-team_lead"},),
    )
    with pytest.raises(EosBusinessProposalApprovalError) as caught:
        runtime.select_line(preview=preview, selection=mutation(preview, selection))
    assert caught.value.error_code.endswith(expected)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(required_stages=[]),
        lambda value: value.update(required_stages="TEAM_LEAD"),
        lambda value: value["required_stages"][0].update(stage_order=2),
        lambda value: value["required_stages"][0].update(candidates="bad"),
        lambda value: value.pop("preview_hash"),
    ],
)
def test_line_selection_rejects_tampered_preview(mutator):
    runtime = _runtime()
    preview = _preview(runtime)
    selection = ApprovalLineSelectionInput(
        preview_hash=preview["preview_hash"],
        proposal_id=PROPOSAL,
        revision_no=3,
        selected_approvers=({"stage_order": 1, "subject_id": "approver-team_lead"},),
    )
    mutator(preview)
    with pytest.raises(EosBusinessProposalApprovalError):
        runtime.select_line(preview=preview, selection=selection)


def test_line_selection_rejects_invalid_input_types_and_scalar_shapes():
    runtime = _runtime()
    preview = _preview(runtime)
    valid = ApprovalLineSelectionInput(
        preview_hash=preview["preview_hash"],
        proposal_id=PROPOSAL,
        revision_no=3,
        selected_approvers=({"stage_order": 1, "subject_id": "approver-team_lead"},),
    )
    invalid = [
        ("not-a-preview", valid),
        (preview, {"selected": "bad"}),
        (
            preview,
            ApprovalLineSelectionInput(
                preview_hash=preview["preview_hash"],
                proposal_id=PROPOSAL,
                revision_no=True,
                selected_approvers=valid.selected_approvers,
            ),
        ),
        (
            preview,
            ApprovalLineSelectionInput(
                preview_hash=preview["preview_hash"],
                proposal_id=PROPOSAL,
                revision_no=3,
                selected_approvers="bad",  # type: ignore[arg-type]
            ),
        ),
        (
            preview,
            ApprovalLineSelectionInput(
                preview_hash=preview["preview_hash"],
                proposal_id=PROPOSAL,
                revision_no=3,
                selected_approvers=("bad",),  # type: ignore[arg-type]
            ),
        ),
    ]
    for preview_value, selection in invalid:
        with pytest.raises(EosBusinessProposalApprovalError):
            runtime.select_line(  # type: ignore[arg-type]
                preview=preview_value, selection=selection
            )


@pytest.mark.parametrize(
    "policy",
    [
        {**_policy(), "stages": []},
        {**_policy(), "stages": "TEAM_LEAD"},
        {**_policy(), "stages": [{**_policy()["stages"][0], "stage_order": 2}]},
        {**_policy(), "stages": [{**_policy()["stages"][0], "quorum_count": 2}]},
    ],
)
def test_policy_stage_shape_is_fail_closed(policy):
    with pytest.raises(EosBusinessProposalApprovalError) as caught:
        _preview(_runtime(policies=Policies([policy])))
    assert caught.value.error_code == "BUSINESS_PROPOSAL_APPROVAL_INVALID"
