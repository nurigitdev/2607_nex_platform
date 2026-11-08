from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def test_agent_transition_tests_use_owner_first_namespace() -> None:
    legacy_phase_first = sorted(TESTS.glob("test_p[0-9]*_*.py"))

    assert legacy_phase_first == []
    for phase in (4, 5, 6):
        assert sorted(TESTS.glob(f"test_ae_p{phase}_*.py"))
