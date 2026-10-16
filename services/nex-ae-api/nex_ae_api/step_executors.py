from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from nex_ae_api.chat_application import ChatApplicationService
from nex_ae_api.executable_steps import ExecutableStepError, compatibility_outcome
from nex_ae_api.multi_step_engine import (
    SqlAlchemyMultiStepEngine,
    StepExecutionContext,
    StepTerminalOutcome,
    StepWaitingOutcome,
)
from nex_ae_api.nsl_backend_profiles import normalize_nsl_backend_profile
from nex_ae_api.planning_capabilities import (
    LOCAL_SKILL_EXECUTOR_KIND,
    CapabilitySnapshotError,
    validate_local_skill_binding,
)
from nex_ae_api.runtime_jobs import RuntimeJobClaim, SqlAlchemyRuntimeJobQueue

EXECUTOR_KINDS = frozenset(
    {
        "P4_CHAT_RAG_COMPATIBILITY",
        "DETERMINISTIC_AGGREGATE",
        "DETERMINISTIC_REPORT",
    }
)
PLATFORM_EXECUTOR_KINDS = frozenset((*EXECUTOR_KINDS, "LOCAL_SKILL"))


@dataclass
class P5StepExecutorError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class P5ExecutorOutcome:
    state: Literal["WAITING", "SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"]
    result_contract_ref: str
    result_payload: Mapping[str, Any]
    external_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    error_ref: str | None = None
    retrieval_package_ref: str | None = None
    retrieval_package_hash: str | None = None
    cx_generation_id: str | None = None
    cx_job_id: str | None = None
    business_operation_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


@dataclass(frozen=True)
class P5WorkerExecution:
    disposition: Literal["WAITING", "TERMINAL", "ALREADY_TERMINAL"]
    step: dict[str, Any] | None
    step_result: dict[str, Any] | None
    runtime_job: dict[str, Any]


class P5StepExecutor(Protocol):
    def execute(
        self,
        context: StepExecutionContext,
        *,
        continuation_result: Any | None = None,
    ) -> P5ExecutorOutcome: ...


@dataclass(frozen=True)
class LocalSkillExecutorDependencies:
    artifact_gateway: object
    binding_repository: object
    request_builder: Callable[..., Mapping[str, Any]]
    backend: object
    result_mapper: Callable[..., P5ExecutorOutcome]


class P6LocalSkillExecutor:
    def __init__(
        self,
        *,
        dependencies: LocalSkillExecutorDependencies,
        handler: Callable[
            [StepExecutionContext, LocalSkillExecutorDependencies], P5ExecutorOutcome
        ],
    ) -> None:
        self._dependencies = validate_local_skill_executor_dependencies(dependencies)
        if not callable(handler):
            raise _local_skill_unavailable("LOCAL_SKILL handler is unavailable.")
        self._handler = handler

    @property
    def backend_profile(self) -> str:
        return str(self._dependencies.backend.backend_profile)

    def execute(
        self,
        context: StepExecutionContext,
        *,
        continuation_result: Any | None = None,
    ) -> P5ExecutorOutcome:
        _require_executor(context.step, LOCAL_SKILL_EXECUTOR_KIND)
        if context.step.get("step_type") != "LOCAL_SKILL":
            raise _invalid("LOCAL_SKILL executor requires a LOCAL_SKILL step.")
        if continuation_result is not None:
            raise _invalid("LOCAL_SKILL READ cannot consume continuation input in P6.")
        try:
            binding = validate_local_skill_binding(context.step.get("skill_binding"))
        except CapabilitySnapshotError as exc:
            raise _invalid("LOCAL_SKILL compiled binding is invalid.") from exc
        if binding["backend_profile"] != self.backend_profile:
            raise _local_skill_unavailable(
                "LOCAL_SKILL compiled binding has no matching configured backend."
            )
        outcome = self._handler(context, self._dependencies)
        if not isinstance(outcome, P5ExecutorOutcome):
            raise _invalid("LOCAL_SKILL handler returned an invalid outcome.")
        return outcome


