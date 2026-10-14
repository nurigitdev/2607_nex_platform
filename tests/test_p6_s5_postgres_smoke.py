from __future__ import annotations

from pathlib import Path

import pytest
import run_p6_s5_postgres_smoke as smoke


def test_smoke_is_opt_in_and_rejects_untrusted_targets() -> None:
    skipped = smoke.run_p6_s5_postgres_smoke({})
    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False

    missing = smoke.run_p6_s5_postgres_smoke({smoke.SMOKE_ENV: "1"})
    assert missing["failure_code"] == "database_url_missing"

    rejected = smoke.run_p6_s5_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql://nex_ae_user:secret@127.0.0.1/nex_ae_dev"
            ),
        }
    )
    assert rejected["failure_code"] == "target_not_allowed"

    missing_source = smoke.run_p6_s5_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql://nex_ae_user:secret@127.0.0.1/nex_ae_test"
            ),
        }
    )
    assert missing_source["failure_code"] == "nsl_source_missing"


def test_nsl_source_preflight_fails_closed(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(ValueError, match="stable"):
        smoke._verified_nsl_source(tmp_path)

    (tmp_path / "nsl/api").mkdir(parents=True)
    (tmp_path / "nsl/api/__init__.py").write_text("", encoding="utf-8")

    class _Result:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    outputs = iter((_Result("wrong-sha\n"), _Result("")))
    monkeypatch.setattr(
        smoke.subprocess, "run", lambda *_args, **_kwargs: next(outputs)
    )
    with pytest.raises(RuntimeError, match="revision"):
        smoke._verified_nsl_source(tmp_path)


def test_summary_is_bounded() -> None:
    assert smoke.summary_line(
        {
            "status": "PASS",
            "actual_postgres": True,
            "checks": {"one": True, "two": True},
            "migration": {"planned_count": 43},
            "row_counts": {"backend_runs": 1, "progress_events": 4},
            "cleanup_counts": {"s5_remaining": 0},
        }
    ) == (
        "p6_s5_postgres=pass actual_postgres=true checks=2/2 "
        "migrations=43 runs=1 progress=4 remaining=0"
    )
