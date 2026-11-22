from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from nex_runtime import (
    DIAGNOSTIC_EVIDENCE_MANIFEST_SCHEMA_VERSION,
    DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
    OMITTED_DIAGNOSTIC_VALUE,
    REDACTED_DIAGNOSTIC_VALUE,
    SERVICE_SPECS,
    DiagnosticEvidenceError,
    DiagnosticEvidencePolicy,
    DiagnosticEvidenceRecorder,
    build_service_app,
    diagnostic_evidence_recorder_from_environment,
    write_diagnostic_evidence_manifest,
)
from nex_runtime.diagnostic_http import (
    DiagnosticHttpEvidenceMiddleware,
    _body_projection,
    _BodyCapture,
    _first_text,
    _headers,
)

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def _environment(root: Path, **overrides: str) -> dict[str, str]:
    return {
        "NEX_DIAGNOSTIC_EVIDENCE_MODE": "LIVE_JOURNEY",
        "NEX_DIAGNOSTIC_EVIDENCE_ROOT": str(root),
        "NEX_DIAGNOSTIC_EVIDENCE_SESSION_ID": "w80-live-001",
        "NEX_DIAGNOSTIC_EVIDENCE_INCLUDE_RAW": "true",
        "NEX_DIAGNOSTIC_EVIDENCE_RETENTION_DAYS": "7",
        **overrides,
    }


def test_off_policy_is_a_noop(tmp_path: Path) -> None:
    policy = DiagnosticEvidencePolicy.from_environment({})
    recorder = DiagnosticEvidenceRecorder(
        policy, service_id="nex-ae-api", component="semantic-admission"
    )

    assert policy.enabled is False
    assert recorder.emit("semantic.start", {"raw_prompt": "not written"}) is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        (
            {"NEX_DIAGNOSTIC_EVIDENCE_MODE": "verbose"},
            "diagnostic_evidence.mode_invalid",
        ),
        (
            {
                "NEX_DIAGNOSTIC_EVIDENCE_MODE": "METADATA",
                "NEX_DIAGNOSTIC_EVIDENCE_ROOT": "",
                "NEX_DIAGNOSTIC_EVIDENCE_SESSION_ID": "session",
                "NEX_DIAGNOSTIC_EVIDENCE_INCLUDE_RAW": "false",
            },
            "diagnostic_evidence.root_required",
        ),
        (
            {"NEX_DIAGNOSTIC_EVIDENCE_INCLUDE_RAW": "false"},
            "diagnostic_evidence.raw_required",
        ),
        (
            {
                "NEX_DIAGNOSTIC_EVIDENCE_MODE": "METADATA",
                "NEX_DIAGNOSTIC_EVIDENCE_INCLUDE_RAW": "true",
            },
            "diagnostic_evidence.raw_mode_invalid",
        ),
        (
            {"NEX_DIAGNOSTIC_EVIDENCE_RETENTION_DAYS": "31"},
            "diagnostic_evidence.retention_invalid",
        ),
        (
            {"NEX_DIAGNOSTIC_EVIDENCE_SESSION_ID": "not/a/session"},
            "diagnostic_evidence.identifier_invalid",
        ),
        (
            {"NEX_DIAGNOSTIC_EVIDENCE_INCLUDE_RAW": "maybe"},
            "diagnostic_evidence.boolean_invalid",
        ),
        (
            {"NEX_DIAGNOSTIC_EVIDENCE_RETENTION_DAYS": "not-an-int"},
            "diagnostic_evidence.integer_invalid",
        ),
        (
            {"NEX_DIAGNOSTIC_EVIDENCE_RETENTION_DAYS": "0"},
            "diagnostic_evidence.integer_invalid",
        ),
    ],
)
def test_policy_rejects_unsafe_configuration(
    tmp_path: Path, overrides: dict[str, str], error_code: str
) -> None:
    environment = _environment(tmp_path, **overrides)

    with pytest.raises(DiagnosticEvidenceError) as caught:
        DiagnosticEvidencePolicy.from_environment(environment)

    assert caught.value.error_code == error_code
    assert str(caught.value)