def validate_local_skill_executor_dependencies(
    value: object,
) -> LocalSkillExecutorDependencies:
    if not isinstance(value, LocalSkillExecutorDependencies):
        raise _local_skill_unavailable("LOCAL_SKILL dependencies are unavailable.")
    requirements = (
        (value.artifact_gateway, "resolve_verified", "artifact gateway"),
        (value.binding_repository, "bind_request", "binding repository"),
        (value.backend, "execute", "selected backend"),
    )
    for dependency, method, label in requirements:
        if dependency is None or not callable(getattr(dependency, method, None)):
            raise _local_skill_unavailable(
                f"LOCAL_SKILL {label} dependency is unavailable."
            )
    if not callable(value.request_builder):
        raise _local_skill_unavailable(
            "LOCAL_SKILL request builder dependency is unavailable."
        )
    if not callable(value.result_mapper):
        raise _local_skill_unavailable(
            "LOCAL_SKILL result mapper dependency is unavailable."
        )
    try:
        normalize_nsl_backend_profile(getattr(value.backend, "backend_profile", None))
    except ValueError as exc:
        raise _local_skill_unavailable(
            "LOCAL_SKILL selected backend profile is unsupported."
        ) from exc
    return value


class P5CompatibilityChatExecutor:
    def __init__(
        self,
        callback: Callable[[StepExecutionContext], Any],
        *,
        application: ChatApplicationService | None = None,
    ) -> None:
        self._callback = callback
        self._application = application or ChatApplicationService()

    def execute(
        self,
        context: StepExecutionContext,
        *,
        continuation_result: Any | None = None,
    ) -> P5ExecutorOutcome:
        step = context.step
        _require_executor(step, "P4_CHAT_RAG_COMPATIBILITY")
        is_continuation = step.get("state") == "WAITING"
        if is_continuation:
            if continuation_result is None:
                raise _invalid(
                    "A waiting compatibility step requires its terminal result."
                )
            result = continuation_result
        else:
            if continuation_result is not None:
                raise _invalid(
                    "A fresh compatibility step cannot consume a continuation result."
                )
            result = self._application.create(lambda: self._callback(context))
        try:
            outcome = compatibility_outcome(
                result,
                expected_interaction_id=_required_text(
                    "legacy_interaction_id", step.get("legacy_interaction_id"), 128
                ),
            )
        except ExecutableStepError as exc:
            raise P5StepExecutorError(
                exc.error_code, exc.detail, exc.retryable
            ) from exc
        if is_continuation and outcome.state == "WAITING":
            raise _invalid("A compatibility continuation result must be terminal.")
        record = _result_record(result)
        payload = {
            "interaction_ref": outcome.result_ref,
            "status": _required_text("status", record.get("status"), 32).upper(),
            "retrieval_package_ref": outcome.retrieval_package_ref,
            "retrieval_package_hash": outcome.retrieval_package_hash,
            "cx_generation_ref": outcome.cx_generation_id,
            "cx_job_ref": outcome.cx_job_id,
            "generated_response_ref": outcome.generated_response_id,
        }
        return P5ExecutorOutcome(
            state=outcome.state,
            result_contract_ref=_required_text(
                "output_contract_ref", step.get("output_contract_ref"), 256
            ),
            result_payload={
                key: value for key, value in payload.items() if value is not None
            },
            external_refs=_external_refs(outcome),
            artifact_refs=_artifact_refs(record.get("artifact_refs", ())),
            evidence_refs=(outcome.result_ref,) if outcome.result_ref else (),
            error_ref=outcome.error_ref,
            retrieval_package_ref=outcome.retrieval_package_ref,
            retrieval_package_hash=outcome.retrieval_package_hash,
            cx_generation_id=outcome.cx_generation_id,
            cx_job_id=outcome.cx_job_id,
        )


