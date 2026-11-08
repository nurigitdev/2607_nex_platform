from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from .canonical_platform_trust import (
    CANONICAL_PLATFORM_DEPLOYMENT_BOUNDARY,
    CANONICAL_PLATFORM_OWNERS,
    STARTUP_SERVICE_TOKEN_BOOTSTRAP_ENV,
    CanonicalPlatformTrustError,
    materialize_canonical_owner_secrets,
)
from .demo_service_token_bootstrap import issue_demo_startup_service_tokens
from .demo_trust import (
    DEMO_DEPLOYMENT_BOUNDARY,
    DEMO_OWNERS,
    DEMO_STARTUP_TOKEN_BOOTSTRAP_ENV,
    materialize_demo_owner_secrets,
)
from .openbao_secret_resolver import (
    OpenBaoSecretResolver,
    OpenBaoSecretResolverError,
    build_openbao_secret_resolver,
)
from .p9_wa_trust import (
    P9_WA_DEPLOYMENT_BOUNDARY,
    P9_WA_OWNERS,
    materialize_p9_wa_owner_secrets,
)
from .production_secret_materialization import (
    OwnerProductionSecretMaterialization,
    materialize_owner_production_secrets,
)
from .startup_service_token_bootstrap import issue_startup_service_tokens

ROOT = Path(__file__).resolve().parents[3]
ALLOWED_OWNERS = tuple(
    dict.fromkeys((*CANONICAL_PLATFORM_OWNERS, *DEMO_OWNERS, *P9_WA_OWNERS))
)
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
    demo_token_issuer: Callable[
        [str, Mapping[str, str]], tuple[dict[str, str], object]
    ] = issue_demo_startup_service_tokens,
    startup_token_issuer: Callable[
        [str, Mapping[str, str]], tuple[dict[str, str], object]
    ] = issue_startup_service_tokens,
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
        boundary = str(environ.get("NEX_DEPLOYMENT_BOUNDARY") or "").strip()
        if boundary == CANONICAL_PLATFORM_DEPLOYMENT_BOUNDARY:
            materialization = materialize_canonical_owner_secrets(
                environ,
                resolver,
                owner=owner,
                profile=profile,
            )
        elif boundary == DEMO_DEPLOYMENT_BOUNDARY:
            materialization = materialize_demo_owner_secrets(
                environ,
                resolver,
                owner=owner,
                profile=profile,
            )
        elif boundary == P9_WA_DEPLOYMENT_BOUNDARY:
            materialization = materialize_p9_wa_owner_secrets(
                environ,
                resolver,
                owner=owner,
                profile=profile,
            )
        else:
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
        if (
            boundary == CANONICAL_PLATFORM_DEPLOYMENT_BOUNDARY
            and str(environ.get(STARTUP_SERVICE_TOKEN_BOOTSTRAP_ENV) or "").strip()
            == "true"
        ):
            process_environment, _ = startup_token_issuer(
                owner, process_environment
            )
        elif (
            boundary == DEMO_DEPLOYMENT_BOUNDARY
            and str(environ.get(DEMO_STARTUP_TOKEN_BOOTSTRAP_ENV) or "").strip()
            == "true"
        ):
            process_environment, _ = demo_token_issuer(owner, process_environment)
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
        detail = (
            f" detail={exc}"
            if isinstance(exc, (OpenBaoSecretResolverError, CanonicalPlatformTrustError))
            else ""
        )
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
