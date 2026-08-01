# Development Environment Skeleton

Status: Draft bootstrap.

This document captures the environment assumptions that should be made explicit
before NeX-Platform implementation begins. The first frozen version is now
assembled in
[Platform Development Environment Freeze](../../32_platform_development_environment_freeze.md).

## Repository Layout Assumption

The platform may become multiple repositories or a monorepo. The first design
pass should document both options, then pick one before implementation.

| Area | Initial Need |
| --- | --- |
| `nex-cx` | API service, migrations, extraction/chunking/retrieval modules, database access. |
| `nex-ae-web` | Web frontend, i18n resources, design system assets, Playwright coverage. |
| `nex-ae-api` | Agent orchestration APIs, prompt packaging, artifact generation, service clients. |
| `nex-mo` | Provider registry, health checks, metric scrapers, operations runners. |
| `nex-oa` | Auth service, token/session/API key handling, claim signing/validation. |
| `nex-ag` | Admin APIs and UI for governance, logs, policies, readiness, monitoring. |
| Shared contracts | Error envelope, auth claim model, correlation metadata, provider contracts. |

## Local Runtime

| Dependency | Purpose |
| --- | --- |
| Python | Backend services, workers, scripts, tests. |
| PostgreSQL | Metadata, chunks, logs, runs, policies, operational snapshots. |
| pgvector | Vector storage and similarity search where `nex-cx` owns embeddings. |
| Node.js | Frontend tooling and UI tests if a web app framework is selected. |
| Docker | Optional only; current PCX development avoided Docker for core DB work. |

## Environment Profiles

| Profile | Purpose |
| --- | --- |
| Local mock | Run without DGX/vLLM access using mock embedding, reranker, and generation providers. |
| Local live | Use local app services with remote DGX providers. |
| Test | Isolated database, deterministic fixtures, single-pass coverage gate. |
| Production foreground | Transitional run mode with explicit PID/log evidence. |
| Production service | Later hardening path with supervisor/systemd, restart policy, and logs. |

## Configuration Skeleton

| Key Type | Examples |
| --- | --- |
| Database URL | `DATABASE_URL`, service-specific database URLs. |
| Provider route | Provider id, model id, URL, port, profile, auth mode, timeout. |
| Runtime mode | `mock`, `remote_http`, `remote_openai_compatible`. |
| Secrets | API keys, service credentials, signing keys, database passwords. |
| Observability | Log level, retention days, metrics interval, evidence output path. |
| Feature flags | Experimental provider, tokenizer, reranker, chunk policy, template mode. |

## Setup Checklist

- Create isolated development and test databases.
- Apply migrations before running any smoke or backfill script.
- Seed required provider, tokenizer, template, policy, and role defaults.
- Keep secrets out of committed files.
- Document remote provider host, port, model path, health endpoint, and smoke command.
- Prefer mock provider mode when DGX access is unavailable.

## Open Decisions

- Monorepo vs service repositories.
- Shared library packaging strategy.
- Migration ownership per service.
- Frontend framework selection for `nex-ae-web` and `nex-ag`.
- Production process model: foreground runner, systemd, container, or orchestrator.
