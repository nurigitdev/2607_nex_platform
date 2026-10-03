from __future__ import annotations

import json
from pathlib import Path

import run_oa_service_principal_contracts as contracts


def test_service_principal_contract_evidence_passes() -> None:
    evidence = contracts.run_oa_service_principal_contracts()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert all(evidence["contract_checks"].values())
    assert all(evidence["privacy_checks"].values())
    assert all(evidence["runtime_checks"].values())
    assert all(evidence["operation_checks"].values())
    assert all(evidence["canonical_checks"].values())
    assert evidence["summary"] == {
        "schema_count": 6,
        "positive_valid_count": 6,
        "privacy_safe_count": 6,
        "runtime_valid_count": 6,
        "operation_valid_count": 9,
        "remaining_contract_drift_count": 21,
    }


def test_operation_matcher_fails_closed() -> None:
    path = "/sample"
    valid = {
        "paths": {
            path: {
                "post": {
                    "security": [{"serviceBearer": []}],
                    "x-nex-required-scopes": ["service:call", "sample:admin"],
                    "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Request"}}}},
                    "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Response"}}}}},
                }
            }
        }
    }
    kwargs = {
        "method": "post", "path": path, "scope": "sample:admin",
        "request_schema": "Request", "response_schema": "Response",
    }
    assert contracts._operation_matches(valid, **kwargs)
    assert not contracts._operation_matches({}, **kwargs)
    assert not contracts._operation_matches(
        valid, **{**kwargs, "request_schema": "Wrong"}
    )
    assert not contracts._operation_matches(
        valid, **{**kwargs, "response_schema": "Wrong"}
    )
    assert not contracts._operation_matches(
        {"paths": {path: {"post": {**valid["paths"][path]["post"], "security": []}}}},
        **kwargs,
    )
    assert not contracts._operation_matches(
        {"paths": {path: {"post": {**valid["paths"][path]["post"], "x-nex-required-scopes": []}}}},
        **kwargs,
    )


def test_privacy_checks_allow_only_one_time_root_secret() -> None:
    assert contracts._privacy_safe(
        "credential_issue", {"client_secret": "one-time", "secret_display": "once"}
    )
    assert not contracts._privacy_safe("credential_response", {"client_secret": "x"})
    assert not contracts._privacy_safe(
        "credential_rotation",
        {"client_secret": "x", "secret_display": "once", "nested": {"client_secret": "x"}},
    )
    assert not contracts._privacy_safe("principal_response", {"secret_hash": "x"})
    assert contracts._key_paths([{"client_secret": "x"}], "client_secret") == [
        "payload[0].client_secret"
    ]
    assert contracts._sensitive_paths({"safe": [{"password_hash": "x"}]}) == [
        "payload.safe[0].password_hash"
    ]


def test_runner_fails_closed_for_missing_inputs(tmp_path: Path) -> None:
    result = contracts.run_oa_service_principal_contracts(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["inputs_valid"] is False
    assert result["issues"]


def test_runner_covers_non_runtime_root_and_rejects_non_object_openapi(
    tmp_path: Path, monkeypatch
) -> None:
    schema_root = tmp_path / "contracts/schemas/service/nex_oa"
    positive_root = tmp_path / "contracts/examples/auth"
    negative_root = tmp_path / "contracts/tests/negative/auth"
    openapi_root = tmp_path / "contracts/openapi"
    for directory in (schema_root, positive_root, negative_root, openapi_root):
        directory.mkdir(parents=True, exist_ok=True)
    (schema_root / "sample.schema.json").write_text(
        '{"type":"object","additionalProperties":false}', encoding="utf-8"
    )
    (positive_root / "positive.json").write_text("{}", encoding="utf-8")
    (negative_root / "negative.json").write_text(
        '{"unexpected":true}', encoding="utf-8"
    )
    (openapi_root / "nex-oa.openapi.yaml").write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(
        contracts,
        "CONTRACTS",
        {"sample": ("sample.schema.json", "positive.json", "negative.json")},
    )

    result = contracts.run_oa_service_principal_contracts(tmp_path)

    assert result["status"] == "FAIL"
    assert result["contract_checks"] == {"sample": True}
    assert result["runtime_checks"] == {}
    assert {issue["category"] for issue in result["issues"]} == {"openapi_invalid"}


def test_load_json_rejects_non_object(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_text(json.dumps([]), encoding="utf-8")

    try:
        contracts._load_json(path)
    except ValueError as exc:
        assert "must be an object" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-object input must fail closed")


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = contracts.run_oa_service_principal_contracts()
    assert contracts.summary_line(passing) == (
        "oa_service_principal_contracts=pass contracts=6/6 privacy=6/6 "
        "runtime=6/6 operations=9/9 drift=21"
    )
    monkeypatch.setattr(contracts, "run_oa_service_principal_contracts", lambda: passing)
    assert contracts.main(["--summary"]) == 0
    assert "operations=9/9" in capsys.readouterr().out
    assert contracts.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        contracts, "run_oa_service_principal_contracts", lambda: {"status": "FAIL"}
    )
    assert contracts.main([]) == 1
