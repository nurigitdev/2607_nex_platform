# nex-ae-web

Korean-default NeX Agent Experience workspace shell.

Run locally:

```bash
npm --prefix apps/nex-ae-web run dev
```

The shell uses only Node.js standard library for serving static files.

Slice 0045 integrates the first mock workspace surface and artifact card flow:

- Service readiness strip.
- Workspace summary metrics.
- Chat composer with retrieval and target format controls.
- Document scope list.
- Generation progress timeline.
- AE artifact handoff summary.
- AE artifact card refs with version, preview route, download route, and action
  metadata.
- AG audit summary.

The browser shell is static and mock-first. Backend service calls are limited to
readiness checks until service-authenticated browser mediation is added.
