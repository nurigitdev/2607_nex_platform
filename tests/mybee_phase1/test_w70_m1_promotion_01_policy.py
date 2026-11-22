from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROMOTION = (
    ROOT
    / "docs/slices/"
    "mybee_phase1_w70_m1_promotion_01_branch_to_master_baseline.md"
)
README = ROOT / "docs/transition/MyBee_Phase1/README.md"


def test_promotion_policy_preserves_history_and_tree_identity() -> None:
    text = PROMOTION.read_text(encoding="utf-8")

    for required in (
        "source branch           = codex/mybee-phase1-implementation",
        "target branch           = master",
        "target baseline         = 9fe6ddb1",
        "merge method  = Create a merge commit (--no-ff)",
        "squash merge  = forbidden",
        "rebase merge  = forbidden",
        "merge commit has exactly two parents",
        "merge commit tree equals the source-branch tip tree",
        "origin/master` points to the merge commit",
        "no tag is moved",
    ):
        assert required in text


def test_promotion_policy_reuses_only_identical_tree_evidence() -> None:
    text = PROMOTION.read_text(encoding="utf-8")

    assert "24,031" in text
    assert "96.3353%" in text
    assert "95.3119%" in text
    assert "806 passed" in text
    assert "274 / 320 / 260 / 10" in text
    assert "byte-identical" in text
    assert "Any merge-time tree change invalidates that exemption" in text


def test_promotion_keeps_m2_open_and_hands_off_to_w80_ca01() -> None:
    text = PROMOTION.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert "M1 remains `M1_CHECKPOINT_ONLY`; M2 remains open" in text
    assert "NEXT BOUNDARY          = W80-CA01" in text
    assert "W70-M1-PROMOTION-01" in readme
    assert "mybee_phase1_w70_m1_promotion_01_branch_to_master_baseline.md" in readme
    assert "merge commit" in readme
