from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import os
from pathlib import Path
import sys

from .openbao_secret_resolver import (
    OpenBaoSecretResolver,
    OpenBaoSecretResolverError,
    build_openbao_secret_resolver,
)
from .production_secret_materialization import (
    OwnerProductionSecretMaterialization,
    materialize_owner_production_secrets,
)


ROOT = Path(__file__).resolve().parents[3]
ALLOWED_OWNERS = ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo", "nex-ag")
_PRIVATE_BOOTSTRAP_NAMES = (
    "NEX_OPENBAO_ROLE_ID_FILE",
    "NEX_OPENBAO_SECRET_ID_FILE",
)


class ProductionContainerBootstrapError(ValueError):
    pass


def prepare_production_container_environment(
    owner: str,
    environ: Mapping[str, str],
    *,
    root: Path = ROOT,
    resolver_factory: Callable[[Mapping[str, str]], OpenBaoSecretResolver] = (
        build_openbao_secret_resolver
    ),
) -> tuple[dict[str, str], OwnerProductionSecretMaterialization]:
    if owner not in ALLOWED_OWNERS:
        raise ProductionContainerBootstrapError("production container owner is invalid")
    profile = str(environ.get("NEX_PROFILE") or "").strip()
    if profile not in {"staging_live", "production"}:
        raise ProductionContainerBootstrapError(
            "production container profile is invalid"
        )
    resolver = resolver_factory(environ)
    try:
        materialization = materialize_owner_production_secrets(
            environ,
            resolver,
            owner=owner,
            profile=profile,
            root=root,
        )
        process_environment = dict(environ)
        process_environment.update(
            materialization.owner_environment.process_environment()
        )
        for name in tuple(process_environment):
            if name.endswith("_REF") or name in _PRIVATE_BOOTSTRAP_NAMES:
                process_environment.pop(name, None)
        resolver.revoke()
    except Exception:
        try:
            resolver.revoke()
        except Exception:
            pass
        raise
    return process_environment, materialization


def run_production_container_bootstrap(
    owner: str,
    command: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
    executor: Callable[[str, Sequence[str], Mapping[str, str]], object] = os.execvpe,
) -> object:
    if not command or not command[0]:
        raise ProductionContainerBootstrapError("production container command is empty")
    source = os.environ if environ is None else environ
    process_environment, materialization = prepare_production_container_environment(
        owner, source
    )
    print(
        "production_container_bootstrap=pass "
        f"owner={owner} secrets={len(materialization.owner_environment.secrets)}",
        flush=True,
    )
    return executor(command[0], tuple(command), process_environment)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True, choices=ALLOWED_OWNERS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = tuple(args.command)
    if command and command[0] == "--":
        command = command[1:]
    try:
        run_production_container_bootstrap(args.owner, command)
    except Exception as exc:
        detail = f" detail={exc}" if isinstance(exc, OpenBaoSecretResolverError) else ""
        print(
            "production_container_bootstrap=fail "
            f"owner={args.owner} reason={type(exc).__name__}{detail}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
