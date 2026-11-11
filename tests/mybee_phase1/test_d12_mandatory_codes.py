from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import MappingProxyType

import jsonschema
import pytest
import yaml
from mybee_ax.domain.project_templates import (
    APPROVE_OPERATION,
    GET_OPERATION,
    MANDATORY_CODES_HASH,
    READINESS_OPERATION,
    TEMPLATE_DIGEST,
    TEMPLATE_ID,
    TEMPLATE_STATUS,
    TEMPLATE_VERSION,
    EosProjectTemplateClient,
    ProjectTemplateError,
    calculate_mandatory_codes_hash,
    calculate_template_digest,
    d12_project_work_set_payload_hash,
    load_d12_project_template,
)
from mybee_ax.domain.work_codes import (
    MANDATORY_D12_WORK_CODE_IDS,
    load_work_code_catalog,
)
from nex_eos import project_work_code_set_payload_hash
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = ROOT / "domains/mybee/templates/d12/required_five.json"
SCHEMA_PATH = ROOT / "domains/mybee/templates/d12/required_five.schema.json"
OPENAPI_PATH = ROOT / "contracts/openapi/nex-eos.openapi.yaml"

TENANT_ID = "VO00"
PROJECT_ID = "c1000000-0000-4000-8000-000000000001"
WORK_SET_ID = "c2000000-0000-4000-8000-000000000001"
COMPANY_BINDING_ID = "c3000000-0000-4000-8000-000000000001"
OPERATION_ID = "c4000000-0000-4000-8000-000000000001"
SUBJECT_ID = "employee-1001"
PM_ID = "employee-2001"
PA_ID = "pa-project-001"
PROOF_HASH = "sha256:" + "a" * 64
PA_EVIDENCE_HASH = "sha256:" + "b" * 64
WORK_SET_HASH = "sha256:" + "c" * 64