def test_metadata_mode_omits_raw_data_and_redacts_secrets(tmp_path: Path) -> None:
    recorder = diagnostic_evidence_recorder_from_environment(
        service_id="nex-ae-api",
        component="semantic-admission",
        environ=_environment(
            tmp_path,
            NEX_DIAGNOSTIC_EVIDENCE_MODE="METADATA",
            NEX_DIAGNOSTIC_EVIDENCE_INCLUDE_RAW="false",
        ),
    )

    event = recorder.emit(
        "semantic.request.admitted",
        {
            "raw_prompt": "Project 전표를 생성해줘",
            "agent_plan": {"steps": [{"step_id": "S1"}]},
            "authorization": "Bearer should-never-survive",
            "nested": {"client_secret": "hidden", "token_count": 42},
        },
        trace_id=TRACE_ID,
        request_id="request-001",
        interaction_id="interaction-001",
        observed_at="2026-11-22T00:00:00Z",
    )

    assert event is not None
    assert event["schema_version"] == DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION
    assert event["payload"]["raw_prompt"]["value"] == OMITTED_DIAGNOSTIC_VALUE
    assert event["payload"]["agent_plan"]["value"] == OMITTED_DIAGNOSTIC_VALUE
    assert event["payload"]["authorization"] == REDACTED_DIAGNOSTIC_VALUE
    assert event["payload"]["nested"]["client_secret"] == REDACTED_DIAGNOSTIC_VALUE
    assert event["payload"]["nested"]["token_count"] == 42
    assert event["raw_payload_included"] is False
    assert event["secret_redacted_paths"] == [
        "authorization",
        "nested.client_secret",
    ]


def test_live_journey_preserves_agent_data_and_builds_hash_chain(
    tmp_path: Path,
) -> None:
    recorder = diagnostic_evidence_recorder_from_environment(
        service_id="nex-ae-api",
        component="semantic-admission",
        environ=_environment(tmp_path),
    )
    payload = {
        "raw_prompt": "NVT Project의 비용 전표를 생성해줘",
        "plan_candidate": {"goal": "post voucher", "confidence": 0.98},
        "agent_plan": {"steps": [{"step_id": "S1", "title": "validate"}]},
        "executable_plan": {"steps": [{"step_id": "S1", "executor": "LOCAL_SKILL"}]},
        "step_input": {"amount": 1000, "service_token": "never-log-this"},
        "step_output": {"status": "SUCCEEDED"},
    }

    first = recorder.emit(
        "semantic.compiled",
        payload,
        trace_id=TRACE_ID,
        agent_execution_id="execution-001",
        observed_at="2026-11-22T00:00:00Z",
    )
    second = recorder.emit(
        "runtime.step.completed",
        {"step_input": payload["step_input"], "step_output": payload["step_output"]},
        trace_id=TRACE_ID,
        agent_execution_id="execution-001",
        runtime_job_id="job-001",
        observed_at="2026-11-22T00:00:01Z",
    )

    assert first is not None and second is not None
    assert first["payload"]["raw_prompt"] == payload["raw_prompt"]
    assert first["payload"]["agent_plan"] == payload["agent_plan"]
    assert first["payload"]["executable_plan"] == payload["executable_plan"]
    assert first["payload"]["step_input"]["service_token"] == REDACTED_DIAGNOSTIC_VALUE
    assert first["raw_payload_included"] is True
    assert second["sequence"] == 2
    assert second["previous_event_sha256"] == first["event_sha256"]

    event_files = list((tmp_path / "w80-live-001").glob("*.jsonl"))
    assert len(event_files) == 1
    assert event_files[0].stat().st_mode & 0o777 == 0o600
    lines = [json.loads(line) for line in event_files[0].read_text().splitlines()]
    assert [line["sequence"] for line in lines] == [1, 2]


def test_manifest_freezes_restricted_file_inventory(tmp_path: Path) -> None:
    policy = DiagnosticEvidencePolicy.from_environment(_environment(tmp_path))
    recorder = DiagnosticEvidenceRecorder(
        policy, service_id="nex-ae-api", component="semantic-admission"
    )
    recorder.emit("semantic.start", {"raw_prompt": "원문"})

    manifest = write_diagnostic_evidence_manifest(
        policy,
        metadata={"git_commit": "abc123", "compose_digest": "sha256:compose"},
        observed_at="2026-11-22T00:01:00Z",
    )

    assert manifest["schema_version"] == DIAGNOSTIC_EVIDENCE_MANIFEST_SCHEMA_VERSION
    assert manifest["raw_payload_included"] is True
    assert manifest["secrets_forbidden"] is True
    assert manifest["files"][0]["mode"] == "0o600"
    assert manifest["files"][0]["sha256"]
    manifest_path = tmp_path / "w80-live-001" / "manifest.json"
    assert manifest_path.stat().st_mode & 0o777 == 0o600
    assert os.stat(tmp_path).st_mode & 0o777 == 0o700


