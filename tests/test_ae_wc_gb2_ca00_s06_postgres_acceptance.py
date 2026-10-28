from __future__ import annotations

import time

import pytest
import run_gb2_ca00_s06_wc_event_delivery_worker as smoke


def test_smoke_is_protected_and_opt_in() -> None:
    result = smoke.run_gb2_ca00_s06_wc_event_delivery_worker({})

    assert result["status"] == "SKIPPED"
    assert result["actual_postgres"] is False


def test_smoke_rejects_missing_and_wrong_database_targets() -> None:
    missing = smoke.run_gb2_ca00_s06_wc_event_delivery_worker(
        {smoke.SMOKE_ENV: "1"}
    )
    wrong = smoke.run_gb2_ca00_s06_wc_event_delivery_worker(
        {
            smoke.SMOKE_ENV: "1",
            smoke.WC_DATABASE_ENV: "postgresql://other:secret@localhost/other",
            smoke.AE_DATABASE_ENV: "postgresql://other:secret@localhost/other",
        }
    )

    assert missing["failure_code"] == "database_url_missing"
    assert wrong["failure_code"] == "target_not_allowed"
    assert "other:secret" not in str(wrong)


def test_smoke_projects_migrations_and_component_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: type(
            "Migration",
            (),
            {
                "planned": ("a", "b"),
                "applied": ("b",),
                "skipped": ("a",),
            },
        )(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_protected_component",
        lambda **_kwargs: {
            "status": "PASS",
            "actual_postgres": True,
            "signed_service_token": True,
            "checks": {"worker": True},
            "row_counts": {"service_jobs": 1, "http_attempts": 3},
            "cleanup_counts": {"wc_remaining": 0, "ae_remaining": 0},
            "secret_included": False,
        },
    )
    result = smoke.run_gb2_ca00_s06_wc_event_delivery_worker(
        {
            smoke.SMOKE_ENV: "1",
            smoke.WC_DATABASE_ENV: (
                "postgresql://nex_wc_user:nuri1004@127.0.0.1/nex_wc_test"
            ),
            smoke.AE_DATABASE_ENV: (
                "postgresql://nex_ae_user:nuri1004@127.0.0.1/nex_ae_test"
            ),
        }
    )

    assert result["status"] == "PASS"
    assert result["evidence_classification"] == "PROTECTED_COMPONENT"
    assert result["checks"] == {"migrations_current": True, "worker": True}
    assert result["migration"]["wc"]["planned_count"] == 2
    assert "nuri1004" not in str(result)
    assert smoke.summary_line(result) == (
        "gb2_ca00_s06_wc_delivery=pass classification=PROTECTED_COMPONENT "
        "checks=2/2 jobs=1 http=3 remaining=0"
    )


def test_smoke_fails_closed_and_redacts_password(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "postgresql://nex_wc_user:secret@127.0.0.1/nex_wc_test"
            )
        ),
    )
    result = smoke.run_gb2_ca00_s06_wc_event_delivery_worker(
        {
            smoke.SMOKE_ENV: "1",
            smoke.WC_DATABASE_ENV: (
                "postgresql://nex_wc_user:secret@127.0.0.1/nex_wc_test"
            ),
            smoke.AE_DATABASE_ENV: (
                "postgresql://nex_ae_user:secret@127.0.0.1/nex_ae_test"
            ),
        }
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "execution_failed"
    assert "nex_wc_user:secret" not in str(result)
    assert "***" in result["detail"]


def test_target_summary_and_redaction_helpers() -> None:
    assert smoke._target_url_allowed(
        "postgresql+psycopg://nex_wc_user:x@localhost/nex_wc_test",
        "nex_wc_user",
        "nex_wc_test",
    )
    assert not smoke._target_url_allowed(
        "sqlite:///nex_wc_test", "nex_wc_user", "nex_wc_test"
    )
    assert smoke._redact_detail(
        "postgresql://u:p@host/db unavailable",
        database_urls=("postgresql://u:p@host/db",),
    ) == "postgresql://u:***@host/db unavailable"
    assert smoke.summary_line({"status": "FAIL"}) == (
        "gb2_ca00_s06_wc_delivery=fail classification=none "
        "checks=0/0 jobs=0 http=0 remaining=0"
    )


def test_signed_fixture_accepts_wc_and_denies_wrong_service_at_route_boundary() -> None:
    signed = smoke._signed_trust(now_epoch=int(time.time()))
    admitted = signed["admission"].admit(
        f"Bearer {signed['token']}", required_scopes=("service:call",)
    )
    wrong = signed["admission"].admit(
        f"Bearer {signed['wrong_token']}", required_scopes=("service:call",)
    )

    assert admitted.service_id == "nex-wc"
    assert wrong.service_id == "nex-eos"
    assert admitted.token_kind == wrong.token_kind == "SIGNED"


def test_bridge_raises_http_error_for_denied_response() -> None:
    class Client:
        def request(self, *_args, **_kwargs):
            return type(
                "Response",
                (),
                {
                    "status_code": 403,
                    "reason_phrase": "Forbidden",
                    "headers": {},
                    "content": b'{"error_code":"denied"}',
                },
            )()

    request = type(
        "Request",
        (),
        {
            "full_url": "http://ae.local/internal/v1/work-handoffs",
            "data": b"{}",
            "get_method": lambda self: "POST",
            "header_items": lambda self: [],
        },
    )()
    bridge = smoke._TestClientUrlOpen(Client())

    with pytest.raises(smoke.HTTPError) as exc:
        bridge(request, timeout=1.0)
    assert exc.value.code == 403
    assert bridge.status_codes == [403]
