from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence

from nex_runtime import DEFAULT_SERVICE_SCOPE, resolve_service_endpoint

from .intake import WaEvidenceIntakeService
from .persistence import build_wa_persistence_runtime
from .reconciliation import (
    HttpAeWaReconciliationSource,
    WaAeReconciliationService,
    WaReconciliationError,
)
from .service_auth import resolve_wa_outbound_service_token


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="nex-wa-reconcile-ae-sources")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--mode", choices=("operator", "startup"))
    parser.add_argument("--tenant-id")
    parser.add_argument("--created-after")
    parser.add_argument("--created-before")
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages-per-source", type=int, default=10)
    args = parser.parse_args(argv)
    env = dict(os.environ if environ is None else environ)
    persistence = None
    try:
        endpoint = resolve_service_endpoint("nex-ae-api", environ=env)
        token = resolve_wa_outbound_service_token(
            env.get("NEX_WA_TO_AE_SERVICE_TOKEN"),
            audience="nex-ae-api",
            scopes=(DEFAULT_SERVICE_SCOPE, "work:source:read"),
            environ=env,
        )
        if args.check:
            print(
                json.dumps(
                    {
                        "service_id": "nex-wa",
                        "process_id": "nex-wa-ae-reconciliation",
                        "status": "READY",
                        "ae_endpoint": endpoint.base_url,
                        "signed_source_access": bool(token),
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )
            return 0
        required = {
            "--mode": args.mode,
            "--tenant-id": args.tenant_id,
            "--created-after": args.created_after,
            "--created-before": args.created_before,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            parser.error(f"required arguments missing: {', '.join(missing)}")
        persistence = build_wa_persistence_runtime(environ=env)
        source = HttpAeWaReconciliationSource(
            base_url=env.get("NEX_AE_API_BASE_URL", endpoint.base_url),
            service_token=token,
            timeout_seconds=float(
                env.get("NEX_WA_TO_AE_RECONCILIATION_TIMEOUT_SECONDS", "15")
            ),
        )
        result = WaAeReconciliationService(
            source=source,
            intake=WaEvidenceIntakeService(persistence.job_queue),
        ).run(
            tenant_id=args.tenant_id,
            created_after=args.created_after,
            created_before=args.created_before,
            mode=args.mode,
            page_size=args.page_size,
            max_pages_per_source=args.max_pages_per_source,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=True, sort_keys=True))
        return 0 if all(source.complete for source in result.sources) else 2
    except (ValueError, WaReconciliationError) as exc:
        print(
            json.dumps(
                {
                    "service_id": "nex-wa",
                    "process_id": "nex-wa-ae-reconciliation",
                    "status": "FAILED",
                    "error_code": getattr(
                        exc, "error_code", "WA_RECONCILIATION_BOOTSTRAP_FAILED"
                    ),
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 1
    finally:
        if persistence is not None:
            persistence.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