def test_manifest_and_recorder_reject_incomplete_boundaries(tmp_path: Path) -> None:
    disabled = DiagnosticEvidencePolicy(mode="OFF")
    with pytest.raises(DiagnosticEvidenceError) as disabled_error:
        write_diagnostic_evidence_manifest(disabled)
    assert disabled_error.value.error_code == "diagnostic_evidence.manifest_disabled"

    missing = DiagnosticEvidencePolicy(
        mode="LIVE_JOURNEY",
        root=tmp_path,
        session_id="missing-session",
        include_raw=True,
    )
    with pytest.raises(DiagnosticEvidenceError) as missing_error:
        write_diagnostic_evidence_manifest(missing)
    assert missing_error.value.error_code == "diagnostic_evidence.session_missing"

    incomplete = DiagnosticEvidenceRecorder(
        DiagnosticEvidencePolicy(mode="LIVE_JOURNEY", include_raw=True),
        service_id="nex-ae-api",
        component="test",
    )
    with pytest.raises(DiagnosticEvidenceError) as incomplete_error:
        incomplete.emit("test.event", {})
    assert incomplete_error.value.error_code == "diagnostic_evidence.policy_incomplete"


def test_recorder_rejects_invalid_payload_and_normalizes_non_json_values(
    tmp_path: Path,
) -> None:
    recorder = diagnostic_evidence_recorder_from_environment(
        service_id="nex-ae-api",
        component="test",
        environ=_environment(tmp_path),
    )
    with pytest.raises(DiagnosticEvidenceError) as payload_error:
        recorder.emit("test.event", ["not", "an", "object"])  # type: ignore[arg-type]
    assert payload_error.value.error_code == "diagnostic_evidence.payload_invalid"

    value = object()
    event = recorder.emit(
        "test.normalized",
        {
            "binary": b"private-binary",
            "values": (b"nested", value),
        },
    )
    assert event is not None
    assert event["payload"]["binary"]["binary_size_bytes"] == len(b"private-binary")
    assert event["payload"]["values"][0]["binary_sha256"]
    assert event["payload"]["values"][1].startswith("<object object at")


def test_manifest_redacts_secret_metadata_and_replaces_prior_manifest(
    tmp_path: Path,
) -> None:
    policy = DiagnosticEvidencePolicy.from_environment(_environment(tmp_path))
    recorder = DiagnosticEvidenceRecorder(
        policy, service_id="nex-ae-api", component="test"
    )
    recorder.emit("test.event", {"raw_prompt": "kept in event"})
    first = write_diagnostic_evidence_manifest(
        policy,
        metadata={"service_token": "never", "release": "candidate"},
    )
    second = write_diagnostic_evidence_manifest(policy, metadata={"release": "final"})
    assert first["metadata"]["service_token"] == REDACTED_DIAGNOSTIC_VALUE
    assert second["metadata"] == {"release": "final"}
    assert all(item["name"] != "manifest.json" for item in second["files"])


def test_corrupt_chain_tail_is_rejected(tmp_path: Path) -> None:
    policy = DiagnosticEvidencePolicy.from_environment(_environment(tmp_path))
    recorder = DiagnosticEvidenceRecorder(
        policy, service_id="nex-ae-api", component="semantic-admission"
    )
    session = tmp_path / "w80-live-001"
    session.mkdir(mode=0o700)
    path = session / f"nex-ae-api--semantic-admission--{os.getpid()}.jsonl"
    path.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(DiagnosticEvidenceError) as caught:
        recorder.emit("semantic.start", {"raw_prompt": "원문"})

    assert caught.value.error_code == "diagnostic_evidence.chain_invalid"


