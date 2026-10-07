#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.background_process import (  # noqa: E402,F401
    BACKGROUND_DATABASE_ENVIRONMENTS,
    BACKGROUND_MODULES,
    ENABLED_BACKGROUND_PROFILES,
    BackgroundProcessResource,
    _build_ingestion_work_process,
    _configure_import_path,
    _database_environment,
    _handle_stop_signal,
    _required_database_url,
    background_process_metadata,
    install_signal_handlers,
    main,
    prepare_background_process,
    run_background_process_shell,
)


if __name__ == "__main__":  # pragma: no cover
    install_signal_handlers()
    raise SystemExit(main())
