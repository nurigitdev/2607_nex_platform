from __future__ import annotations

from pathlib import Path

import pytest

from nex_runtime.production_container_bootstrap import (
    ProductionContainerBootstrapError,
    main,
    prepare_production_container_environment,
    run_production_container_bootstrap,
)
from nex_runtime.openbao_secret_resolver import OpenBaoSecretResolverError
from nex_runtime.production_secret_materialization import ResolvedSecret
from run_platform_production_startup_admission import _synthetic_environment


ROOT = Path(__file__).resolve().parents[1]


class Resolver:
    revoked = False

    def resolve(self, reference, *, context):
        return ResolvedSecret(
            owner=context.owner,
            target_environment_name=context.target_environment_name,
            secret_generation=context.secret_generation,
            reference_version=context.reference_version,
            provider_id="external",
            value=f"owner-value-{context.target_environment_name}",
        )

    def revoke(self):
        self.revoked = True


def test_prepares_only_owner_environment_removes_references_and_revokes() -> None:
    environment = _synthetic_environment(ROOT)
    environment.update(
        {
            "NEX_PROFILE": "staging_live",
            "NEX_OPENBAO_ROLE_ID_FILE": "/run/secrets/role",
            "NEX_OPENBAO_SECRET_ID_FILE": "/run/secrets/secret",
        }
    )
    resolver = Resolver()
    process_environment, result = prepare_production_container_environment(
        "nex-oa",
        environment,
        root=ROOT,
        resolver_factory=lambda _: resolver,
    )
    assert resolver.revoked is True
    assert result.owner_environment.owner == "nex-oa"
    assert result.profile == "staging_live"
    assert len(result.owner_environment.secrets) == 2
    assert process_environment["NEX_OA_DATABASE_URL"].startswith("owner-value-")
    assert "NEX_AG_DATABASE_URL" not in process_environment
    assert not any(name.endswith("_REF") for name in process_environment)
    assert "NEX_OPENBAO_SECRET_ID_FILE" not in process_environment


def test_prepare_rejects_owner_and_revokes_after_materialization_failure() -> None:
    with pytest.raises(ProductionContainerBootstrapError, match="owner"):
        prepare_production_container_environment(
            "unknown", {}, root=ROOT, resolver_factory=lambda _: Resolver()
        )

    class RevokeFailureResolver(Resolver):
        def revoke(self):
            raise RuntimeError("private revoke detail")

    with pytest.raises(Exception):
        prepare_production_container_environment(
            "nex-oa",
            {"NEX_PROFILE": "production"},
            root=ROOT,
            resolver_factory=lambda _: RevokeFailureResolver(),
        )
    resolver = Resolver()
    with pytest.raises(Exception):
        prepare_production_container_environment(
            "nex-oa",
            {"NEX_PROFILE": "production"},
            root=ROOT,
            resolver_factory=lambda _: resolver,
        )
    assert resolver.revoked is True
    with pytest.raises(ProductionContainerBootstrapError, match="profile"):
        prepare_production_container_environment(
            "nex-oa",
            {"NEX_PROFILE": "test"},
            root=ROOT,
            resolver_factory=lambda _: Resolver(),
        )


def test_run_executes_exact_command_with_materialized_environment(monkeypatch, capsys) -> None:
    environment = _synthetic_environment(ROOT)
    captured = {}
    resolver = Resolver()
    monkeypatch.setattr(
        "nex_runtime.production_container_bootstrap.build_openbao_secret_resolver",
        lambda _: resolver,
    )
    monkeypatch.setattr(
        "nex_runtime.production_container_bootstrap.prepare_production_container_environment",
        lambda owner, env: (
            {"SAFE": "value"},
            type(
                "Materialization",
                (),
                {
                    "owner_environment": type(
                        "Owner", (), {"secrets": (1, 2)}
                    )()
                },
            )(),
        ),
    )

    def executor(executable, command, env):
        captured.update(executable=executable, command=command, env=dict(env))
        return "executed"

    result = run_production_container_bootstrap(
        "nex-oa", ("python", "-m", "example"), environ=environment, executor=executor
    )
    assert result == "executed"
    assert captured == {
        "executable": "python",
        "command": ("python", "-m", "example"),
        "env": {"SAFE": "value"},
    }
    assert "owner=nex-oa secrets=2" in capsys.readouterr().out
    with pytest.raises(ProductionContainerBootstrapError, match="command"):
        run_production_container_bootstrap("nex-oa", (), environ=environment)


def test_main_strips_separator_and_sanitizes_failure(monkeypatch, capsys) -> None:
    captured = {}
    monkeypatch.setattr(
        "nex_runtime.production_container_bootstrap.run_production_container_bootstrap",
        lambda owner, command: captured.update(owner=owner, command=command),
    )
    assert main(["--owner", "nex-mo", "--", "python", "-V"]) == 0
    assert captured == {"owner": "nex-mo", "command": ("python", "-V")}
    monkeypatch.setattr(
        "nex_runtime.production_container_bootstrap.run_production_container_bootstrap",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("private-value")),
    )
    assert main(["--owner", "nex-mo", "--", "python"]) == 1
    output = capsys.readouterr()
    assert "private-value" not in output.err
    assert "owner=nex-mo" in output.err
    assert "reason=RuntimeError" in output.err

    monkeypatch.setattr(
        "nex_runtime.production_container_bootstrap.run_production_container_bootstrap",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OpenBaoSecretResolverError(
                "OpenBao request failed: POST /v1/auth/approle/login status=403"
            )
        ),
    )
    assert main(["--owner", "nex-mo", "--", "python"]) == 1
    output = capsys.readouterr()
    assert "status=403" in output.err
    assert "reason=OpenBaoSecretResolverError" in output.err

    captured.clear()
    monkeypatch.setattr(
        "nex_runtime.production_container_bootstrap.run_production_container_bootstrap",
        lambda owner, command: captured.update(owner=owner, command=command),
    )
    assert main(["--owner", "nex-oa", "python", "-V"]) == 0
    assert captured["command"] == ("python", "-V")
