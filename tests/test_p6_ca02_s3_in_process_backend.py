from __future__ import annotations

import asyncio
import json
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import nex_ae_api.nsl_read_backends as backend_module
import pytest
from nex_ae_api.nsl_backend_profiles import NSL_V01_IN_PROCESS_BACKEND
from nex_ae_api.nsl_read_backends import (
    NSLReadBackendError,
    V01InProcessReadBackendAdapter,
    build_v01_in_process_backend,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/transition/P6/contracts/examples"
NSL_ID = "66666666-6666-4666-8666-666666666666"
NOW = "2026-10-14T07:00:00Z"
COMPLETED = datetime(2026, 10, 14, 7, 0, 1, tzinfo=UTC)


def _example(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class _Event:
    def __init__(self, value: dict[str, Any]) -> None:
        self._value = value

    def to_data(self) -> dict[str, Any]:
        return dict(self._value)


class _Progress:
    def __init__(self) -> None:
        self.events: list[_Event] = []


class _Job:
    @classmethod
    def from_data(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, dict) or value.get("execution_id") != NSL_ID:
            raise ValueError("invalid job")
        return dict(value)


class _Envelope:
    def __init__(self, value: dict[str, Any]) -> None:
        self._value = value

    def to_data(self) -> dict[str, Any]:
        return dict(self._value)


class _Worker:
    def __init__(
        self,
        progress: _Progress,
        *,
        failure: Exception | None = None,
        malformed: bool = False,
    ) -> None:
        self._progress = progress
        self._failure = failure
        self._malformed = malformed

    async def execute(self, job: dict[str, Any]) -> object:
        if self._failure is not None:
            raise self._failure
        for sequence, state in enumerate(
            ("STARTED", "SKILL_RESOLVED", "RUNNING", "COMPLETED"), start=1
        ):
            terminal = state == "COMPLETED"
            self._progress.events.append(
                _Event(
                    {
                        "format": "NEX-NSL-EXECUTION-PROGRESS",
                        "schema_version": "1.0",
                        "execution_id": job["execution_id"],
                        "sequence": sequence,
                        "state": state,
                        "skill_id": job["skill_id"],
                        "skill_version": job["skill_version"],
                        "runtime_status": "COMPLETED" if terminal else None,
                        "error_code": None,
                    }
                )
            )
        if self._malformed:
            return object()
        return _Envelope(
            {
                "format": "NEX-NSL-RUNTIME-RESULT",
                "schema_version": "1.0",
                "runtime_result": {
                    "schema_version": "1.0",
                    "execution_id": job["execution_id"],
                    "skill_id": job["skill_id"],
                    "skill_version": job["skill_version"],
                    "semantic_hash": job["expected_semantic_hash"],
                    "status": "COMPLETED",
                    "completeness": "COMPLETE",
                    "checks": [],
                    "outputs": [],
                    "resources": {
                        "tool_calls": 2,
                        "loop_iterations": 1,
                        "emitted_rows": 1,
                        "max_collection_size_seen": 3,
                    },
                    "error": None,
                },
            }
        )


class _Session:
    def __init__(self, worker: object, execution_number: int) -> None:
        self.worker = worker
        self._execution_number = execution_number

    def evidence_refs(self) -> list[str]:
        return [
            f"NSL:AUDIT:{NSL_ID}:{self._execution_number}",
            f"NSL:SNAPSHOT:{NSL_ID}:{self._execution_number}",
        ]


class _SessionFactory:
    def __init__(
        self,
        *,
        failure: Exception | None = None,
        malformed_worker: bool = False,
        malformed_envelope: bool = False,
    ) -> None:
        self.failure = failure
        self.malformed_worker = malformed_worker
        self.malformed_envelope = malformed_envelope
        self.sessions: list[_Session] = []
        self.artifact_handles: list[str] = []

    def __call__(self, artifact_handle: str, progress: _Progress) -> _Session:
        self.artifact_handles.append(artifact_handle)
        worker: object = (
            object()
            if self.malformed_worker
            else _Worker(
                progress,
                failure=self.failure,
                malformed=self.malformed_envelope,
            )
        )
        session = _Session(worker, len(self.sessions) + 1)
        self.sessions.append(session)
        return session


def _api() -> object:
    return types.SimpleNamespace(
        InMemoryProgressSink=_Progress,
        SkillExecutionJob=_Job,
        SkillExecutionWorker=_Worker,
    )


def _adapter(factory: _SessionFactory) -> V01InProcessReadBackendAdapter:
    return V01InProcessReadBackendAdapter(
        factory,
        api=_api(),
        clock=lambda: COMPLETED,
    )


def _execute(
    adapter: V01InProcessReadBackendAdapter, *, attempt_no: int = 1
) -> dict[str, Any]:
    return adapter.execute(
        request=_example("p6-golden-skill-execution-request-v1.json"),
        context_projection=_example("p6-golden-context-projection-v1.json"),
        artifact=_example("p6-golden-verified-artifact-v1.json"),
        attempt_no=attempt_no,
        started_at=NOW,
    )


def test_in_process_adapter_executes_exact_public_contract_with_fresh_sessions() -> (
    None
):
    factory = _SessionFactory()
    adapter = _adapter(factory)

    first = _execute(adapter)
    second = _execute(adapter, attempt_no=2)

    assert adapter.backend_profile == NSL_V01_IN_PROCESS_BACKEND
    assert adapter.timeout_semantics == "NSL_COOPERATIVE_DEADLINE"
    assert first["backend_profile"] == NSL_V01_IN_PROCESS_BACKEND
    assert first["isolation_status"] == "COMPLETED"
    assert first["runtime_status"] == "COMPLETED"
    assert second["attempt_no"] == 2
    assert first["nsl_execution_id"] == second["nsl_execution_id"] == NSL_ID
    assert len(factory.sessions) == 2
    assert factory.sessions[0] is not factory.sessions[1]
    assert len(set(factory.artifact_handles)) == 1
    assert [event["state"] for event in first["progress_events"]] == [
        "STARTED",
        "SKILL_RESOLVED",
        "RUNNING",
        "COMPLETED",
    ]
    assert any(ref.startswith("NSL:SNAPSHOT:") for ref in first["evidence_refs"])


@pytest.mark.parametrize(
    "factory",
    (
        _SessionFactory(failure=RuntimeError("private target failure")),
        _SessionFactory(),
    ),
)
def test_in_process_adapter_contains_target_failures(factory: _SessionFactory) -> None:
    if factory.failure is None:

        def fail_factory(*_args: object) -> _Session:
            raise RuntimeError("private session failure")

        adapter = V01InProcessReadBackendAdapter(
            fail_factory, api=_api(), clock=lambda: COMPLETED
        )
    else:
        adapter = _adapter(factory)

    record = _execute(adapter)

    assert record["backend_profile"] == NSL_V01_IN_PROCESS_BACKEND
    assert record["isolation_status"] == "TARGET_ERROR"
    assert record["error_code"] == "IN_PROCESS_RUNTIME_TARGET_ERROR"
    assert record["retryable"] is False
    assert "private" not in json.dumps(record)


@pytest.mark.parametrize(
    "factory",
    (
        _SessionFactory(malformed_worker=True),
        _SessionFactory(malformed_envelope=True),
    ),
)
def test_in_process_adapter_contains_protocol_drift(factory: _SessionFactory) -> None:
    record = _execute(_adapter(factory))

    assert record["backend_profile"] == NSL_V01_IN_PROCESS_BACKEND
    assert record["isolation_status"] == "PROTOCOL_ERROR"
    assert record["error_code"] == "IN_PROCESS_RUNTIME_PROTOCOL_ERROR"
    assert record["runtime_result_envelope"] is None


def test_in_process_adapter_rejects_nested_event_loop_without_hard_timeout() -> None:
    async def execute_inside_loop() -> dict[str, Any]:
        return _execute(_adapter(_SessionFactory()))

    record = asyncio.run(execute_inside_loop())

    assert record["isolation_status"] == "PROTOCOL_ERROR"
    assert record["error_code"] == "IN_PROCESS_RUNTIME_PROTOCOL_ERROR"


def test_in_process_builder_imports_only_the_stable_public_api(monkeypatch) -> None:
    imported: list[str] = []

    def import_module(name: str) -> object:
        imported.append(name)
        return _api()

    monkeypatch.setattr(backend_module.importlib, "import_module", import_module)
    backend = build_v01_in_process_backend(_SessionFactory(), clock=lambda: COMPLETED)

    assert backend.backend_profile == NSL_V01_IN_PROCESS_BACKEND
    assert imported == ["nsl.api"]

    monkeypatch.setattr(
        backend_module.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("missing")),
    )
    with pytest.raises(NSLReadBackendError) as missing:
        build_v01_in_process_backend(_SessionFactory())
    assert missing.value.error_code == "ae.nsl_read_backend_unavailable"


def test_in_process_adapter_configuration_fails_closed() -> None:
    with pytest.raises(NSLReadBackendError, match="factory"):
        V01InProcessReadBackendAdapter(None, api=_api())  # type: ignore[arg-type]
    with pytest.raises(NSLReadBackendError, match="public API"):
        V01InProcessReadBackendAdapter(_SessionFactory(), api=object())
