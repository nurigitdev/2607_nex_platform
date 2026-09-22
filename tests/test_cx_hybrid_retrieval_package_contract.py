from __future__ import annotations

import json

import run_cx_hybrid_retrieval_package_contract as contract


def test_hybrid_retrieval_package_contract_passes_without_private_payload() -> None:
    result = contract.run_cx_hybrid_retrieval_package_contract()

    assert result["status"] == "PASS"
    assert result["passed_checks"] == len(result["checks"]) == 10
    assert result["failed_checks"] == []
    assert result["package_schema_version"] == "cx_retrieval_context_package.v1"
    assert result["persistence_payload_policy"] == "hash_only_private_owner"
    assert result["postgres_required"] is False
    assert result["remote_provider_required"] is False
    serialized = json.dumps(result)
    assert contract.QUERY not in serialized
    assert contract.EVIDENCE not in serialized


def test_summary_and_cli_outputs(monkeypatch, capsys) -> None:
    passing = contract.run_cx_hybrid_retrieval_package_contract()
    assert contract.summary_line(passing) == (
        "cx_hybrid_retrieval_package_contract=pass checks=10/10 "
        "postgres_required=False remote_required=False"
    )
    assert "checks=0/0" in contract.summary_line({})

    monkeypatch.setattr(
        contract,
        "run_cx_hybrid_retrieval_package_contract",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "contract=pass" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_cx_hybrid_retrieval_package_contract",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_contract_materializer_exposes_only_requested_authorized_text() -> None:
    records = contract._EvidenceMaterializer().load_authorized_texts(
        chunk_refs=[
            {
                "content_object_id": contract.DOCUMENT_ID,
                "chunk_id": contract.CHUNK_ID,
            }
        ]
    )

    assert records == [
        {
            "content_object_id": contract.DOCUMENT_ID,
            "chunk_id": contract.CHUNK_ID,
            "chunk_text": contract.EVIDENCE,
            "text_sha256": contract._digest(contract.EVIDENCE),
        }
    ]
