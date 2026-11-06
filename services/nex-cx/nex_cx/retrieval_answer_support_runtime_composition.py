from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nex_runtime import OperationalEventEmitter, OperationalEventStore

from nex_cx.hybrid_retrieval_package import (
    HybridRetrievalPrimaryPolicy,
    HybridRetrievalShadowObserver,
)
from nex_cx.retrieval_answer_support_controlled_activation import (
    OperationalAnswerSupportProgressSink,
    OperationalRuntimeActivationStateStore,
    build_installed_controlled_answer_support_runtime,
)
from nex_cx.retrieval_answer_support_limited_operations import (
    DEFAULT_POLICY_PATH,
    LIMITED_OPERATIONS_POLICY_PATH_ENV,
    OperationalLimitedShadowSource,
    build_installed_limited_shadow_operations_runtime,
    load_limited_operations_policy,
)
from nex_cx.retrieval_answer_support_policy_cutover import (
    OperationalPolicyCutoverStateStore,
    build_installed_answer_support_policy_cutover,
)
from nex_cx.retrieval_answer_support_policy_cutover_operations import (
    OperationalPolicyCutoverDecisionSink,
    build_installed_policy_cutover_operations_source,
)
from nex_cx.retrieval_answer_support_policy_steady_state import (
    OperationalSteadyStateStateStore,
    build_installed_answer_support_policy_steady_state,
)
from nex_cx.retrieval_answer_support_policy_steady_state_operations import (
    build_installed_policy_steady_state_operations_source,
)
from nex_cx.retrieval_answer_support_policy_sustained_operations import (
    build_installed_policy_sustained_operations_source,
)
from nex_cx.retrieval_answer_support_shadow_runtime import (
    AnswerSupportGenerationClient,
)
from nex_cx.retrieval_observability import OperationalAnswerSupportShadowSink


@dataclass(frozen=True)
class InstalledAnswerSupportRuntimeComposition:
    primary_policy: HybridRetrievalPrimaryPolicy | None
    shadow_observer: HybridRetrievalShadowObserver | None
    policy_cutover: Any
    steady_state_policy: Any
    limited_runtime: Any
    operations_source: Any
    cutover_operations_source: Any
    sustained_operations_source: Any
    steady_state_operations_source: Any

    @property
    def retrieval_shadow_observer(self) -> HybridRetrievalShadowObserver | None:
        return self.limited_runtime or self.shadow_observer

    def safe_snapshot(self) -> dict[str, Any]:
        primary = (
            dict(self.primary_policy.snapshot())
            if self.primary_policy is not None
            else None
        )
        return {
            "primary_policy_installed": self.primary_policy is not None,
            "steady_state_policy_installed": self.steady_state_policy is not None,
            "cutover_policy_installed": self.policy_cutover is not None,
            "shadow_observer_installed": self.retrieval_shadow_observer is not None,
            "selected_policy_hash": (
                primary.get("selected_policy_hash") if primary is not None else None
            ),
            "steady_state_state": (
                primary.get("steady_state_state") if primary is not None else None
            ),
            "steady_state_reason_code": (
                primary.get("steady_state_reason_code")
                if primary is not None
                else None
            ),
            "cutover_state": (
                primary.get("cutover_state") if primary is not None else None
            ),
            "cutover_reason_code": (
                primary.get("cutover_reason_code")
                if primary is not None
                else None
            ),
        }


def build_installed_answer_support_runtime_composition(
    *,
    environ: Mapping[str, str],
    generation_client: AnswerSupportGenerationClient,
    emitter: OperationalEventEmitter,
    store: OperationalEventStore,
) -> InstalledAnswerSupportRuntimeComposition:
    activation_state_store = OperationalRuntimeActivationStateStore(
        emitter=emitter,
        store=store,
    )
    outcome_sink = OperationalAnswerSupportShadowSink(emitter)
    progress_sink = OperationalAnswerSupportProgressSink(emitter)
    decision_sink = OperationalPolicyCutoverDecisionSink(emitter)
    policy_cutover = build_installed_answer_support_policy_cutover(
        environ=environ,
        generation_client=generation_client,
        progress_sink=progress_sink,
        outcome_sink=outcome_sink,
        state_store=OperationalPolicyCutoverStateStore(
            emitter=emitter,
            store=store,
        ),
        decision_sink=decision_sink,
    )
    steady_state_policy = build_installed_answer_support_policy_steady_state(
        environ=environ,
        delegate=policy_cutover,
        state_store=OperationalSteadyStateStateStore(
            emitter=emitter,
            store=store,
        ),
    )
    primary_policy = steady_state_policy or policy_cutover
    cutover_operations_source = build_installed_policy_cutover_operations_source(
        environ=environ,
        store=store,
        emitter=emitter,
        runtime_snapshot=lambda: (
            primary_policy.snapshot() if primary_policy is not None else None
        ),
    )
    sustained_operations_source = build_installed_policy_sustained_operations_source(
        environ=environ,
        store=store,
        emitter=emitter,
        runtime_snapshot=lambda: (
            primary_policy.snapshot() if primary_policy is not None else None
        ),
    )
    steady_state_operations_source = (
        build_installed_policy_steady_state_operations_source(
            environ=environ,
            store=store,
            emitter=emitter,
            runtime_snapshot=lambda: (
                steady_state_policy.snapshot()
                if steady_state_policy is not None
                else None
            ),
        )
    )
    shadow_observer = (
        None
        if primary_policy is not None
        else build_installed_controlled_answer_support_runtime(
            environ=environ,
            generation_client=generation_client,
            progress_sink=progress_sink,
            outcome_sink=outcome_sink,
            state_store=activation_state_store,
        )
    )
    limited_runtime = (
        None
        if policy_cutover is not None
        else build_installed_limited_shadow_operations_runtime(
            environ=environ,
            controlled_runtime=shadow_observer,
            store=store,
            outcome_sink=outcome_sink,
        )
    )
    operations_source = (
        limited_runtime.source
        if limited_runtime is not None
        else OperationalLimitedShadowSource(
            store=store,
            policy=load_limited_operations_policy(
                Path(
                    environ.get(
                        LIMITED_OPERATIONS_POLICY_PATH_ENV,
                        str(DEFAULT_POLICY_PATH),
                    )
                )
            ),
            runtime_snapshot=lambda: (
                shadow_observer.snapshot() if shadow_observer is not None else None
            ),
        )
    )
    return InstalledAnswerSupportRuntimeComposition(
        primary_policy=primary_policy,
        shadow_observer=shadow_observer,
        policy_cutover=policy_cutover,
        steady_state_policy=steady_state_policy,
        limited_runtime=limited_runtime,
        operations_source=operations_source,
        cutover_operations_source=cutover_operations_source,
        sustained_operations_source=sustained_operations_source,
        steady_state_operations_source=steady_state_operations_source,
    )
