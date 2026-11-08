from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.error import URLError

import pytest
from nex_wa.agent_result_source import (
    AeAgentResultSourceAdapter,
    HttpWcWorkResultProjectionClient,
)
from nex_wa.source_adapters import WaSourceAdapterError
from nex_wa.work_evidence import deterministic_work_evidence_id
from test_nex_wa_p9_s17_agent_result_admission import (
    AGENT,
    EXECUTION,
    NOW,
    PROJECT,
    RESULT,
    TENANT,
    _projection,
    _Projects,
    _request,
    _Source,
)


def _work_result(**overrides):
    value = {
        "tenant_id": TENANT,
        "result_id": "wc-result-1",
        "work_item_id": "work-1",
        "revision_no": 1,
        "source_execution_ref": EXECUTION,
        "claim_id": "claim-1",
        "claim_generation": 2,
        "assignment_id": "assignment-1",
        "submitted_agent_id": AGENT,
        "submitted_at": "2026-10-28T04:59:01Z",
        "result_hash": "sha256:" + "c" * 64,
    }
    value.update(overrides)
    return value


class _WorkResults:
    def __init__(self, value=None, error=None):
        self.value = value or _work_result()
        self.error = error
        self.calls = []

    def fetch_by_execution(self, *, tenant_id, agent_execution_id):
        self.calls.append((tenant_id, agent_execution_id))
        if self.error is not None:
            raise self.error
        return self.value


class _Admission:
    def __init__(self):
        self.single = []
        self.sets = []
        self.evidence = {}

    def admit_normalized_evidence(self, evidence, asset):
        self.single.append((evidence, asset))
        self._remember(evidence)

    def admit_normalized_evidence_set(self, evidence, asset):
        self.sets.append((evidence, asset))
        for item in evidence:
            self._remember(item)

    def find_evidence(
        self, *, tenant_id, source_type, source_ref, source_revision_ref
    ):
        return self.evidence.get(
            (tenant_id, source_type, source_ref, source_revision_ref)
        )

    def _remember(self, evidence):
        evidence_id = deterministic_work_evidence_id(
            tenant_id=evidence.tenant_id,
            source_type=evidence.source_type,
            source_ref=evidence.source_ref,
            source_revision_ref=evidence.source_revision_ref,
        )
        self.evidence[
            (
                evidence.tenant_id,
                evidence.source_type,
                evidence.source_ref,
                evidence.source_revision_ref,
            )
        ] = SimpleNamespace(work_evidence_id=evidence_id)


def _adapter(work_results):
    admission = _Admission()
    return (
        AeAgentResultSourceAdapter(
            source=_Source(_projection("CA")),
            admission=admission,
            projects=_Projects(),
            work_results=work_results,
            clock=lambda: NOW,
        ),
        admission,
    )


def test_background_result_creates_one_asset_with_primary_and_supporting_evidence() -> None:
    work_results = _WorkResults()
    adapter, admission = _adapter(work_results)
    adapter.fetch(_request())

    assert admission.single == []
    evidence, asset = admission.sets[0]
    assert [item.source_type for item in evidence] == [
        "AE_AGENT_RESULT",
        "WC_WORK_RESULT",
    ]
    assert [binding.binding_role for binding in asset.bindings] == [
        "PRIMARY",
        "SUPPORTING",
    ]
    assert work_results.calls == [(TENANT, EXECUTION)]
    assert evidence[1].source_ref == "work-1"
    assert evidence[1].source_revision_ref == "wc-result-1"
    assert evidence[1].project_ref == PROJECT
    assert evidence[0].classification == "CONFIDENTIAL"
    assert evidence[1].classification == "CONFIDENTIAL"
    assert asset.classification == "CONFIDENTIAL"


def test_same_work_result_replay_keeps_exact_semantics() -> None:
    adapter, admission = _adapter(_WorkResults())
    adapter.fetch(_request())
    adapter.fetch(_request())
    assert admission.sets[0] == admission.sets[1]


