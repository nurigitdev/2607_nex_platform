from __future__ import annotations

import time

import pytest
import run_gb2_ca00_s06_wc_event_delivery_worker as smoke


def test_smoke_is_protected_and_opt_in() -> None:
    result = smoke.run_gb2_ca00_s06_wc_event_delivery_worker({})

    assert result["status"] == "SKIPPED"
    assert result["actual_postgres"] is False


def test_smoke_rejects_missing_and_wrong_database_targets() -> None:
    missing = smoke.run_gb2_ca00_s06_wc_event_delivery_worker({smoke.SMOKE_ENV: "1"})
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
            RuntimeError("postgresql://nex_wc_user:secret@127.0.0.1/nex_wc_test")
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
    assert (
        smoke._redact_detail(
            "postgresql://u:p@host/db unavailable",
            database_urls=("postgresql://u:p@host/db",),
        )
        == "postgresql://u:***@host/db unavailable"
    )
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


def _component_values() -> dict:
    return {
        "wc_identity": ("nex_wc_test", "nex_wc_user"),
        "ae_identity": ("nex_ae_test", "nex_ae_user"),
        "wrong_readiness": {"readiness_status": "READY"},
        "readiness": {"readiness_status": "READY", "checks": {"queue": True}},
        "claimed": {"claim": {"state": "ACTIVE"}},
        "denied_event": {"delivery_state": "ENQUEUED"},
        "execution_count_after_denial": 0,
        "status_codes": (403, 200, 200),
        "wrong_run": {"failed_count": 1},
        "failed_job": {"status": "QUEUED", "attempt_count": 1},
        "delivery_run": {"failed_count": 0, "work_cycles": 1},
        "final_job": {"status": "SUCCEEDED", "attempt_count": 2},
        "event": {"delivery_state": "DELIVERED"},
        "assignment_execution_id": "execution-1",
        "replay": {"agent_execution_id": "execution-1"},
        "accepted_signed": 3,
        "execution_count": 1,
        "inbox_count": 1,
        "restart_run": {"work_cycles": 0, "failed_count": 0},
        "heartbeat": {
            "status": "STOPPED",
            "metadata": {"process_id": smoke.PROCESS_ID},
        },
        "worker_id": "worker-1",
        "cleanup": {"wc_remaining": 0, "ae_remaining": 0},
    }


def test_component_evidence_accepts_db_less_retry_replay_orchestration() -> None:
    evidence = smoke._component_evidence(**_component_values())

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["row_counts"]["http_attempts"] == 3
    assert evidence["process"]["restart_work_cycles"] == 0


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    (
        (
            lambda value: value.update(wc_identity=("wrong", "wrong")),
            "actual_database_identities",
        ),
        (
            lambda value: value["readiness"]["checks"].update(queue=False),
            "readiness_truthful",
        ),
        (
            lambda value: value["claimed"]["claim"].update(state="EXPIRED"),
            "normal_wc_domain_admission",
        ),
        (
            lambda value: value.update(execution_count_after_denial=1),
            "worker_unavailable_preserved_pending_event",
        ),
        (
            lambda value: value.update(status_codes=()),
            "wrong_signed_trust_failed_closed",
        ),
        (
            lambda value: value["failed_job"].update(status="FAILED"),
            "wrong_signed_trust_failed_closed",
        ),
        (
            lambda value: value["final_job"].update(attempt_count=1),
            "restart_resumed_pending_delivery",
        ),
        (
            lambda value: value["replay"].update(agent_execution_id="conflict"),
            "delivery_result_persisted",
        ),
        (lambda value: value.update(accepted_signed=2), "signed_transport_accepted"),
        (lambda value: value.update(inbox_count=2), "replay_idempotent"),
        (
            lambda value: value["restart_run"].update(work_cycles=1),
            "restart_did_not_double_deliver",
        ),
        (lambda value: value.update(heartbeat=None), "heartbeat_persisted"),
    ),
)
def test_component_evidence_rejects_retry_replay_and_malformed_drift(
    mutation, failed_check: str
) -> None:
    values = _component_values()
    mutation(values)

    evidence = smoke._component_evidence(**values)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"][failed_check] is False
