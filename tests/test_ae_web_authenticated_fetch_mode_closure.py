from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_s24_slice_index_and_closure_docs_are_wired() -> None:
    docs_index = read_text("docs/README.md")
    ae_web_readme = read_text("apps/nex-ae-web/README.md")
    ae_api_readme = read_text("services/nex-ae-api/README.md")

    for slice_id in range(231, 241):
        assert f"Slice {slice_id:04d}" in docs_index

    assert "authenticated fetch-mode" in read_text(
        "docs/slices/0240_ae_web_authenticated_fetch_mode_closure.md"
    )
    assert "Slice 0240" in ae_web_readme
    assert "Slice 0240" in ae_api_readme


def test_authenticated_fetch_smoke_cannot_regress_to_service_auth() -> None:
    smoke_runner = read_text("scripts/smoke/run_ae_web_fetch_mode_postgres_smoke.py")
    contract_schema = json.loads(
        read_text(
            "contracts/schemas/service/nex_ae_web/"
            "fetch_mode_smoke_evidence.v1.schema.json"
        )
    )
    positive_fixture = json.loads(
        read_text(
            "contracts/examples/operations/"
            "ae_web_fetch_mode_smoke_evidence.postgres_success.json"
        )
    )

    assert "issue_mock_user_token" in smoke_runner
    assert "_ae_browser_headers" in smoke_runner
    assert "_ae_service_headers" not in smoke_runner
    assert "service_token_used_for_ae_facade" in json.dumps(contract_schema)
    assert positive_fixture["auth_observations"] == {
        "ae_facade_auth_mode": "browser_user",
        "ae_facade_transport": "authorization_header",
        "owner_scope_authority": "claim",
        "browser_token_redacted": True,
        "service_token_used_for_ae_facade": False,
    }
    assert positive_fixture["checks"]["browser_claim_owner_scope_enforced"] is True
    assert positive_fixture["checks"]["retrieval_actor_scope_claim_derived"] is True
