from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINAL_BASELINE = (
    ROOT
    / "docs/transition/P9/"
    "P9_Final_AsBuilt_Baseline_and_Next_Phase_Handoff_v1.0.md"
)


def test_final_baseline_freezes_required_p9_s31_evidence() -> None:
    text = FINAL_BASELINE.read_text(encoding="utf-8")

    required = (
        "bc28307a58b659c791211d995ea773c77ef786c0",
        "0b687578bb120e68b67f0f14bb5cab9f376496cf",
        "9fdf95175cbcaf22c13fca81009ccd26c69578e9",
        "2517_oa_service_principal_wa",
        "2514_ae_nsl_v02_profile",
        "1374_cx_trace_projection_indexes",
        "1470_mo_model_rollout_persistence",
        "1477_ag_platform_alert_persistence",
        "1006_wc_approval_foundation",
        "2515_eos_worker_heartbeat",
        "2607_wa_service_logs",
        "sha256:8049b21cddf7bb761632966a9c449eb4b4c899e1baf0add19812f43cf9d56c2a",
        "18,264 passed, 131 protected skips",
        "P9.5 status                                  = DEFERRED",
        "NEXT PHASE NOT IMPLICITLY AUTHORIZED",
    )
    for value in required:
        assert value in text


def test_final_baseline_preserves_foundation_invariants() -> None:
    text = FINAL_BASELINE.read_text(encoding="utf-8")

    for invariant in (
        "WA is not a Scheduler",
        "does not read or mutate another service's database directly",
        "evidence admission is not Approval",
        "creates no WC Delegation",
        "has no NSL runtime dependency",
        "completion/publication",
        "Source equivalence",
        "Stale-worker recovery fences",
        "privacy scopes remain separate",
        "autonomous authority profiles fail closed",
    ):
        assert invariant in text


def test_p9_readme_and_compose_docs_match_the_frozen_state() -> None:
    transition_readme = (ROOT / "docs/transition/P9/README.md").read_text(
        encoding="utf-8"
    )
    compose_readme = (ROOT / "deployment/compose/README.md").read_text(
        encoding="utf-8"
    )

    assert "P9 FOUNDATION CLOSED" in transition_readme
    assert "P9_Final_AsBuilt_Baseline_and_Next_Phase_Handoff_v1.0.md" in (
        transition_readme
    )
    assert "Next phase                              = CONTROLLED DECISION REQUIRED" in (
        transition_readme
    )
    assert "P9-S27 activated `nex-wa-evidence-consumer`" in compose_readme
    assert "not represented as an active work-claiming" not in compose_readme
