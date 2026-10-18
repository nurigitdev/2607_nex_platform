from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from nex_runtime import (
    InMemoryJobQueue,
    JobRetryPolicy,
    build_common_job,
    build_job_error,
    build_subject_ref,
)


ROOT = Path(__file__).resolve().parents[1]
P7 = ROOT / "docs" / "transition" / "P7"
CONTRACTS = P7 / "contracts"
EXAMPLES = CONTRACTS / "examples"
NEGATIVE = CONTRACTS / "tests" / "negative"
FROZEN_WC = (
    ROOT
    / "docs"
    / "frozen"
    / "v2.1"
    / "10_PLATFORM_v2.1"
    / "03_NORMATIVE_V2_1_CONTRACTS"
    / "NeX_Platform_v2.1_Controlled_Amendment_Batch02_CP02_CP06"
    / "WC"
)

PAIRS = (
    ("p7-work-item-v2.1.schema.json", "p7-work-item-v2.1.json"),
    ("p7-routing-decision-v2.1.schema.json", "p7-routing-decision-v2.1.json"),
    (
        "p7-claim-execution-handoff-v2.1.schema.json",
        "p7-claim-execution-handoff-v2.1.json",
    ),
    ("p7-work-result-v2.1.schema.json", "p7-work-result-v2.1.json"),
    (
        "p7-work-result-submitted-v2.1.schema.json",
        "p7-work-result-submitted-v2.1.json",
    ),
    ("p7-delegation-spec-v1.schema.json", "p7-delegation-spec-v1.json"),
    ("p7-wait-registration-v1.schema.json", "p7-wait-registration-v1.json"),
)

FROZEN_EXTRACTS = (
    ("work-item-v2.1.schema.json", "p7-work-item-v2.1.schema.json"),
    ("routing-decision-v2.1.schema.json", "p7-routing-decision-v2.1.schema.json"),
    (
        "claim-execution-handoff-v2.1.schema.json",
        "p7-claim-execution-handoff-v2.1.schema.json",
    ),
    ("work-result-v2.1.schema.json", "p7-work-result-v2.1.schema.json"),
    (
        "work-result-submitted-event-v2.1.schema.json",
        "p7-work-result-submitted-v2.1.schema.json",
    ),
)

NEGATIVE_PAIRS = (
    (
        "p7-work-item-v2.1.schema.json",
        "p7-work-item-pa-missing-project.json",
    ),
    (
        "p7-routing-decision-v2.1.schema.json",
        "p7-routing-agent-type-mismatch.json",
    ),
    (
        "p7-delegation-spec-v1.schema.json",
        "p7-delegation-actual-assignee.json",
    ),
    (
        "p7-wait-registration-v1.schema.json",
        "p7-wait-resume-job-missing.json",
    ),
)

FROZEN_DIGESTS = {
    "002_wc_work_result_v2_1.sql": (
        "9eaaae64d31065cfc73f3e666a4ee98ef2baa469b492ca732f135faaa1df20eb"
    ),
    "claim-execution-handoff-v2.1.schema.json": (
        "3f7614fdd5fb2f0ba506281581b7a5158c5a6d92cac50cd61ac9ba6ed6d2f138"
    ),
    "routing-decision-v2.1.schema.json": (
        "ace386dff6039213885ebd163eda6f65655f8e81a650639244de91a0ced9870e"
    ),
    "wc_protocols_v2_1.py": (
        "6701e1a2653d9a21ea40aa6e94fee09176dce6e7f693f02c9d7a5d00fb65aed4"
    ),
    "work-item-v2.1.schema.json": (
        "ee027300754a6aa34706d612fd73a5d4d7edd51b625987bf3be7abd5f4473ff9"
    ),
    "work-result-submitted-event-v2.1.schema.json": (
        "0015acf1fe492424a7dad1bb99a759bb3bd78e577435fbfc9dee55f55df56c1b"
    ),
    "work-result-v2.1.schema.json": (
        "4364f1840327146ca34c69589fd66e6d17789ce20ef0d50f78859a9ce0d49ff9"
    ),
}