@pytest.mark.parametrize(
    "tail",
    (
        {"sequence": 0, "event_sha256": "a" * 64},
        {"sequence": 1, "event_sha256": "not-a-digest"},
    ),
)
def test_semantically_invalid_chain_tail_is_rejected(
    tmp_path: Path, tail: dict[str, object]
) -> None:
    policy = DiagnosticEvidencePolicy.from_environment(_environment(tmp_path))
    recorder = DiagnosticEvidenceRecorder(
        policy, service_id="nex-ae-api", component="chain-test"
    )
    session = tmp_path / "w80-live-001"
    session.mkdir(mode=0o700)
    path = session / f"nex-ae-api--chain-test--{os.getpid()}.jsonl"
    path.write_text(json.dumps(tail) + "\n", encoding="utf-8")

    with pytest.raises(DiagnosticEvidenceError) as caught:
        recorder.emit("test.event", {})

    assert caught.value.error_code == "diagnostic_evidence.chain_invalid"


def test_blank_chain_lines_are_ignored(tmp_path: Path) -> None:
    policy = DiagnosticEvidencePolicy.from_environment(_environment(tmp_path))
    recorder = DiagnosticEvidenceRecorder(
        policy, service_id="nex-ae-api", component="blank-chain"
    )
    session = tmp_path / "w80-live-001"
    session.mkdir(mode=0o700)
    path = session / f"nex-ae-api--blank-chain--{os.getpid()}.jsonl"
    path.write_text("\n\n", encoding="utf-8")

    event = recorder.emit("test.event", {})

    assert event is not None
    assert event["sequence"] == 1


def test_live_http_exchange_captures_json_and_redacts_secrets(
    tmp_path: Path,
) -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"], environ=_environment(tmp_path))

    @app.post("/diagnostic-test")
    async def diagnostic_test(request: Request) -> dict[str, object]:
        return {"accepted": True, "received": await request.json()}

    response = TestClient(app).post(
        "/diagnostic-test?password=query-secret&mode=live",
        headers={
            "Authorization": "Bearer header-secret",
            "X-OpenBao-Token": "openbao-secret",
            "X-Request-ID": "request-http-001",
        },
        json={
            "raw_prompt": "NVT Project 전표를 등록해줘",
            "agent_plan": {"steps": [{"step_id": "S1"}]},
            "service_token": "body-secret",
        },
    )

    assert response.status_code == 200
    path = next((tmp_path / "w80-live-001").glob("*--http-api--*.jsonl"))
    event = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    payload = event["payload"]
    assert event["event_type"] == "http.exchange"
    assert event["correlation"]["request_id"] == "request-http-001"
    assert payload["request_body"]["raw_prompt"] == "NVT Project 전표를 등록해줘"
    assert payload["request_body"]["agent_plan"]["steps"][0]["step_id"] == "S1"
    assert payload["request_body"]["service_token"] == REDACTED_DIAGNOSTIC_VALUE
    assert payload["request_headers"]["authorization"] == REDACTED_DIAGNOSTIC_VALUE
    assert payload["request_headers"]["x-openbao-token"] == (REDACTED_DIAGNOSTIC_VALUE)
    assert payload["query_parameters"]["password"] == REDACTED_DIAGNOSTIC_VALUE
    assert payload["query_parameters"]["mode"] == "live"
    assert payload["response_body"]["received"]["service_token"] == (
        REDACTED_DIAGNOSTIC_VALUE
    )