def _raw_template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _write_template(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "template.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _approval_bindings() -> dict:
    return {
        "tenant_id": TENANT_ID,
        "project_id": PROJECT_ID,
        "subject_id": SUBJECT_ID,
        "business_operation_id": OPERATION_ID,
        "idempotency_key": "mb1-02:required-five:revision-1",
        "work_set_id": WORK_SET_ID,
        "revision": 1,
        "approved_proof_hash": PROOF_HASH,
        "pm_subject_id": PM_ID,
        "pa_agent_id": PA_ID,
        "pa_identity_evidence_hash": PA_EVIDENCE_HASH,
        "effective_from": date(2026, 11, 11),
    }


def _work_set(**overrides) -> dict:
    value = {
        "tenant_id": TENANT_ID,
        "project_id": PROJECT_ID,
        "work_set_id": WORK_SET_ID,
        "revision": 1,
        "catalog_id": "mybee.fl.d12.project-governance",
        "catalog_version": "1.0.0",
        "catalog_digest": (
            "sha256:31e5a24a8a5e62f80fc1571a4a232723a90f9c1b628841ae80df24654848c8ba"
        ),
        "template_ref": TEMPLATE_ID,
        "template_version": TEMPLATE_VERSION,
        "mandatory_codes_hash": MANDATORY_CODES_HASH,
        "approved_proof_hash": PROOF_HASH,
        "approved_by_subject_id": SUBJECT_ID,
        "pm_subject_id": PM_ID,
        "pa_agent_id": PA_ID,
        "pa_identity_evidence_hash": PA_EVIDENCE_HASH,
        "state": "APPROVED",
        "effective_from": "2026-11-11",
        "work_set_hash": WORK_SET_HASH,
        "created_at": "2026-11-11T00:00:00+00:00",
        "code_ids": list(MANDATORY_D12_WORK_CODE_IDS),
    }
    value.update(overrides)
    return value


def _readiness(*, ready: bool = True, **overrides) -> dict:
    source = {
        "tenant_id": TENANT_ID,
        "project_id": PROJECT_ID,
        "technical_status": "ACTIVE",
        "work_set_hash": WORK_SET_HASH if ready else None,
        "company_binding_ids": [COMPANY_BINDING_ID] if ready else [],
        "required_codes_ok": ready,
        "project_company_bound": ready,
        "pm_assigned": ready,
        "members_eligible": ready,
        "pa_identity_bound": ready,
        "effective_on": "2026-11-11",
    }
    value = {
        **source,
        "state": "BUSINESS_READY" if ready else "DRAFT_CONFIGURATION",
        "business_ready": ready,
        "budget_bound_if_required": True,
        "reason_codes": [] if ready else ["WORK_CODE_SET_MISSING"],
        "source_hash": semantic_sha256_hash_ref(
            {"domain": "EOS-PROJECT-BUSINESS-READINESS-V1", **source}
        ),
        "work_set": _work_set() if ready else None,
    }
    value.update(overrides)
    return value


def test_mb1_02_template_matches_schema_catalog_and_immutable_digest() -> None:
    raw = _raw_template()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(raw)

    template = load_d12_project_template()
    catalog = load_work_code_catalog()
    assert template.template_id == TEMPLATE_ID
    assert template.template_version == TEMPLATE_VERSION
    assert template.status == TEMPLATE_STATUS
    assert template.template_digest == TEMPLATE_DIGEST
    assert template.template_digest == calculate_template_digest(raw)
    assert template.catalog_digest == catalog.mapping_digest
    assert template.required_code_ids == MANDATORY_D12_WORK_CODE_IDS
    assert template.mandatory_codes_hash == MANDATORY_CODES_HASH
    assert calculate_mandatory_codes_hash(template.required_code_ids) == (
        MANDATORY_CODES_HASH
    )


def test_mb1_02_approval_request_matches_s1_05_provider_hash_contract() -> None:
    request = load_d12_project_template().approval_request(**_approval_bindings())

    assert request.method == "POST"
    assert request.operation_id == APPROVE_OPERATION
    assert request.path == (
        f"/internal/v2/projects/{PROJECT_ID}/work-code-sets:approve"
    )
    assert request.tenant_id == TENANT_ID
    assert request.subject_id == SUBJECT_ID
    assert request.query is None
    assert "project_id" not in request.payload
    provider_payload = {**dict(request.payload), "project_id": PROJECT_ID}
    assert request.payload["payload_hash"] == d12_project_work_set_payload_hash(
        provider_payload
    )
    assert request.payload["payload_hash"] == project_work_code_set_payload_hash(
        provider_payload
    )
    assert request.payload["work_set"]["code_ids"] == list(MANDATORY_D12_WORK_CODE_IDS)


def test_mb1_02_read_requests_use_only_canonical_eos_public_boundaries() -> None:
    template = load_d12_project_template()
    current = template.current_work_set_request(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        subject_id=SUBJECT_ID,
    )
    readiness = template.business_readiness_request(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        subject_id=SUBJECT_ID,
        effective_on=date(2026, 11, 11),
    )

    assert (current.method, current.operation_id, current.query) == (
        "GET",
        GET_OPERATION,
        None,
    )
    assert current.path.endswith(f"/{PROJECT_ID}/work-code-set")
    assert readiness.operation_id == READINESS_OPERATION
    assert readiness.path.endswith(f"/{PROJECT_ID}/business-readiness")
    assert dict(readiness.query) == {"effective_on": "2026-11-11"}


def test_mb1_02_static_openapi_matches_template_consumer_operations() -> None:
    template = _raw_template()
    spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))

    for name, method in (
        ("approve", "post"),
        ("current_work_set", "get"),
        ("business_readiness", "get"),
    ):
        contract = template["eos_consumer_contract"][name]
        path = contract["path_template"]
        operation = spec["paths"][path][method]
        assert operation["operationId"] == contract["operation_id"]
        assert operation["x-nex-business-scope"] == contract["business_scope"]
    assert (
        spec["paths"][template["eos_consumer_contract"]["approve"]["path_template"]][
            "post"
        ]["x-nex-route-class"]
        == "WRITE"
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        (lambda value: value.update({"extra": True}), "TEMPLATE_FIELDS_INVALID"),
        (
            lambda value: value.update({"template_version": "2.0.0"}),
            "TEMPLATE_IDENTITY_INVALID",
        ),
        (
            lambda value: value["catalog_binding"]["required_code_ids"].pop(),
            "TEMPLATE_REQUIRED_CODES_INVALID",
        ),
        (
            lambda value: value["catalog_binding"].update(
                {"catalog_digest": "sha256:" + "0" * 64}
            ),
            "TEMPLATE_CATALOG_BINDING_INVALID",
        ),
        (
            lambda value: value["eos_consumer_contract"]["approve"].update(
                {"operation_id": "PROJECT.PROJECT.CREATE"}
            ),
            "TEMPLATE_EOS_CONTRACT_INVALID",
        ),
        (
            lambda value: value["readiness_contract"].update(
                {"active_is_not_business_ready": False}
            ),
            "TEMPLATE_READINESS_INVALID",
        ),
        (
            lambda value: value["runtime_boundaries"].update(
                {"direct_database_access": True}
            ),
            "TEMPLATE_BOUNDARY_INVALID",
        ),
        (
            lambda value: value["release_attestation"].update({"authority": "OTHER"}),
            "TEMPLATE_ATTESTATION_INVALID",
        ),
        (
            lambda value: value["release_attestation"].update(
                {"content_digest": "sha256:" + "0" * 64}
            ),
            "TEMPLATE_DIGEST_MISMATCH",
        ),
    ),
)
def test_mb1_02_template_drift_fails_closed(
    tmp_path: Path, mutation, expected_code: str
) -> None:
    value = copy.deepcopy(_raw_template())
    mutation(value)
    with pytest.raises(ProjectTemplateError) as raised:
        load_d12_project_template(_write_template(tmp_path, value))
    assert raised.value.code == expected_code