PRIVATE_KEYS = {
    "api_key",
    "authorization",
    "credential",
    "password",
    "provider_endpoint",
    "raw_prompt",
    "secret",
    "token",
}


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(schema_name: str) -> Draft202012Validator:
    schema = _load(CONTRACTS / schema_name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in _all_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _all_keys(child)}
    return set()


@pytest.mark.parametrize(("schema_name", "example_name"), PAIRS)
def test_p7_transition_schemas_and_golden_examples_validate(
    schema_name: str, example_name: str
) -> None:
    _validator(schema_name).validate(_load(EXAMPLES / example_name))


@pytest.mark.parametrize(("schema_name", "fixture_name"), NEGATIVE_PAIRS)
def test_p7_negative_fixtures_fail_closed(
    schema_name: str, fixture_name: str
) -> None:
    with pytest.raises(ValidationError):
        _validator(schema_name).validate(_load(NEGATIVE / fixture_name))


@pytest.mark.parametrize(("frozen_name", "transition_name"), FROZEN_EXTRACTS)
def test_p7_frozen_contract_extracts_are_byte_identical(
    frozen_name: str, transition_name: str
) -> None:
    assert (FROZEN_WC / frozen_name).read_bytes() == (
        CONTRACTS / transition_name
    ).read_bytes()


@pytest.mark.parametrize(("name", "expected_digest"), FROZEN_DIGESTS.items())
def test_p7_frozen_source_digest_is_pinned(name: str, expected_digest: str) -> None:
    assert hashlib.sha256((FROZEN_WC / name).read_bytes()).hexdigest() == expected_digest


def test_p7_frozen_contract_semantic_lineage_rules_fail_closed() -> None:
    handoff = _load(EXAMPLES / "p7-claim-execution-handoff-v2.1.json")
    invalid_handoff = copy.deepcopy(handoff)
    invalid_handoff.pop("assignment_ref")
    with pytest.raises(ValidationError):
        _validator("p7-claim-execution-handoff-v2.1.schema.json").validate(
            invalid_handoff
        )

    result = _load(EXAMPLES / "p7-work-result-v2.1.json")
    invalid_result = copy.deepcopy(result)
    invalid_result.pop("claim_ref")
    with pytest.raises(ValidationError):
        _validator("p7-work-result-v2.1.schema.json").validate(invalid_result)

    event = _load(EXAMPLES / "p7-work-result-submitted-v2.1.json")
    invalid_event = copy.deepcopy(event)
    invalid_event.pop("source_execution_ref")
    with pytest.raises(ValidationError):
        _validator("p7-work-result-submitted-v2.1.schema.json").validate(
            invalid_event
        )


def test_p7_result_event_matches_wait_external_identity() -> None:
    event = _load(EXAMPLES / "p7-work-result-submitted-v2.1.json")
    wait = _load(EXAMPLES / "p7-wait-registration-v1.json")

    assert event["resume_match_ref"] == event["work_item_id"]
    assert wait["external_ref"] == event["work_item_id"]
    assert wait["matched_event_id"] == event["event_id"]


def test_p7_delegation_contract_excludes_allocated_authority() -> None:
    schema = _load(CONTRACTS / "p7-delegation-spec-v1.schema.json")
    fields = set(schema["properties"])

    assert fields.isdisjoint(
        {
            "actual_assignee_ref",
            "agent_execution_id",
            "assignment_ref",
            "authorization_decision",
            "claim_generation",
            "claim_ref",
            "lease_token",
        }
    )
    assert schema["additionalProperties"] is False


def test_p7_golden_fixtures_exclude_secrets_and_provider_configuration() -> None:
    for _, example_name in PAIRS:
        assert _all_keys(_load(EXAMPLES / example_name)).isdisjoint(PRIVATE_KEYS)


