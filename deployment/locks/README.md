# Deployment Dependency Locks

`python-production.lock` is the hash-pinned Python 3.12 Linux production
dependency closure for the five backend service artifacts. Regenerate it only
from the repository root with the recorded command:

```bash
scripts/deployment/compile_python_lock.sh
```

The AE Web production input is `apps/nex-ae-web/package-lock.json`; builds use
`npm ci` and reject missing integrity metadata. Development-only Python and
Playwright packages are not installed into Python service artifacts.

Lock updates are reviewed changes. Artifact builds must use hash enforcement
and must not resolve from `requirements.txt` directly.