def test_mb1_02_loader_rejects_unreadable_invalid_json_and_nonobject(
    tmp_path: Path,
) -> None:
    with pytest.raises(ProjectTemplateError) as unreadable:
        load_d12_project_template(tmp_path / "missing.json")
    assert unreadable.value.code == "TEMPLATE_UNREADABLE"

    malformed = tmp_path / "bad.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(ProjectTemplateError) as invalid_json:
        load_d12_project_template(malformed)
    assert invalid_json.value.code == "TEMPLATE_INVALID_JSON"

    with pytest.raises(ProjectTemplateError) as nonobject:
        load_d12_project_template(_write_template(tmp_path, []))
    assert nonobject.value.code == "TEMPLATE_FIELDS_INVALID"


def test_mb1_02_loader_rejects_catalog_code_that_is_not_mandatory() -> None:
    catalog = load_work_code_catalog()
    changed_code = replace(catalog.work_codes[0], required_for_project_work_set=False)
    changed_codes = (changed_code, *catalog.work_codes[1:])
    changed_catalog = replace(
        catalog,
        work_codes=changed_codes,
        _by_code=MappingProxyType({item.code_id: item for item in changed_codes}),
    )

    with pytest.raises(ProjectTemplateError) as raised:
        load_d12_project_template(catalog=changed_catalog)
    assert raised.value.code == "TEMPLATE_REQUIRED_CODES_INVALID"


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    (
        ("tenant_id", "bad tenant", "TENANT_ID_INVALID"),
        ("project_id", "bad", "PROJECT_ID_INVALID"),
        ("business_operation_id", "bad", "BUSINESS_OPERATION_ID_INVALID"),
        ("idempotency_key", "", "IDEMPOTENCY_KEY_INVALID"),
        ("work_set_id", "bad", "WORK_SET_ID_INVALID"),
        ("revision", True, "REVISION_INVALID"),
        ("approved_proof_hash", "bad", "APPROVED_PROOF_HASH_INVALID"),
        ("pa_identity_evidence_hash", "bad", "PA_IDENTITY_EVIDENCE_HASH_INVALID"),
        ("effective_from", datetime.now(UTC), "EFFECTIVE_FROM_INVALID"),
    ),
)
def test_mb1_02_approval_runtime_bindings_fail_closed(
    field: str, value: object, expected_code: str
) -> None:
    bindings = _approval_bindings()
    bindings[field] = value
    with pytest.raises(ProjectTemplateError) as raised:
        load_d12_project_template().approval_request(**bindings)
    assert raised.value.code == expected_code