def test_live_http_exchange_keeps_multipart_content_opaque(tmp_path: Path) -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"], environ=_environment(tmp_path))

    @app.post("/upload-test")
    async def upload_test(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    response = TestClient(app).post(
        "/upload-test",
        content=b"raw-private-file-content",
        headers={"Content-Type": "multipart/form-data; boundary=test"},
    )

    assert response.status_code == 200
    path = next((tmp_path / "w80-live-001").glob("*--http-api--*.jsonl"))
    event = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    request_body = event["payload"]["request_body"]
    assert request_body["raw_binary_included"] is False
    assert request_body["size_bytes"] == len(b"raw-private-file-content")
    assert (
        request_body["sha256"]
        == hashlib.sha256(b"raw-private-file-content").hexdigest()
    )
    assert "raw-private-file-content" not in path.read_text(encoding="utf-8")


def test_http_body_projection_covers_structured_malformed_and_truncated_data() -> None:
    empty = _BodyCapture(10)
    assert _body_projection(empty, "application/json") is None

    malformed_json = _BodyCapture(20)
    malformed_json.append(b"{bad-json")
    assert (
        _body_projection(malformed_json, "application/json")[
            "malformed_structured_body"
        ]
        is True
    )

    form = _BodyCapture(50)
    form.append(b"item=one&item=two&blank=")
    assert _body_projection(form, "application/x-www-form-urlencoded") == {
        "item": ["one", "two"],
        "blank": "",
    }

    malformed_form = _BodyCapture(10)
    malformed_form.append(b"\xff")
    assert (
        _body_projection(malformed_form, "application/x-www-form-urlencoded")[
            "malformed_structured_body"
        ]
        is True
    )

    text = _BodyCapture(20)
    text.append("정상 텍스트".encode())
    assert _body_projection(text, "text/plain") == "정상 텍스트"

    malformed_text = _BodyCapture(10)
    malformed_text.append(b"\xff")
    assert (
        _body_projection(malformed_text, "text/plain")["malformed_structured_body"]
        is True
    )

    truncated = _BodyCapture(3)
    truncated.append(b"12345")
    truncated.append(b"6")
    projection = _body_projection(truncated, "application/json")
    assert projection["truncated"] is True
    assert projection["size_bytes"] == 6
    assert projection["raw_binary_included"] is False

    binary = _BodyCapture(10)
    binary.append(b"binary")
    assert (
        _body_projection(binary, "application/octet-stream")["raw_binary_included"]
        is False
    )


def test_http_helpers_handle_duplicate_headers_and_missing_correlation() -> None:
    assert _headers(((b"x-value", b"one"), (b"x-value", b"two"))) == {
        "x-value": "one, two"
    }
    assert _first_text(None, 3, "", "  request-1  ") == "request-1"
    assert _first_text(None, "") is None


def test_http_middleware_rejects_invalid_capture_limit() -> None:
    async def app(_scope: object, _receive: object, _send: object) -> None:
        return None

    recorder = DiagnosticEvidenceRecorder(
        DiagnosticEvidencePolicy(mode="OFF"),
        service_id="nex-ae-api",
        component="http-api",
    )
    with pytest.raises(ValueError, match="capture_limit_bytes"):
        DiagnosticHttpEvidenceMiddleware(app, recorder=recorder, capture_limit_bytes=0)


def test_live_http_exchange_records_application_failure(tmp_path: Path) -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"], environ=_environment(tmp_path))

    @app.post("/failing-test")
    async def failing_test() -> None:
        raise RuntimeError("private exception detail")

    response = TestClient(app, raise_server_exceptions=False).post("/failing-test")

    assert response.status_code == 500
    path = next((tmp_path / "w80-live-001").glob("*--http-api--*.jsonl"))
    event = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["payload"]["application_error_type"] == "RuntimeError"
    assert "private exception detail" not in path.read_text(encoding="utf-8")


def test_off_http_middleware_bypasses_non_http_scope() -> None:
    calls: list[str] = []

    async def app(scope: object, _receive: object, _send: object) -> None:
        calls.append(str(scope))

    async def receive() -> dict[str, object]:
        return {"type": "websocket.receive"}

    async def send(_message: object) -> None:
        return None

    recorder = DiagnosticEvidenceRecorder(
        DiagnosticEvidencePolicy(mode="OFF"),
        service_id="nex-ae-api",
        component="http-api",
    )
    middleware = DiagnosticHttpEvidenceMiddleware(app, recorder=recorder)
    asyncio.run(middleware({"type": "websocket"}, receive, send))

    assert calls == ["{'type': 'websocket'}"]


def test_live_http_middleware_tolerates_non_body_asgi_messages(tmp_path: Path) -> None:
    async def app(
        _scope: object,
        receive: object,
        send: object,
    ) -> None:
        assert callable(receive) and callable(send)
        assert await receive() == {"type": "http.disconnect"}
        await send({"type": "custom.message"})

    async def receive() -> dict[str, object]:
        return {"type": "http.disconnect"}

    sent: list[object] = []

    async def send(message: object) -> None:
        sent.append(message)

    recorder = diagnostic_evidence_recorder_from_environment(
        service_id="nex-ae-api",
        component="http-api",
        environ=_environment(tmp_path),
    )
    middleware = DiagnosticHttpEvidenceMiddleware(app, recorder=recorder)
    asyncio.run(
        middleware(
            {
                "type": "http",
                "method": "GET",
                "path": "/disconnect",
                "query_string": b"",
                "headers": (),
            },
            receive,
            send,
        )
    )

    assert sent == [{"type": "custom.message"}]
