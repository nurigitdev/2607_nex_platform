# P8-S91: IA Playwright Full Gate

## Status

Completed on 2026-10-24.

## Scope

P8-S91 closes the authenticated IA approval browser boundary against the
actual service-owned PostgreSQL test databases. It composes the existing S43
human-approval journey with the S74 EOS formal-approval journey instead of
creating a second approval implementation.

```text
nex_wc_test  / nex_wc_user
nex_oa_test  / nex_oa_user
nex_eos_test / nex_eos_user
```

The AE approval facade and Web server run through their production-shaped
same-origin HTTP routes. They are stateless for this journey, so P8-S91 does
not manufacture an AE database mutation merely to claim a fourth database.
Remote model providers and RustFS are outside this approval-only gate.

## Acceptance Matrix

| Required behavior | Protected evidence |
|---|---|
| `NSL_WRITE` | Authenticated inbox rendering and actual WC `APPROVE` decision |
| `BUSINESS_FORMAL` | Actual EOS stage projection, WC rendering, `APPROVE`, and independent `REJECT` |
| approve | WC work item becomes `APPROVED`; one immutable decision and one outbox row |
| reject | WC work item becomes `REJECTED`; one immutable decision and one outbox row |
| expired | Expired gate is not admitted to the browser detail route and remains unmodified |
| unauthorized | Target mismatch is hidden; read-only, inactive, and wrong-target decisions fail closed |
| duplicate | Exact decision replay returns the original decision without a second decision or outbox row |
| domain distinction | IA displays `NSL_WRITE` and `BUSINESS_FORMAL` separately; EOS stage metadata is present only on the formal gate |

Anonymous users see only the credential-login shell. Logout returns to that
shell, and raw protected request, resume target, semantic hash, service token,
database URL, and storage path material remain absent from browser evidence.

## Responsive Evidence

The protected Playwright harness now accepts the optional
`NEX_P8_S91_SCREENSHOT_DIR` setting. When set, both approval journeys capture
full-page desktop (`1440 x 1000`) and mobile (`390 x 844`) views and fail when
the document is wider than the viewport. Screenshot paths are restricted to
`reports/quality/`; paths that escape that evidence tree fail closed.

The first S91 run found a real mobile overflow in the EOS-backed formal detail
view. Its display-safe summary could contain a long structured sentence, while
`.approval-detail-surface > p` lacked the wrapping already applied to inbox
and metadata values. Adding `overflow-wrap: anywhere` removed the overflow;
the focused Web regression now guards that rule.

The accepted screenshots were visually inspected for clipped text,
incoherent overlap, unstable controls, domain distinction, formal stage
metadata, and decision-action fit:

```text
reports/quality/p8-s91-playwright/approval-inbox-desktop.png
reports/quality/p8-s91-playwright/approval-inbox-mobile.png
reports/quality/p8-s91-playwright/business-formal-detail-desktop.png
reports/quality/p8-s91-playwright/business-formal-detail-mobile.png
```

These local evidence artifacts remain under the intentionally ignored
`reports/` tree.

## Verification

```text
actual OA/WC/EOS PostgreSQL + Playwright = 4 passed / 0 skipped / 0 failed
browser journeys                              = 2
responsive screenshots                       = 4
desktop horizontal overflow                  = 0
mobile horizontal overflow                   = 0
AE Web Node regression                       = 375 passed / 0 skipped / 0 failed
S91 tenant residue in OA/WC/EOS               = 0 rows
```

JUnit evidence is stored locally at:

```text
reports/quality/p8-s91-ia-playwright-protected.junit.xml
```

The canonical production-source coverage result remains the unchanged P8-S89
Full Gate result: `96.72%` statement and `96.11%` branch. P8-S91 changes the
Web harness, one CSS wrapping rule, its regression assertion, and evidence
documentation; it does not alter the Python production denominator or lower
any threshold.

## Exit Decision

P8-S91 is closed. Authenticated IA approval behavior is proven in Chromium
against actual OA, WC, and EOS test databases for both approval domains and
all required approve, reject, expired, unauthorized, duplicate, and domain
separation outcomes. The responsive approval UI leaves no horizontal overflow
or test residue. P8-S92 may now re-run Golden A and the required reliability
variants against the final candidate commit.
