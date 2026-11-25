# W80-CA00F.5B: Primary Project Code Typed Business Context Propagation Closure

## 1. Status

- Version: 1.0
- State: CLOSED
- Parent: W80-CA00F.5
- Trigger: installed Journal live journey authority-request failure
- Migration: none

## 2. Problem

The IA semantic admission path resolved a canonical `primary_project_code`, but
`ae.business_request_context.v1` did not preserve that identity. The initial
WorkIntent kept it only as a model-derived parameter candidate. Claimed-work
reconstruction correctly removed those untrusted parameters while preserving
the typed business context, so the PA Product preparation path could not resolve
the primary Project for a Journal-only request with no allocation list.

This was a propagation defect, not an absent Project authority. The installed
journey still carried the Project UUID and PA assignment, but those references
cannot substitute for the canonical user-facing Project code required by the
EOS transaction-preparation authority contract.

## 3. Decision

1. `primary_project_code` is an optional, hash-bound field of
   `ae.business_request_context.v1` for backward-compatible replay.
2. Every newly admitted `FINANCE_VOUCHER_POSTING` context must include the
   validated canonical Project code.
3. WC delegation, claimed-work reconstruction, PA planning, restart, and replay
   preserve the context and its semantic hash unchanged.
4. The Product preparation authority source reads the typed context first.
5. A pre-amendment v1 context without the field may use the historical
   WorkIntent parameter candidate fallback. New runtime paths must not depend on
   that fallback.
6. Missing Project identity fails closed. No tenant, Project, or scenario
   default is synthesized.
7. General Chat/RAG requests remain Project-neutral and do not require
   `primary_project_code`.

## 4. Default Project Boundary

A personal default scope may later provide durable storage or memory for
non-Project conversations, but it is not silently treated as an EOS business
Project in this amendment. Account creation does not create a Project, and a
general question does not gain accounting or Project authority by fallback.

Whether a personal default scope needs an Agent is a separate design decision.
The current recommendation is that it should not receive a PA unless it becomes
a governed business Project with EOS lifecycle, OA entitlements, and explicit
delegation semantics. IA remains the owner of ordinary personal conversations.

## 5. Contract and Runtime Rules

- Format: `^[A-Z0-9]{4}[DMSOIG][0-9]{6}$`.
- The field participates in `context_hash`; changing it changes WorkIntent
  semantic identity.
- `requested_allocation` may be empty while `primary_project_code` remains
  present for Journal attribution.
- Allocation Project codes do not replace the primary Project identity.
- UUID authority references remain internal; Project code is the canonical
  business identity crossing the IA-to-PA typed handoff.
- The field is input identity, not authorization. EOS and OA still resolve and
  validate fresh company, Project, period, account, approval, and role authority.

## 6. Prohibited Implementations

- requiring a Project code for general questions;
- creating a default business Project during account registration in this Slice;
- creating a PA for a personal/default conversation scope;
- inferring Project code from tenant, Project count, allocation ratio, or fixture;
- accepting a Project UUID as a replacement for the canonical code;
- adding a database table or migration for this propagation correction.

## 7. Verification

1. new Journal and allocation contexts include the typed primary Project code;
2. Journal contexts with an empty allocation list retain it;
3. invalid or tampered codes fail schema and semantic-hash validation;
4. claimed-work authority requests resolve it with empty parameter candidates;
5. historical v1 context replay remains accepted through the bounded fallback;
6. context without either typed identity or historical fallback fails closed;
7. focused contract tests, AE Slice Gate, installed protected live journey, and
   Repository Full Gate run in that order.

## 8. As-Built Closure

The shared business-context validator now accepts both the historical v1 field
set and the additive typed Project identity. New AE admissions always write the
field, examples and hashes are refreshed, and PA Product preparation consumes
the typed value before the replay-only fallback. The change reuses existing JSON
persistence and adds no migration, authority shortcut, or scenario branch.

Focused context, authority-source, and contract tests passed `96` cases. The AE
Slice Gate passed `7,088` tests with `55` protected skips, statement coverage
`96.48%`, branch coverage `94.71%`, and `6/6` commands. Contract validation
passed `279` schemas, `322` examples, `260` negative examples, and `10` OpenAPI
documents.
