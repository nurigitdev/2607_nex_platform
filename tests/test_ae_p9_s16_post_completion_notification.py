from __future__ import annotations

import json
from urllib.error import HTTPError, URLError

import pytest
from nex_ae_api.wa_completion_notifications import (
    AeWaPostCompletionNotifier,
    HttpWaEvidenceIntakeClient,
    build_ae_wa_post_completion_notifier,
)
from nex_ae_api.wa_source_projections import WaSourceProjectionError
from test_ae_p9_s11_agent_result_projection import (
    RESULT_ID,
    TENANT,
    _aggregate,
    _Source,
)
from test_ae_p9_s12_artifact_projection import VERSION_ID, _record


class _Client:
    def __init__(self, *, fail: bool = False, reused: bool = False) -> None:
        self.fail = fail
        self.reused = reused
        self.payloads: list[dict] = []

    def admit(self, payload):
        self.payloads.append(dict(payload))
        if self.fail:
            raise TimeoutError("offline")
        return {
            "status": "QUEUED",
            "idempotent_reuse": self.reused,
            "source_type": payload["source_type"],
            "source_ref": payload["source_ref"],
            "source_revision_ref": payload["source_revision_ref"],
        }


class _ErrorSource:
    def __init__(self, retryable: bool) -> None:
        self.retryable = retryable

    def get_projection(self, **_kwargs):
        raise WaSourceProjectionError("source.failed", "failed", self.retryable)


def test_agent_notification_waits_for_the_authoritative_completion_barrier() -> None:
    client = _Client()
    pending = AeWaPostCompletionNotifier(
        client,
        agent_results=_Source(_aggregate(acknowledged=False)),
    ).notify_agent_result(tenant_id=TENANT, result_id=RESULT_ID)
    assert pending.status == "NOT_READY"
    assert client.payloads == []

    completed = AeWaPostCompletionNotifier(
        client,
        agent_results=_Source(_aggregate(acknowledged=True)),
    ).notify_agent_result(tenant_id=TENANT, result_id=RESULT_ID)
    assert completed.status == "ACCEPTED"
    assert client.payloads == [
        {
            "schema_version": "wa_evidence_intake_request.v1",
            "tenant_id": TENANT,
            "source_type": "AE_AGENT_RESULT",
            "source_ref": "22222222-2222-4222-8222-222222222222",
            "source_revision_ref": RESULT_ID,
            "source_hash": "sha256:" + "a" * 64,
            "occurred_at": "2026-10-28T00:00:00Z",
            "correlation_id": "22222222-2222-4222-8222-222222222222",
        }
    ]


def test_duplicate_and_restart_notifications_keep_one_semantic_identity() -> None:
    client = _Client(reused=True)
    notifier = AeWaPostCompletionNotifier(
        client,
        agent_results=_Source(_aggregate(acknowledged=True, agent_type="PA")),
    )
    first = notifier.notify_agent_result(tenant_id=TENANT, result_id=RESULT_ID)
    restarted = notifier.notify_agent_result(tenant_id=TENANT, result_id=RESULT_ID)
    assert first.status == restarted.status == "REUSED"
    assert client.payloads[0] == client.payloads[1]


def test_notification_failure_is_retryable_and_source_missing_is_not_ready() -> None:
    failed = AeWaPostCompletionNotifier(
        _Client(fail=True),
        agent_results=_Source(_aggregate(acknowledged=True)),
    ).notify_agent_result(tenant_id=TENANT, result_id=RESULT_ID)
    assert (failed.status, failed.retryable, failed.detail) == (
        "RETRY_PENDING",
        True,
        "TimeoutError",
    )
    missing = AeWaPostCompletionNotifier(
        _Client(), agent_results=_Source(None)
    ).notify_agent_result(tenant_id=TENANT, result_id=RESULT_ID)
    assert missing.status == "NOT_READY"


@pytest.mark.parametrize("retryable", [False, True])
def test_typed_projection_failure_is_preserved(retryable) -> None:
    outcome = AeWaPostCompletionNotifier(
        _Client(), agent_results=_ErrorSource(retryable)
    ).notify_agent_result(tenant_id=TENANT, result_id=RESULT_ID)
    assert outcome.status == "RETRY_PENDING"
    assert outcome.retryable is retryable
    assert outcome.detail == "source.failed"


def test_ready_artifact_notification_is_reference_only() -> None:
    client = _Client()
    notifier = AeWaPostCompletionNotifier(
        client, agent_results=_Source(_aggregate(acknowledged=True))
    )
    accepted = notifier.notify_ready_artifact(
        _record(), artifact_version_id=VERSION_ID
    )
    assert accepted.status == "ACCEPTED"
    assert client.payloads[0]["source_type"] == "AE_ARTIFACT"
    assert client.payloads[0]["source_revision_ref"] == VERSION_ID
    assert "rendered_markdown" not in json.dumps(client.payloads[0])

    missing = notifier.notify_ready_artifact(
        _record(), artifact_version_id="missing-version"
    )
    assert missing.status == "NOT_READY"
    invalid = notifier.notify_ready_artifact(
        _record(status="RENDERING"), artifact_version_id=VERSION_ID
    )
    assert invalid.status == "RETRY_PENDING"
    malformed = notifier.notify_ready_artifact(None, artifact_version_id=VERSION_ID)
    assert (malformed.status, malformed.retryable) == ("RETRY_PENDING", True)


class _Response:
    def __init__(self, payload) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def _payload():
    return {
        "schema_version": "wa_evidence_intake_request.v1",
        "tenant_id": TENANT,
        "source_type": "AE_AGENT_RESULT",
        "source_ref": "execution-1",
        "source_revision_ref": "result-1",
        "source_hash": "sha256:" + "a" * 64,
        "occurred_at": "2026-10-28T00:00:00Z",
        "correlation_id": "execution-1",
    }


def test_http_intake_client_validates_ack_and_transport(monkeypatch) -> None:
    client = HttpWaEvidenceIntakeClient(
        base_url="http://wa", service_token="signed-token"
    )
    acknowledgement = {
        "status": "QUEUED",
        "source_type": "AE_AGENT_RESULT",
        "source_ref": "execution-1",
        "source_revision_ref": "result-1",
    }
    monkeypatch.setattr(
        "nex_ae_api.wa_completion_notifications.urlopen",
        lambda *_args, **_kwargs: _Response(acknowledgement),
    )
    assert client.admit(_payload())["status"] == "QUEUED"

    for response in ({"status": "FAILED"}, {**acknowledgement, "source_ref": "x"}):
        monkeypatch.setattr(
            "nex_ae_api.wa_completion_notifications.urlopen",
            lambda *_args, response=response, **_kwargs: _Response(response),
        )
        with pytest.raises(RuntimeError):
            client.admit(_payload())

    for error in (
        HTTPError("http://wa", 503, "failed", None, None),
        URLError("offline"),
    ):
        monkeypatch.setattr(
            "nex_ae_api.wa_completion_notifications.urlopen",
            lambda *_args, error=error, **_kwargs: (_ for _ in ()).throw(error),
        )
        with pytest.raises(RuntimeError):
            client.admit(_payload())
    with pytest.raises(ValueError):
        HttpWaEvidenceIntakeClient(base_url="http://wa", service_token="").admit(
            _payload()
        )


def test_factory_uses_wa_service_token_profile() -> None:
    notifier = build_ae_wa_post_completion_notifier(
        agent_results=_Source(_aggregate(acknowledged=True)),
        environ={
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
            "NEX_WA_BASE_URL": "http://wa:8108",
        },
    )
    assert isinstance(notifier, AeWaPostCompletionNotifier)