def test_p7_common_job_queue_reuse_is_idempotent_and_reference_only() -> None:
    queue = InMemoryJobQueue()
    job = build_common_job(
        job_id="wc-job-001",
        job_type="WC_EVENT_DELIVERY",
        trace_id="corr-p7-golden-001",
        request_id="request-p7-golden-001",
        subject_ref=build_subject_ref("WC_OUTBOX", "outbox-p7-golden-001"),
        idempotency_key="event-p7-golden-001",
        created_at="2026-10-18T01:00:00Z",
        max_attempts=5,
    )
    job["payload"] = {
        "outbox_id": "outbox-p7-golden-001",
        "event_id": "event-p7-golden-001",
    }

    first = queue.enqueue(job)
    duplicate = queue.enqueue({**job, "job_id": "wc-job-duplicate"})
    running = queue.claim_next_job(
        "wc-outbox-worker-001",
        job_type="WC_EVENT_DELIVERY",
        updated_at="2026-10-18T01:00:01Z",
    )
    assert running is not None
    retried = queue.retry_job(
        running["job_id"],
        error=build_job_error(
            error_code="wc.event_delivery_timeout",
            detail="delivery timed out",
            retryable=True,
        ),
        failed_at="2026-10-18T01:00:02Z",
        policy=JobRetryPolicy(initial_delay_seconds=1, max_delay_seconds=2),
    )

    assert first["job_id"] == duplicate["job_id"] == "wc-job-001"
    assert first["subject_ref"] == {
        "type": "WC_OUTBOX",
        "id": "outbox-p7-golden-001",
    }
    assert set(first["payload"]) == {"outbox_id", "event_id"}
    assert _all_keys(first["payload"]).isdisjoint(PRIVATE_KEYS)
    assert retried["status"] == "QUEUED"
    assert retried["attempt_count"] == 1


def test_p7_closure_freezes_reuse_authority_and_inactive_vocabulary() -> None:
    closure = (
        P7 / "P7_CA01_Source_Backed_WC_Background_Agent_Contract_Closure_v1.0.md"
    ).read_text(encoding="utf-8")

    for decision in range(1, 18):
        assert f"P7-CA01-DEC-{decision:02d}" in closure
    for required_text in (
        "WC_EVENT_DELIVERY",
        "InMemoryJobQueue / SqlAlchemyJobQueue",
        "WorkItemId != ClaimId != AssignmentId != OutboxId != EventId",
        "RESUME_EXECUTION",
        "ACKNOWLEDGED",
        "HUMAN candidate/assignee",
        "EXTERNAL_AGENT candidate/assignee",
        "P7-CA01 is closed. P7-S1 is authorized.",
    ):
        assert required_text in closure


def test_p7_current_source_has_distinct_common_and_agent_runtime_queues() -> None:
    common_jobs = (ROOT / "services/_shared/nex_runtime/jobs.py").read_text(
        encoding="utf-8"
    )
    runtime_jobs = (
        ROOT / "services/nex-ae-api/nex_ae_api/runtime_jobs.py"
    ).read_text(encoding="utf-8")

    assert "class SqlAlchemyJobQueue" in common_jobs
    assert "class InMemoryJobQueue" in common_jobs
    assert "class SqlAlchemyRuntimeJobQueue" in runtime_jobs
    assert 'P4_RUNTIME_JOB_TYPES = frozenset({"START_EXECUTION", "CONTINUE_EXECUTION"})' in runtime_jobs


def test_p7_wc_does_not_define_a_second_generic_job_queue() -> None:
    wc_source = ROOT / "services" / "nex-wc"
    if not wc_source.exists():
        return

    forbidden = (
        "class InMemoryJobQueue",
        "class SqlAlchemyJobQueue",
        "class JobRetryPolicy",
        "def plan_job_retry(",
        "def plan_dead_letter_replay(",
    )
    for path in wc_source.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path} duplicates shared runtime token {token}"
