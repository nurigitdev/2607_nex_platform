from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nex_runtime.demo_fixture import load_demo_business_fixture

from nex_ae_api.golden_a_approval_journey import GoldenAContextResolver
from nex_ae_api.golden_a_planning import (
    GOLDEN_A_CAPABILITY_ID,
    activate_golden_a_work_intent,
    bind_golden_a_planning_candidate,
)

P8_DEMO_GOLDEN_A_ADMISSION_ENV = "NEX_AE_DEMO_GOLDEN_A_ADMISSION_ENABLED"


@dataclass(frozen=True)
class P8DemoSemanticActivationResult:
    work_intent: Mapping[str, Any] = field(repr=False)
    context_resolver: Any = field(repr=False)


@dataclass(frozen=True)
class P8DemoGoldenAIntentActivator:
    fixture: Mapping[str, Any] = field(repr=False)

    def activate(
        self,
        *,
        candidate: Mapping[str, Any],
        work_intent: Mapping[str, Any],
        principal_id: str,
        resolved_at: str,
    ) -> P8DemoSemanticActivationResult:
        activation = bind_golden_a_planning_candidate(
            fixture=self.fixture,
            candidate=candidate,
        )
        activated = activate_golden_a_work_intent(
            work_intent,
            candidate=candidate,
            activation=activation,
        )
        return P8DemoSemanticActivationResult(
            work_intent=activated,
            context_resolver=GoldenAContextResolver(
                activation=activation,
                authority_ref=f"OA:SUBJECT:{principal_id}",
                resolved_at=resolved_at,
            ),
        )


def build_p8_demo_intent_activators(
    environ: Mapping[str, str],
) -> dict[str, P8DemoGoldenAIntentActivator]:
    if str(environ.get(P8_DEMO_GOLDEN_A_ADMISSION_ENV) or "").lower() != "true":
        return {}
    fixture_path = _required_path(environ, "NEX_AE_DEMO_FIXTURE")
    base_fixture_path = _required_path(environ, "NEX_AE_DEMO_BASE_FIXTURE")
    _, fixture = load_demo_business_fixture(
        fixture_path,
        base_fixture_path=base_fixture_path,
    )
    return {GOLDEN_A_CAPABILITY_ID: P8DemoGoldenAIntentActivator(fixture)}


def _required_path(environ: Mapping[str, str], name: str) -> Path:
    value = str(environ.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required for P8 Demo semantic activation")
    path = Path(value)
    if not path.is_file():
        raise ValueError(f"{name} is unavailable for P8 Demo semantic activation")
    return path