class P5DeterministicProjectionExecutor:
    def execute(
        self,
        context: StepExecutionContext,
        *,
        continuation_result: Any | None = None,
    ) -> P5ExecutorOutcome:
        kind = str(context.step.get("executor_kind") or "")
        if kind not in {"DETERMINISTIC_REPORT", "DETERMINISTIC_AGGREGATE"}:
            raise _invalid("Deterministic projection executor kind is invalid.")
        if continuation_result is not None:
            raise _invalid("Deterministic projection cannot consume a continuation.")
        dependencies = {
            item["compiled_step_key"]: item for item in context.dependency_results
        }
        if not dependencies or any(
            item.get("status") != "SUCCEEDED" for item in dependencies.values()
        ):
            raise _invalid(
                "Deterministic projection requires successful dependency results."
            )
        bindings: dict[str, Any] = {}
        for binding in context.step.get("compiled_input_bindings", ()):
            if not isinstance(binding, Mapping):
                raise _invalid("Compiled input binding is not an object.")
            target = _required_text("target_name", binding.get("target_name"), 128)
            if target in bindings:
                raise _invalid("Compiled input binding target is duplicated.")
            bindings[target] = _resolve_binding(binding, dependencies)
        if not bindings:
            raise _invalid("Deterministic projection requires compiled input bindings.")
        dependency_values = tuple(dependencies.values())
        return P5ExecutorOutcome(
            state="SUCCEEDED",
            result_contract_ref=_required_text(
                "output_contract_ref",
                context.step.get("output_contract_ref"),
                256,
            ),
            result_payload={
                "projection_kind": (
                    "REPORT" if kind == "DETERMINISTIC_REPORT" else "AGGREGATE"
                ),
                "bindings": bindings,
            },
            external_refs=_union_refs(dependency_values, "external_refs"),
            artifact_refs=_union_refs(dependency_values, "artifact_refs"),
            evidence_refs=tuple(
                sorted(
                    {
                        *_union_refs(dependency_values, "evidence_refs"),
                        *(
                            f"AE:STEP_RESULT:{item['step_result_id']}"
                            for item in dependency_values
                        ),
                    }
                )
            ),
        )


class P5StepExecutorRegistry:
    def __init__(self, executors: Mapping[str, P5StepExecutor]) -> None:
        unknown = set(executors) - PLATFORM_EXECUTOR_KINDS
        if unknown:
            raise _invalid("Executor registry contains an unsupported kind.")
        local_skill = executors.get(LOCAL_SKILL_EXECUTOR_KIND)
        if local_skill is not None and not isinstance(
            local_skill, P6LocalSkillExecutor
        ):
            raise _local_skill_unavailable(
                "LOCAL_SKILL registry entry lacks verified dependency composition."
            )
        self._executors = dict(executors)

    @property
    def registered_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._executors))

    @property
    def backend_profiles(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    executor.backend_profile
                    for executor in self._executors.values()
                    if isinstance(executor, P6LocalSkillExecutor)
                }
            )
        )

    def execute(
        self,
        context: StepExecutionContext,
        *,
        continuation_result: Any | None = None,
    ) -> P5ExecutorOutcome:
        kind = str(context.step.get("executor_kind") or "")
        executor = self._executors.get(kind)
        if executor is None:
            raise P5StepExecutorError(
                "ae.p5_executor_unavailable",
                f"P5 executor is unavailable for {kind or 'unknown'}.",
            )
        return executor.execute(context, continuation_result=continuation_result)