def test_mb1_02_human_pm_and_pa_identity_must_be_distinct() -> None:
    bindings = _approval_bindings()
    bindings["pa_agent_id"] = PM_ID
    with pytest.raises(ProjectTemplateError) as raised:
        load_d12_project_template().approval_request(**bindings)
    assert raised.value.code == "PROJECT_ACTOR_CONFLICT"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        (lambda value: "not-an-object", "EOS_WORK_SET_INVALID"),
        (
            lambda value: value.update({"tenant_id": "other"}) or value,
            "EOS_WORK_SET_SCOPE_MISMATCH",
        ),
        (
            lambda value: value.update({"template_version": "2.0.0"}) or value,
            "EOS_WORK_SET_IDENTITY_MISMATCH",
        ),
        (
            lambda value: value.update({"code_ids": "FL0012004"}) or value,
            "CODE_IDS_INVALID",
        ),
        (
            lambda value: value.update({"code_ids": [*value["code_ids"], None]})
            or value,
            "CODE_IDS_INVALID",
        ),
        (
            lambda value: (value["code_ids"].pop(), value)[1],
            "EOS_WORK_SET_CODES_MISMATCH",
        ),
        (
            lambda value: value.update({"revision": 0}) or value,
            "REVISION_INVALID",
        ),
        (
            lambda value: value.update({"work_set_id": "bad"}) or value,
            "WORK_SET_ID_INVALID",
        ),
        (
            lambda value: value.update({"work_set_hash": "bad"}) or value,
            "WORK_SET_HASH_INVALID",
        ),
        (
            lambda value: value.update({"effective_from": "bad"}) or value,
            "EFFECTIVE_FROM_INVALID",
        ),
    ),
)
def test_mb1_02_work_set_projection_drift_fails_closed(mutation, expected_code) -> None:
    value = mutation(_work_set())
    with pytest.raises(ProjectTemplateError) as raised:
        load_d12_project_template().admit_work_set(
            value, tenant_id=TENANT_ID, project_id=PROJECT_ID
        )
    assert raised.value.code == expected_code


def test_mb1_02_business_ready_projection_is_admitted_for_pa_write() -> None:
    admitted = load_d12_project_template().require_business_ready(
        _readiness(), tenant_id=TENANT_ID, project_id=PROJECT_ID
    )
    assert admitted.tenant_id == TENANT_ID
    assert admitted.project_id == PROJECT_ID
    assert admitted.effective_on == date(2026, 11, 11)
    assert admitted.work_set_hash == WORK_SET_HASH
    assert admitted.company_binding_ids == (COMPANY_BINDING_ID,)


