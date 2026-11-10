# COA-05 PA/NSL Deterministic Semantic Account Resolution

## Scope

- Add the canonical `FINANCE.COA.RESOLVE_SEMANTIC` read operation at
  `GET /internal/v2/finance/accounts/resolve-semantic`.
- Resolve a MyBee semantic key to an effective tenant-owned EOS Account UUID
  using the approved company adoption, immutable COA binding, active Account,
  CompanyAccountPolicy, PostingRule, date, and currency.
- Add a signed AE-to-EOS HTTP adapter that validates the exact request identity,
  response schema, Account reference, and evidence hash.
- Freeze the MyBee NSL READ Tool source contract without pretending that an
  unbuilt or unadmitted Skill artifact is active in the product runtime.

## Decisions

- The LLM or Project Agent may select only a semantic accounting intent. It
  must not invent an AccountCode or Account UUID.
- EOS is the sole authority that returns the tenant Account UUID. No candidate,
  multiple candidates, stale policy, wrong tenant/company/date, or unsupported
  currency fails closed.
- The resolver requires fresh OA `finance:account:read` authority in addition
  to signed service trust.
- The result includes both the tenant Account code and immutable definition
  code, plus adoption/binding/policy evidence and a semantic SHA-256 evidence
  hash.
- The MyBee contract remains `CONTRACT_ONLY` until an exact NSL artifact digest
  is built and admitted. COA-05 does not modify the production capability
  registry with a fictitious artifact.
- No database migration or remote model provider is required for this Slice.

## Verification

- Focused EOS/AE regression: `72 passed, 3 skipped`.
- AE adapter focused coverage: statement `100.00%`, branch `100.00%`.
- Actual PostgreSQL smoke against `nex_eos_test`:
  - identity `nex_eos_test / nex_eos_user` verified;
  - migrations applied in an isolated schema;
  - approved publish, company policy, adoption, and semantic resolution passed;
  - isolated schema removed after execution.
- EOS Slice Gate: `919 passed, 28 skipped`; statement `96.15%`, branch
  `94.70%`; resolver statement `98.71%`, branch `95.76%`; API `100%/100%`.
- AE Slice Gate: `5,813 passed, 45 skipped`; statement `97.01%`, branch
  `95.22%`; semantic adapter `100%/100%`.
- Contract validation: `233` schemas, `292` examples, `245` negative examples,
  and `10` OpenAPI documents passed.

## Follow-up

- Build and admit the exact `FINANCE.ACCOUNT_SEMANTIC_RESOLVE` NSL artifact
  before activating this Tool in the product capability registry.
- COA-06 owns approved K-IFRS/DART reporting taxonomy mappings. COA-07 owns
  release diff, observability, negative concurrency, and upgrade rehearsal.
