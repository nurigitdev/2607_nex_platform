from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from .nsl_runtime_bundle import NslRuntimeBundle
from .semantic_hashes import canonical_json, nsl_write_payload_hash_ref


class NslRuntimeAdapterError(RuntimeError):
    pass


def decode_nsl_document(value: Mapping[str, Any]) -> Any:
    """Keep installed NSL representation decoding behind the runtime adapter."""

    from nsl.core import decode_value

    return decode_value(deepcopy(dict(value)))


@dataclass(frozen=True)
class NslExecutionBinding:
    input_document: Mapping[str, Any]
    principal_document: Mapping[str, Any]
    handlers: Mapping[str, Callable[[Mapping[str, Any]], Any]]
    write_tool_id: str
    write_tool_version: str
    precondition_evidence_ref: str
    provider_guarantee_ref: str = "eos:idempotency:product"

    def __post_init__(self) -> None:
        for value, label in (
            (self.write_tool_id, "write_tool_id"),
            (self.write_tool_version, "write_tool_version"),
            (self.precondition_evidence_ref, "precondition_evidence_ref"),
            (self.provider_guarantee_ref, "provider_guarantee_ref"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise NslRuntimeAdapterError(f"{label} must be a non-empty string.")
        if not isinstance(self.input_document, Mapping):
            raise NslRuntimeAdapterError("NSL input document must be an object.")
        if not isinstance(self.principal_document, Mapping):
            raise NslRuntimeAdapterError("NSL principal document must be an object.")
        if not isinstance(self.handlers, Mapping) or not self.handlers:
            raise NslRuntimeAdapterError("NSL Tool handlers are unavailable.")
        if any(not callable(handler) for handler in self.handlers.values()):
            raise NslRuntimeAdapterError("NSL Tool handlers must be callable.")


class InstalledNslPackage:
    """Exact admitted Skill package without scenario or fixture ownership."""

    def __init__(
        self,
        bundle: NslRuntimeBundle,
        skill_root: Path,
        state_root: Path,
    ) -> None:
        from nsl.cli import _load_program
        from nsl.cli_config import load_tool_catalog

        self.bundle = bundle
        self.skill_root = skill_root
        self.state_root = state_root
        self.catalog = load_tool_catalog(skill_root / "tools.json")
        skill_sources = sorted(skill_root.glob("*.ns"))
        if len(skill_sources) != 1:
            raise NslRuntimeAdapterError(
                "Installed NSL package requires exactly one Skill source."
            )
        self.skill = _load_program(skill_sources[0], self.catalog)
        if (
            self.skill.skill_id != bundle.skill_id
            or self.skill.skill_version != bundle.skill_version
            or self.skill.semantic_hash != bundle.skill_semantic_hash
        ):
            raise NslRuntimeAdapterError(
                "Installed Skill identity differs from the admitted bundle."
            )

    def execution(
        self,
        *,
        tenant_id: str,
        agent_execution_id: str,
        executable_step_id: str,
        nsl_execution_id: str,
        business_operation_id: str,
        binding: NslExecutionBinding,
    ) -> InstalledNslExecution:
        return InstalledNslExecution(
            package=self,
            tenant_id=tenant_id,
            agent_execution_id=agent_execution_id,
            executable_step_id=executable_step_id,
            nsl_execution_id=nsl_execution_id,
            business_operation_id=business_operation_id,
            binding=binding,
        )


class InstalledNslExecution:
    def __init__(
        self,
        *,
        package: InstalledNslPackage,
        tenant_id: str,
        agent_execution_id: str,
        executable_step_id: str,
        nsl_execution_id: str,
        business_operation_id: str,
        binding: NslExecutionBinding,
    ) -> None:
        from nsl.cli_config import load_principal_document
        from nsl.cli_controlled import FileControlledStatePort
        from nsl.cli_runtime import build_execution_request
        from nsl.core import BusinessOperationId, DataClassification

        self.package = package
        self.binding = binding
        self.tenant_id = _identity(tenant_id)
        self.agent_execution_id = _identity(agent_execution_id)
        self.executable_step_id = _identity(executable_step_id)
        self.nsl_execution_id = _identity(nsl_execution_id)
        self.business_operation_id = _identity(business_operation_id)
        root = (
            package.state_root
            / _path_segment(tenant_id)
            / _path_segment(agent_execution_id)
            / _path_segment(executable_step_id)
        )
        root.mkdir(parents=True, exist_ok=True)
        _write_stable_json(root / "input.json", binding.input_document)
        _write_stable_json(root / "principal.json", binding.principal_document)
        self.checkpoint_path = root / "controlled-prefix.nsc"
        self.approval_request_path = root / "approval-request.json"
        self.file_state_port = FileControlledStatePort(
            self.checkpoint_path, self.approval_request_path
        )
        self.skill = package.skill
        self.catalog = package.catalog
        self.handlers = dict(binding.handlers)
        self.principal = load_principal_document(dict(binding.principal_document))
        self.inputs = decode_nsl_document(binding.input_document)
        self.runtime_context = decode_nsl_document(
            _json_object(package.skill_root / "context.json")
        )
        self.request = build_execution_request(
            self.principal,
            nsl_execution_id,
            inputs=self.inputs,
            runtime_context=self.runtime_context,
            business_operation_id=BusinessOperationId(business_operation_id),
        )
        self.contract = package.catalog.resolve(
            binding.write_tool_id, binding.write_tool_version
        )
        self.data_classification = DataClassification.CONFIDENTIAL

    @property
    def checkpoint_version(self) -> int:
        from nsl.checkpoints import ExecutionCheckpoint

        return ExecutionCheckpoint.from_bytes(
            self.checkpoint_path.read_bytes()
        ).checkpoint_version

    async def start(self, state_port: Any) -> Any:
        from nsl.cli_controlled import start_controlled_run
        from nsl.security import RuntimeEnvironment

        return await start_controlled_run(
            skill=self.skill,
            catalog=self.catalog,
            request=self.request,
            handlers=self.handlers,
            state_port=state_port,
            environment=RuntimeEnvironment.PRODUCTION,
            fake_approval_enabled=False,
        )

    def existing_approval_request(self) -> Any | None:
        from nsl.cli_controlled import load_approval_request

        if (
            not self.checkpoint_path.is_file()
            or not self.approval_request_path.is_file()
        ):
            return None
        return load_approval_request(self.approval_request_path)

    def controlled_write_request(
        self,
        *,
        invocation: Any,
        public_api: Any,
        request_factory: Callable[..., Any],
        canonical_write_payload: Mapping[str, Any],
        authority_hash: str,
    ) -> Any:
        from nsl.audit import InMemorySnapshotStore
        from nsl.core import ApprovalRequestId, ApprovalStatus
        from nsl.replay import RecordingToolExecutor
        from nsl.runtime import RuntimeEngine
        from nsl.runtime_models import ValidationSummary
        from nsl.security import RuntimeEnvironment
        from nsl.tools import MockToolExecutor
        from nsl.validation import (
            BusinessPreconditionEvidence,
            BusinessPreconditionMechanism,
            PreWriteEvidence,
            WriteContractEvidence,
        )

        context = invocation.outcome.context
        tools = RecordingToolExecutor(
            MockToolExecutor(self.catalog, self.handlers),
            InMemorySnapshotStore(),
            self.request.data_policy,
        )
        intent = asyncio.run(
            RuntimeEngine(
                self.catalog, environment=RuntimeEnvironment.PRODUCTION
            ).prepare_controlled_write_intent(context, tools)
        )
        if str(intent.payload_hash) != nsl_write_payload_hash_ref(
            canonical_write_payload
        ):
            raise NslRuntimeAdapterError(
                "Approved NSL payload differs from the authoritative product payload."
            )
        now = datetime.now(UTC).replace(microsecond=0)
        contract_evidence = WriteContractEvidence(
            tool_id=self.contract.tool_id,
            contract_hash=self.contract.contract_hash,
            capability=self.contract.capability,
            risk_level=self.contract.risk_level,
            preconditions_supported=True,
        )
        precondition = BusinessPreconditionEvidence(
            evidence_id=f"product-authority:{authority_hash}",
            tenant_id=self.tenant_id,
            business_operation_id=context.identity.business_operation_id,
            write_node_id=intent.node_id,
            tool_id=intent.tool_id,
            contract_hash=self.contract.contract_hash,
            payload_hash=intent.payload_hash,
            write_intent_hash=intent.write_intent_hash,
            mechanism=BusinessPreconditionMechanism.ETAG,
            evidence_ref=self.binding.precondition_evidence_ref,
            observed_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(minutes=10),
            provider_atomic_enforcement=True,
        )
        execution_evidence = PreWriteEvidence(
            validation=ValidationSummary.from_checks(tuple(context.checks)),
            approval_status=ApprovalStatus.APPROVED,
            approval_evidence_valid=True,
            runtime_preflight_passed=True,
            current_policy_allowed=False,
            tool_preconditions_passed=False,
            business_preconditions_passed=False,
            intent_binding_valid=True,
            idempotency_ready=True,
            durability_ready=True,
            trust_valid=True,
            replay_live_write_allowed=True,
        )
        provider_evidence = public_api.provider_idempotency_evidence(
            tool_id=self.contract.tool_id,
            contract_hash=self.contract.contract_hash,
            retention_policy="PROVIDER_DEFINED",
            provider_guarantee_ref=self.binding.provider_guarantee_ref,
            verified_at=now - timedelta(seconds=1),
            guaranteed_until=now + timedelta(days=30),
            durable_duplicate_guarantee=True,
        )
        return request_factory(
            intent=intent,
            context=context,
            contract=self.contract,
            contract_evidence=contract_evidence,
            execution_evidence=execution_evidence,
            business_preconditions=precondition,
            approval_evidence=invocation.resume_token.approval_evidence,
            approval_request_id=ApprovalRequestId(invocation.approval_request_id),
            provider_idempotency_evidence=provider_evidence,
            invocation_id=f"ae-product-{uuid4().hex}",
            trace_refs=(
                f"trace_id:{uuid4().hex}",
                f"correlation_id:{self.agent_execution_id}",
                f"causation_id:{invocation.approval_request_id}",
            ),
            evaluated_at=now,
            required_until=now + timedelta(days=7),
            requested_at=now,
        )


def _write_stable_json(path: Path, value: Mapping[str, Any]) -> None:
    data = canonical_json(dict(value)).encode("utf-8")
    if path.exists():
        if path.read_bytes() != data:
            raise NslRuntimeAdapterError(
                f"Installed NSL runtime document collision: {path.name}"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_object(path: Path) -> dict[str, Any]:
    import json

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NslRuntimeAdapterError(
            f"JSON document is unavailable: {path.name}"
        ) from exc
    if not isinstance(value, Mapping):
        raise NslRuntimeAdapterError(f"JSON document must be an object: {path.name}")
    return dict(value)


def _identity(value: object) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise NslRuntimeAdapterError("Installed NSL identity is invalid.")
    return normalized


def _path_segment(value: object) -> str:
    normalized = _identity(value)
    if normalized in {".", ".."} or "/" in normalized:
        raise NslRuntimeAdapterError("Installed NSL state path identity is invalid.")
    return normalized
