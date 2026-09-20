from __future__ import annotations

from nex_cx.private_payload_boundary import (
    CX_PRIVATE_PAYLOAD_DECISIONS,
    build_cx_private_payload_boundary_decision,
)
import run_cx_private_payload_boundary_decision as runner


def test_private_payload_decision_classifies_all_payloads() -> None:
    decision = build_cx_private_payload_boundary_decision()

    assert decision["decision_status"] == "FROZEN"
    assert decision["summary"] == {
        "payload_count": 6,
        "durable_count": 1,
        "reconstructable_count": 1,
        "adapter_required_count": 4,
        "adapter_required_payloads": [
            "chunk_texts",
            "embedding_vectors",
            "summary_texts",
            "summary_embedding_vectors",
        ],
    }
    assert decision["next_requirement"] == "S92"
    assert decision["policies"]["owner_scope_policy"].startswith("authorize")


def test_private_payload_decision_returns_detached_records() -> None:
    decision = build_cx_private_payload_boundary_decision()
    decision["payloads"][0]["durability_status"] = "MUTATED"

    fresh = build_cx_private_payload_boundary_decision()

    assert fresh["payloads"][0]["durability_status"] == "DURABLE"
    assert CX_PRIVATE_PAYLOAD_DECISIONS[0]["durability_status"] == "DURABLE"


def test_boundary_runner_passes_and_summary_is_bounded() -> None:
    result = runner.run_cx_private_payload_boundary_decision()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["failure_code"] is None
    assert runner.summary_line(result) == (
        "cx_private_payload_boundary=pass payloads=6 durable=1 "
        "reconstructable=1 adapter_required=4"
    )
    assert runner.summary_line({"status": "FAIL"}) == (
        "cx_private_payload_boundary=fail payloads=0 durable=0 "
        "reconstructable=0 adapter_required=0"
    )


def test_boundary_runner_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_cx_private_payload_boundary_decision()
    monkeypatch.setattr(
        runner,
        "run_cx_private_payload_boundary_decision",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"decision_status": "FROZEN"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_cx_private_payload_boundary_decision",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