class P5StepExecutionWorker:
    def __init__(
        self,
        *,
        engine: SqlAlchemyMultiStepEngine,
        jobs: SqlAlchemyRuntimeJobQueue,
        executors: P5StepExecutorRegistry,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine = engine
        self._jobs = jobs
        self._executors = executors
        self._clock = clock or (lambda: datetime.now(UTC))

    def run_claim(
        self,
        *,
        tenant_id: str,
        claim: RuntimeJobClaim,
        continuation_result: Any | None = None,
    ) -> P5WorkerExecution:
        now = self._now()
        context = self._engine.begin_claim(tenant_id=tenant_id, claim=claim, now=now)
        if context.already_terminal:
            job = self._complete(tenant_id, claim, now)
            return P5WorkerExecution(
                disposition="ALREADY_TERMINAL",
                step=context.step,
                step_result=context.existing_result,
                runtime_job=job,
            )
        try:
            outcome = self._executors.execute(
                context, continuation_result=continuation_result
            )
        except P5StepExecutorError as exc:
            error = exc
        except Exception:  # noqa: BLE001 - adapters are an untrusted boundary
            error = P5StepExecutorError(
                "ae.p5_executor_callback_failed",
                "P5 executor callback failed.",
            )
        else:
            return self._record_outcome(
                tenant_id=tenant_id,
                claim=claim,
                context=context,
                outcome=outcome,
                now=now,
            )
        return self._record_failure(
            tenant_id=tenant_id,
            claim=claim,
            context=context,
            error=error,
            now=now,
        )

    def _record_failure(
        self,
        *,
        tenant_id: str,
        claim: RuntimeJobClaim,
        context: StepExecutionContext,
        error: P5StepExecutorError,
        now: str,
    ) -> P5WorkerExecution:
        result = self._engine.record_outcome(
            tenant_id=tenant_id,
            claim=claim,
            outcome=StepTerminalOutcome(
                status="FAILED",
                result_contract_ref=_required_text(
                    "output_contract_ref",
                    context.step.get("output_contract_ref"),
                    256,
                ),
                result_payload={"failure_code": error.error_code},
                error_ref=error.error_code,
                started_at=now,
                completed_at=now,
            ),
        )
        job = self._fail(tenant_id, claim, now, error.error_code)
        return P5WorkerExecution(
            disposition="TERMINAL",
            step=context.step,
            step_result=result,
            runtime_job=job,
        )

    def _record_outcome(
        self,
        *,
        tenant_id: str,
        claim: RuntimeJobClaim,
        context: StepExecutionContext,
        outcome: P5ExecutorOutcome,
        now: str,
    ) -> P5WorkerExecution:
        if outcome.state == "WAITING":
            step = self._engine.record_waiting(
                tenant_id=tenant_id,
                claim=claim,
                outcome=StepWaitingOutcome(
                    retrieval_package_ref=outcome.retrieval_package_ref,
                    retrieval_package_hash=outcome.retrieval_package_hash,
                    cx_generation_id=outcome.cx_generation_id,
                    cx_job_id=outcome.cx_job_id,
                ),
                now=now,
            )
            job = self._complete(tenant_id, claim, now)
            return P5WorkerExecution(
                disposition="WAITING",
                step=step,
                step_result=None,
                runtime_job=job,
            )
        result = self._engine.record_outcome(
            tenant_id=tenant_id,
            claim=claim,
            outcome=StepTerminalOutcome(
                status=outcome.state,
                result_contract_ref=outcome.result_contract_ref,
                result_payload=outcome.result_payload,
                external_refs=outcome.external_refs,
                artifact_refs=outcome.artifact_refs,
                evidence_refs=outcome.evidence_refs,
                error_ref=outcome.error_ref,
                executor_kind=(
                    LOCAL_SKILL_EXECUTOR_KIND
                    if context.step.get("executor_kind") == LOCAL_SKILL_EXECUTOR_KIND
                    else None
                ),
                business_operation_id=outcome.business_operation_id,
                started_at=outcome.started_at or now,
                completed_at=outcome.completed_at or now,
            ),
        )
        job = self._complete(tenant_id, claim, now)
        return P5WorkerExecution(
            disposition="TERMINAL",
            step=context.step,
            step_result=result,
            runtime_job=job,
        )

    def _complete(
        self, tenant_id: str, claim: RuntimeJobClaim, now: str
    ) -> dict[str, Any]:
        return self._jobs.complete(
            tenant_id=tenant_id,
            runtime_job_id=claim.job["runtime_job_id"],
            worker_id=claim.job["lease_owner"],
            lease_token=claim.job["lease_token"],
            now=now,
        )

    def _fail(
        self, tenant_id: str, claim: RuntimeJobClaim, now: str, error_ref: str
    ) -> dict[str, Any]:
        return self._jobs.fail(
            tenant_id=tenant_id,
            runtime_job_id=claim.job["runtime_job_id"],
            worker_id=claim.job["lease_owner"],
            lease_token=claim.job["lease_token"],
            now=now,
            error_ref=error_ref,
        )

    def _now(self) -> str:
        return self._clock().astimezone(UTC).isoformat().replace("+00:00", "Z")


def default_p5_executor_registry(
    callback: Callable[[StepExecutionContext], Any],
) -> P5StepExecutorRegistry:
    projection = P5DeterministicProjectionExecutor()
    return P5StepExecutorRegistry(
        {
            "P4_CHAT_RAG_COMPATIBILITY": P5CompatibilityChatExecutor(callback),
            "DETERMINISTIC_REPORT": projection,
            "DETERMINISTIC_AGGREGATE": projection,
        }
    )


def default_p6_executor_registry(
    callback: Callable[[StepExecutionContext], Any],
    *,
    local_skill_dependencies: LocalSkillExecutorDependencies,
    local_skill_handler: Callable[
        [StepExecutionContext, LocalSkillExecutorDependencies], P5ExecutorOutcome
    ],
) -> P5StepExecutorRegistry:
    projection = P5DeterministicProjectionExecutor()
    return P5StepExecutorRegistry(
        {
            "P4_CHAT_RAG_COMPATIBILITY": P5CompatibilityChatExecutor(callback),
            "DETERMINISTIC_REPORT": projection,
            "DETERMINISTIC_AGGREGATE": projection,
            LOCAL_SKILL_EXECUTOR_KIND: P6LocalSkillExecutor(
                dependencies=local_skill_dependencies,
                handler=local_skill_handler,
            ),
        }
    )


def _resolve_binding(
    binding: Mapping[str, Any], dependencies: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    binding_type = binding.get("binding_type")
    if binding_type == "COMPILED_STEP_OUTPUT":
        source_ref = _required_text("source_ref", binding.get("source_ref"), 256)
        compiled_key, separator, pointer = source_ref.partition(":")
        if not separator or pointer != "$" or compiled_key not in dependencies:
            raise _invalid("Compiled step output binding cannot be resolved.")
        source = dependencies[compiled_key]
        return {
            "source_step_result_ref": f"AE:STEP_RESULT:{source['step_result_id']}",
            "source_result_hash": source["result_hash"],
            "source_contract_ref": source["result_contract_ref"],
            "value": source["result_payload"],
        }
    if binding_type == "LITERAL":
        return {"value": binding.get("value")}
    if binding_type == "RESOURCE_REF":
        return {
            "resource_ref": _required_text("source_ref", binding.get("source_ref"), 256)
        }
    raise _invalid("Compiled input binding type is unsupported.")


def _external_refs(outcome: Any) -> tuple[str, ...]:
    values = (
        ("CX:RETRIEVAL", outcome.retrieval_package_ref),
        ("CX:GENERATION", outcome.cx_generation_id),
        ("CX:JOB", outcome.cx_job_id),
        ("AE:GENERATED_RESPONSE", outcome.generated_response_id),
    )
    return tuple(sorted(f"{prefix}:{value}" for prefix, value in values if value))


def _artifact_refs(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _invalid("artifact_refs must be an array.")
    refs: set[str] = set()
    for item in value:
        if isinstance(item, str):
            ref = item
        elif isinstance(item, Mapping):
            ref = item.get("artifact_version_id") or item.get("artifact_id")
        else:
            raise _invalid("artifact_refs contains an invalid reference.")
        refs.add(f"AE:ARTIFACT:{_required_text('artifact_ref', ref, 256)}")
    return tuple(sorted(refs))


def _union_refs(
    dependencies: Sequence[Mapping[str, Any]], field: str
) -> tuple[str, ...]:
    refs: set[str] = set()
    for result in dependencies:
        value = result.get(field, ())
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise _invalid(f"Dependency {field} is not an array.")
        refs.update(_required_text(field, item, 256) for item in value)
    return tuple(sorted(refs))


def _result_record(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    body = getattr(value, "body", None)
    if isinstance(body, bytes):
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _invalid("Chat response body is not valid JSON.") from exc
        if isinstance(decoded, Mapping):
            return decoded
    raise _invalid("Chat application result is not a structured record.")


def _require_executor(step: Mapping[str, Any], expected: str) -> None:
    if step.get("executor_kind") != expected:
        raise _invalid("Executor does not match the compiled step binding.")


def _required_text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} must be a non-empty bounded string.")
    return value.strip()


def _invalid(detail: str) -> P5StepExecutorError:
    return P5StepExecutorError("ae.p5_executor_invalid", detail)


def _local_skill_unavailable(detail: str) -> P5StepExecutorError:
    return P5StepExecutorError("ae.local_skill_dependency_unavailable", detail)