def test_mb1_02_active_project_without_business_ready_is_denied() -> None:
    with pytest.raises(ProjectTemplateError) as raised:
        load_d12_project_template().require_business_ready(
            _readiness(ready=False), tenant_id=TENANT_ID, project_id=PROJECT_ID
        )
    assert raised.value.code == "PROJECT_NOT_BUSINESS_READY"
    assert "WORK_CODE_SET_MISSING" in str(raised.value)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        (
            lambda value: value.update({"tenant_id": "other"}),
            "EOS_READINESS_SCOPE_MISMATCH",
        ),
        (
            lambda value: value.update({"reason_codes": "bad"}),
            "REASON_CODES_INVALID",
        ),
        (
            lambda value: value.update({"effective_on": "bad"}),
            "EFFECTIVE_ON_INVALID",
        ),
        (
            lambda value: value.update({"effective_on": None}),
            "EFFECTIVE_ON_INVALID",
        ),
        (
            lambda value: value.update({"company_binding_ids": ["bad"]}),
            "COMPANY_BINDING_ID_INVALID",
        ),
        (
            lambda value: value.update(
                {
                    "company_binding_ids": [
                        "c3000000-0000-4000-8000-000000000002",
                        COMPANY_BINDING_ID,
                    ]
                }
            ),
            "EOS_READINESS_BINDINGS_INVALID",
        ),
        (
            lambda value: value.update({"source_hash": "sha256:" + "0" * 64}),
            "EOS_READINESS_HASH_MISMATCH",
        ),
        (
            lambda value: value["work_set"].update(
                {"work_set_hash": "sha256:" + "d" * 64}
            ),
            "EOS_READINESS_WORK_SET_MISMATCH",
        ),
    ),
)
def test_mb1_02_readiness_projection_drift_fails_closed(
    mutation, expected_code: str
) -> None:
    value = _readiness()
    mutation(value)
    if expected_code not in {
        "EOS_READINESS_SCOPE_MISMATCH",
        "REASON_CODES_INVALID",
        "EFFECTIVE_ON_INVALID",
        "COMPANY_BINDING_ID_INVALID",
        "EOS_READINESS_BINDINGS_INVALID",
        "EOS_READINESS_HASH_MISMATCH",
    }:
        source = {
            key: value[key]
            for key in (
                "tenant_id",
                "project_id",
                "technical_status",
                "work_set_hash",
                "company_binding_ids",
                "required_codes_ok",
                "project_company_bound",
                "pm_assigned",
                "members_eligible",
                "pa_identity_bound",
                "effective_on",
            )
        }
        value["source_hash"] = semantic_sha256_hash_ref(
            {"domain": "EOS-PROJECT-BUSINESS-READINESS-V1", **source}
        )
    with pytest.raises(ProjectTemplateError) as raised:
        load_d12_project_template().require_business_ready(
            value, tenant_id=TENANT_ID, project_id=PROJECT_ID
        )
    assert raised.value.code == expected_code


class RecordingTransport:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = iter(responses)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return next(self.responses)


def test_mb1_02_client_consumes_approval_work_set_and_readiness() -> None:
    transport = RecordingTransport(
        [
            {"created": True, "result": {"work_set": _work_set()}},
            _work_set(),
            _readiness(),
        ]
    )
    client = EosProjectTemplateClient(transport)
    template = load_d12_project_template()

    approved = client.approve_work_set(template, **_approval_bindings())
    current = client.get_current_work_set(
        template,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        subject_id=SUBJECT_ID,
    )
    ready = client.require_business_ready(
        template,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        subject_id=SUBJECT_ID,
    )

    assert approved["work_set_hash"] == WORK_SET_HASH
    assert current["revision"] == 1
    assert ready.work_set_hash == WORK_SET_HASH
    assert [request.operation_id for request in transport.requests] == [
        APPROVE_OPERATION,
        GET_OPERATION,
        READINESS_OPERATION,
    ]


def test_mb1_02_client_rejects_nonobject_provider_response() -> None:
    client = EosProjectTemplateClient(RecordingTransport([[]]))
    with pytest.raises(ProjectTemplateError) as raised:
        client.get_current_work_set(
            load_d12_project_template(),
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            subject_id=SUBJECT_ID,
        )
    assert raised.value.code == "EOS_WORK_SET_INVALID"


def test_mb1_02_payload_hash_rejects_nonobject() -> None:
    with pytest.raises(ProjectTemplateError) as raised:
        d12_project_work_set_payload_hash(None)
    assert raised.value.code == "PAYLOAD_INVALID"
