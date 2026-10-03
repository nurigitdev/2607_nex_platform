from __future__ import annotations

import run_oa_authorization_contracts as contracts


def test_authorization_contract_evidence_passes() -> None:
    evidence = contracts.run_oa_authorization_contracts()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["privacy_paths"] == []
    assert evidence["summary"] == {
        "schema_count": 6,
        "positive_valid_count": 6,
        "negative_rejected_count": 6,
        "operation_valid_count": 8,
        "runtime_response_count": 6,
    }


def test_operation_matcher_fails_closed() -> None:
    path = "/sample"
    valid = {
        "paths": {
            path: {
                "put": {
                    "security": [{"serviceBearer": []}],
                    "x-nex-required-scopes": ["service:call", "sample:write"],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Request"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Response"}
                                }
                            }
                        }
                    },
                }
            }
        }
    }
    kwargs = {
        "method": "put",
        "path": path,
        "scope": "sample:write",
        "request_schema": "Request",
        "response_schema": "Response",
    }
    assert contracts._operation_matches(valid, **kwargs)
    assert contracts._operation_matches(
        valid,
        **{**kwargs, "request_schema": None, "response_schema": None},
    )
    assert not contracts._operation_matches({}, **kwargs)

    bad_security = {"paths": {path: {"put": {**valid["paths"][path]["put"], "security": []}}}}
    assert not contracts._operation_matches(bad_security, **kwargs)
    bad_scopes = {
        "paths": {
            path: {
                "put": {
                    **valid["paths"][path]["put"],
                    "x-nex-required-scopes": ["service:call"],
                }
            }
        }
    }
    assert not contracts._operation_matches(bad_scopes, **kwargs)
    assert not contracts._operation_matches(
        valid, **{**kwargs, "request_schema": "Wrong"}
    )
    assert not contracts._operation_matches(
        valid, **{**kwargs, "response_schema": "Wrong"}
    )


def test_private_path_detection_covers_objects_and_arrays() -> None:
    assert contracts._private_paths(
        {"safe": [{"password_hash": "private"}], "secret_value": "private"}
    ) == ["payload.safe[0].password_hash", "payload.secret_value"]
    assert contracts._private_paths({"safe": ["value"]}) == []


def test_fixture_validation_counts_fail_closed(monkeypatch) -> None:
    class StubValidator:
        def iter_errors(self, payload):
            return ["error"] if payload.get("invalid") else []

    monkeypatch.setattr(contracts, "_validator", lambda _name: StubValidator())
    monkeypatch.setattr(
        contracts,
        "_load_json",
        lambda path: {"invalid": ".editor." in path.name or ".engineering." in path.name or ".active." in path.name or ".role." in path.name},
    )
    positive, negative, payloads = contracts._fixture_validation()
    assert positive < len(contracts.SCHEMA_FIXTURES)
    assert negative < len(contracts.SCHEMA_FIXTURES)
    assert len(payloads) == len(contracts.SCHEMA_FIXTURES)


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = contracts.run_oa_authorization_contracts()
    summary = contracts.summary_line(passing)
    assert "oa_authorization_contracts=pass" in summary
    assert "fixtures=6/6" in summary
    assert "operations=8" in summary
    monkeypatch.setattr(contracts, "run_oa_authorization_contracts", lambda: passing)
    assert contracts.main(["--summary"]) == 0
    assert "runtime=6" in capsys.readouterr().out
    assert contracts.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        contracts,
        "run_oa_authorization_contracts",
        lambda: {"status": "FAIL"},
    )
    assert contracts.main([]) == 1