def test_new_work_result_revision_supersedes_existing_supporting_evidence() -> None:
    work_results = _WorkResults()
    adapter, admission = _adapter(work_results)
    adapter.fetch(_request())

    first_supporting = admission.sets[0][0][1]
    work_results.value = _work_result(
        result_id="wc-result-2",
        revision_no=2,
        result_hash="sha256:" + "d" * 64,
        submitted_at="2026-10-28T05:00:01Z",
        supersedes_result_id="wc-result-1",
        supersedes_revision_no=1,
    )
    adapter.fetch(_request())

    corrected = admission.sets[1][0][1]
    assert corrected.source_ref == first_supporting.source_ref == "work-1"
    assert corrected.source_revision_ref == "wc-result-2"
    assert corrected.supersedes_evidence_id == deterministic_work_evidence_id(
        tenant_id=TENANT,
        source_type="WC_WORK_RESULT",
        source_ref="work-1",
        source_revision_ref="wc-result-1",
    )


def test_reconciliation_accepts_latest_revision_without_local_predecessor() -> None:
    latest = _work_result(
        result_id="wc-result-2",
        revision_no=2,
        supersedes_result_id="wc-result-1",
        supersedes_revision_no=1,
    )
    adapter, admission = _adapter(_WorkResults(latest))
    adapter.fetch(_request())
    assert admission.sets[0][0][1].supersedes_evidence_id is None


def test_wc_unavailable_is_retryable_and_recovery_admits() -> None:
    failure = WaSourceAdapterError("WA_WC_SOURCE_UNAVAILABLE", "offline")
    adapter, admission = _adapter(_WorkResults(error=failure))
    with pytest.raises(WaSourceAdapterError) as exc_info:
        adapter.fetch(_request())
    assert exc_info.value.retryable is True
    assert admission.sets == []

    recovered, recovered_admission = _adapter(_WorkResults())
    recovered.fetch(_request())
    assert len(recovered_admission.sets) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", "OTHER"),
        ("source_execution_ref", "other-execution"),
        ("work_item_id", "other-work"),
        ("claim_id", "other-claim"),
        ("claim_generation", 3),
        ("assignment_id", "other-assignment"),
        ("submitted_agent_id", "other-agent"),
    ],
)
def test_wc_lineage_mismatch_fails_closed(field, value) -> None:
    adapter, admission = _adapter(_WorkResults(_work_result(**{field: value})))
    with pytest.raises(WaSourceAdapterError) as exc_info:
        adapter.fetch(_request())
    assert exc_info.value.error_code == "WA_WC_SOURCE_LINEAGE_MISMATCH"
    assert exc_info.value.retryable is False
    assert admission.sets == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("revision_no", 0),
        ("revision_no", True),
        ("result_id", None),
        ("result_hash", None),
        ("submitted_at", "invalid"),
        ("supersedes_result_id", "wc-result-0"),
        ("supersedes_revision_no", 0),
    ],
)
def test_wc_projection_shape_fails_closed(field, value) -> None:
    values = {field: value}
    if field == "supersedes_result_id":
        values["supersedes_revision_no"] = 1
    if field == "supersedes_revision_no":
        values["supersedes_result_id"] = "wc-result-0"
    adapter, admission = _adapter(_WorkResults(_work_result(**values)))
    with pytest.raises(WaSourceAdapterError):
        adapter.fetch(_request())
    assert admission.sets == []


def test_missing_wc_client_is_typed_retry() -> None:
    admission = _Admission()
    adapter = AeAgentResultSourceAdapter(
        source=_Source(_projection("CA")),
        admission=admission,
        projects=_Projects(),
    )
    with pytest.raises(WaSourceAdapterError) as exc_info:
        adapter.fetch(_request())
    assert exc_info.value.error_code == "WA_WC_SOURCE_UNAVAILABLE"
    assert exc_info.value.retryable is True


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_http_wc_projection_client_and_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "nex_wa.agent_result_source.urlopen",
        lambda *_args, **_kwargs: _Response(_work_result()),
    )
    client = HttpWcWorkResultProjectionClient(
        base_url="http://wc", service_token="signed"
    )
    assert client.fetch_by_execution(
        tenant_id=TENANT, agent_execution_id=EXECUTION
    )["result_id"] == "wc-result-1"

    monkeypatch.setattr(
        "nex_wa.agent_result_source.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")),
    )
    with pytest.raises(WaSourceAdapterError) as exc_info:
        client.fetch_by_execution(tenant_id=TENANT, agent_execution_id=RESULT)
    assert exc_info.value.error_code == "WA_WC_SOURCE_UNAVAILABLE"
