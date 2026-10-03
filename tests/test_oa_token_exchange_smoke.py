from __future__ import annotations

import run_oa_token_exchange as smoke


def test_token_exchange_evidence_passes() -> None:
    result = smoke.run_oa_token_exchange()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["algorithm"] == "RS256"
    assert result["ttl_seconds"] == 300


def test_token_exchange_summary_and_main(capsys, monkeypatch) -> None:
    result = smoke.run_oa_token_exchange()
    assert smoke.summary_line(result) == (
        "oa_token_exchange=pass alg=RS256 ttl=300 next=1268"
    )
    assert smoke.main(["--summary"]) == 0
    assert "oa_token_exchange=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_oa_token_exchange",
        lambda: {
            "status": "FAIL",
            "algorithm": "unknown",
            "ttl_seconds": 0,
            "next_slice": "blocked",
        },
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


def test_token_exchange_evidence_detects_invalid_signature(monkeypatch) -> None:
    original = smoke.OaClientCredentialTokenExchangeService
    captured: dict[str, str] = {}

    class CaptureTokenExchange:
        def __init__(self, **kwargs: object) -> None:
            self.real = original(**kwargs)

        def exchange(self, *args: object, **kwargs: object) -> dict[str, object]:
            result = self.real.exchange(*args, **kwargs)
            captured["token"] = str(result["access_token"])
            return result

    monkeypatch.setattr(smoke, "OaClientCredentialTokenExchangeService", CaptureTokenExchange)
    assert smoke.run_oa_token_exchange()["status"] == "PASS"

    class ReturnStaleTokenExchange:
        def __init__(self, **kwargs: object) -> None:
            pass

        def exchange(self, *args: object, **kwargs: object) -> dict[str, object]:
            return {"access_token": captured["token"], "expires_in": 300}

    monkeypatch.setattr(
        smoke,
        "OaClientCredentialTokenExchangeService",
        ReturnStaleTokenExchange,
    )
    result = smoke.run_oa_token_exchange()
    assert result["status"] == "FAIL"
    assert result["checks"]["rs256_signature_valid"] is False
