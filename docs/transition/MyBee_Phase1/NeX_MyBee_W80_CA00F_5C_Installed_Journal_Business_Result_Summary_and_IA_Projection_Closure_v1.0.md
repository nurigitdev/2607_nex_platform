# W80-CA00F.5C: Installed Journal Business Result Summary and IA Projection Closure

## 1. Status and Parent

- Status: CLOSED / PARENT PROTECTED ACCEPTANCE PASS
- Parent: W80-CA00F.5
- Predecessor: W80-CA00F.5B
- Resumes: W80-CA00F.5 split live journeys and Repository Full Gate

## 2. Problem

The installed Journal path completed D12, D04, EOS posting, WA settlement, PA
WorkResult, and IA finalization, but emitted no `business_summary`. The terminal
API result was `SUCCEEDED` while the Workspace could not render the expected
`전표 등록 결과` card. The acceptance runner correctly failed rather than
weakening the user-facing contract.

## 3. Decision

The installed Journal runtime shall build the existing admitted
`FINANCE.VOUCHER_DRAFT` presentation contract from three independent sources:

1. amount and currency from the hash-bound `BusinessRequestContext`;
2. Project and account semantic identities from the matching preparation
   authority checkpoint;
3. Journal number and committed Project lineage from the verified EOS result.

The summary is not business authority. It is a user-facing projection whose
fields remain traceable to already admitted authority and result evidence.

## 4. Fail-Closed Rules

- Business context validation and context hash must pass.
- The preparation checkpoint must be `READY_FOR_D04` and bind the same context
  hash.
- Context Project and preparation Project must agree. Historical v1 contexts
  without the additive field may use the checkpoint Project only for replay.
- Debit and credit semantic identities must be present.
- A committed EOS result must expose a Journal number and include the primary
  Project in its verified Project-code lineage.
- Missing or conflicting evidence must stop result projection; it must not
  create a generic success card or synthesize fixture data.

## 5. Publication Boundary

The existing route remains canonical:

`PA AgentResult -> WC WorkResult event -> generalized IA resume -> IA AgentResult
-> WORKSPACE_RESULT -> AE Web`

No new table, public API, event type, result pipeline, model call, or database
migration is admitted. Existing WorkResult business-projection hashes protect
the summary across the handoff.

The delegated parent step did not execute the child WRITE. Therefore the EOS
business operation remains in the typed `business_summary`, business-object
lineage, and external references, while the P5 delegated StepResult's own
`business_operation_id` remains null. Only the admitted `LOCAL_SKILL` that
performed the controlled WRITE owns the StepResult WRITE identity.

## 6. Outcome Semantics

- `COMMITTED + VERIFIED` includes the verified Journal number.
- `NOT_COMMITTED` and `UNKNOWN_COMMIT_STATE` retain the typed request summary
  without inventing a Journal number.
- Allocation remains a separate accounting journey and is not reintroduced
  into Journal completion.

## 7. Acceptance

1. focused installed-runtime and business-projection tests;
2. AE Slice Gate with coverage at or above the current baseline;
3. exact-head OCI and installed product-runtime packaging;
4. actual PostgreSQL, live generation, sequential approval, EOS posting, WA,
   and authenticated Playwright acceptance;
5. result card and recovery rendering evidence;
6. zero-residue cleanup and Repository Full Gate.

The first protected run proved EOS posting, WA evidence intake, and a complete
`FINANCE.VOUCHER_DRAFT` summary in the WC WorkResult. It also exposed an
existing P5 contract violation during generalized IA resume: the child EOS
operation identity had been copied into the parent delegated StepResult WRITE
identity. The contract was corrected without changing persistence or public
APIs, and focused regression now materializes the complete P5 StepResult rather
than stopping at the intermediate executor outcome.

The next protected run completed Journal posting and rendered the installed IA
result, then exposed an older allocation-admission mismatch. The shared
`p65.intent_candidate.v1` contract admits finite numeric parameter values, while
the accounting-allocation activator accepted ratio candidates only as strings.
The activator now accepts finite numeric or string ratios and canonicalizes them
to decimal strings. UUID, Project, source, and other identity fields remain
string-strict, and ratios must still be positive and total exactly one.

The final parent rerun passed on source head
`46aadc52116b3df960110d5e7f1f445ff3bed40d`. Journal and allocation each
rendered an independent IA result, both results recovered after restart, and
their hashes and authoritative database counts remained stable. The final
restricted evidence session is
`mybee-w80-ca00f5-20261125T085606Z-3466be68`; the parent 15-item acceptance
matrix is `15/15 PASS`.

## 8. Non-Goals

- per-user default Project or default PA lifecycle;
- a new posted-Journal result contract name;
- fixture values, tenant dictionaries, fixed Project IDs, or scenario branches;
- allocation execution inside Journal completion.
