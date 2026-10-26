# P8-DEMO-S09: External Dependency Admission

## Outcome

The Demo Release now has one fail-closed admission result for the live DGX
providers and the RustFS private object-storage boundary. This Slice does not
activate business work or issue service tokens. It proves that the external
dependencies required by the installed journey are reachable and preserve
the previously admitted privacy and recovery properties before S10 starts
domain consumers.

## Live Provider Evidence

The protected runner contacted all three configured DGX endpoints and
validated their OpenAI-compatible response shapes. Endpoint and credential
values are excluded from evidence.

```text
embedding  = Qwen3-Embedding-4B / openai_embeddings / PASS
reranking  = Qwen3-Reranker-4B / rerank / PASS
generation = Qwen3.5-4B / openai_models / PASS
timeouts   = 30s / 30s / 60s
```

The admission contract is capability- and model-identity-aware without
hard-coding these model names into runtime logic. A later model replacement
must produce a new admitted identity digest and pass its normal readiness and
calibration gates.

## RustFS Evidence

The current S146 protected acceptance was executed rather than reused as a
historical report. It started an isolated digest-pinned RustFS and OpenBao /
Traefik boundary and proved:

- two private owner buckets with versioning and AES256 server-side encryption;
- distinct AE and CX IAM identities and denied cross-bucket access;
- managed TLS through the object-storage route;
- source-backed AE generated-response and CX source/Markdown round trips;
- no private payload bytes written into PostgreSQL;
- restart-safe reads after RustFS restart;
- version-aware cleanup and removal of the temporary named volume.

The protected object-storage probe uses the existing test DB smoke boundary
only for adapter metadata assertions. It does not mutate the seven admitted
Demo development databases or the preserved `VO00` fixture.

## Evidence Result

```text
status                    = PASS
actual provider execution = true
provider capabilities      = 3/3
actual RustFS execution    = true
private buckets            = 2
managed TLS                = true
owner isolation            = true
restart recovery           = true
runtime residue retained   = false
next                       = P8-DEMO-S10
```

The combined report is written to
`reports/deployment/p8-demo-external-dependencies.json`. It contains model
identities and a deterministic dependency digest, but no endpoint, API key,
database URL, private object key, or payload.

P8-DEMO-S10 may now provision real OA service-principal credentials, issue
audience-scoped signed tokens, and activate the admitted AE/WC/EOS domain
consumers.
