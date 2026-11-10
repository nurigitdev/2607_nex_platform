# NeX MyBee COA-01 Candidate Reviewer Diff v1.0

## 1. Review Boundary

This is the first human-review baseline for the 88 proposed postable leaves in
`NeX_MyBee_COA_Codebook_Candidate_v0.1.json`; there is no previously approved
release to diff against. Every row is an internal MyBee product-code proposal,
not an official K-IFRS account number or a DART concept ID.

- Validation status: `STRUCTURE_VALIDATED_ACCOUNTING_APPROVAL_PENDING`
- Accounting-owner approval: `false`
- Runtime Seed allowed: `false`
- Candidate semantic hash:
  `sha256:804cbc36814397ba9a74522dc7de7ffa444e001cde8ff6cbf8b8959129893fc0`
- Code/semantic identity-set hash:
  `sha256:412dee6066d65620e0b817bc652ab319b2ce33eccfccdce1b6e2cd77a0c4a673`
- Full node-contract hash:
  `sha256:e988aaf0f5eccb9578591d8e4f678cb8d751019583389346178a427771be7c13`

`FX monetary` is the proposed default monetary classification. `Postable`
means only that the row is structurally a leaf if it is later admitted; it is
not permission to publish, adopt, or post against the row.

## 2. Leaf Review Table

| Code | Semantic key | Korean title | Category | Balance | Contra | Parent | FX monetary | Postable |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `10101001` | `MB-COA-CASH-ON-HAND` | 현금 | `ASSET` | `DR` | `false` | `10101000` | `true` | `true` |
| `10101002` | `MB-COA-BANK-DEMAND-DEPOSIT` | 보통예금 | `ASSET` | `DR` | `false` | `10101000` | `true` | `true` |
| `10101003` | `MB-COA-BANK-FX-DEPOSIT` | 외화예금 | `ASSET` | `DR` | `false` | `10101000` | `true` | `true` |
| `10102001` | `MB-COA-SHORT-TERM-FINANCIAL-DEPOSIT` | 단기금융상품 | `ASSET` | `DR` | `false` | `10102000` | `true` | `true` |
| `10201001` | `MB-COA-ACCOUNTS-RECEIVABLE-TRADE` | 매출채권 | `ASSET` | `DR` | `false` | `10201000` | `true` | `true` |
| `10201002` | `MB-COA-ACCOUNTS-RECEIVABLE-FX` | 외화매출채권 | `ASSET` | `DR` | `false` | `10201000` | `true` | `true` |
| `10201003` | `MB-COA-AR-LOSS-ALLOWANCE` | 대손충당금 | `ASSET` | `CR` | `true` | `10201000` | `false` | `true` |
| `10202001` | `MB-COA-OTHER-RECEIVABLES` | 미수금 | `ASSET` | `DR` | `false` | `10202000` | `true` | `true` |
| `10202002` | `MB-COA-ACCRUED-INCOME-RECEIVABLE` | 미수수익 | `ASSET` | `DR` | `false` | `10202000` | `true` | `true` |
| `10202003` | `MB-COA-ADVANCES-PAID` | 선급금 | `ASSET` | `DR` | `false` | `10202000` | `false` | `true` |
| `10301001` | `MB-COA-INVENTORY-RAW-MATERIAL` | 원재료 | `ASSET` | `DR` | `false` | `10301000` | `false` | `true` |
| `10301002` | `MB-COA-INVENTORY-WORK-IN-PROGRESS` | 재공품 | `ASSET` | `DR` | `false` | `10301000` | `false` | `true` |
| `10301003` | `MB-COA-INVENTORY-FINISHED-GOODS` | 제품 | `ASSET` | `DR` | `false` | `10301000` | `false` | `true` |
| `10301004` | `MB-COA-INVENTORY-MERCHANDISE` | 상품 | `ASSET` | `DR` | `false` | `10301000` | `false` | `true` |
| `10301005` | `MB-COA-INVENTORY-LOSS-ALLOWANCE` | 재고자산평가충당금 | `ASSET` | `CR` | `true` | `10301000` | `false` | `true` |
| `10401001` | `MB-COA-PREPAID-EXPENSES` | 선급비용 | `ASSET` | `DR` | `false` | `10401000` | `false` | `true` |
| `10501001` | `MB-COA-VAT-INPUT-RECEIVABLE` | 부가세대급금 | `ASSET` | `DR` | `false` | `10501000` | `false` | `true` |
| `10801001` | `MB-COA-PPE-MACHINERY` | 기계장치 | `ASSET` | `DR` | `false` | `10801000` | `false` | `true` |
| `10801002` | `MB-COA-PPE-MACHINERY-ACC-DEPR` | 감가상각누계액-기계장치 | `ASSET` | `CR` | `true` | `10801000` | `false` | `true` |
| `10802001` | `MB-COA-PPE-EQUIPMENT` | 비품 | `ASSET` | `DR` | `false` | `10802000` | `false` | `true` |
| `10802002` | `MB-COA-PPE-EQUIPMENT-ACC-DEPR` | 감가상각누계액-비품 | `ASSET` | `CR` | `true` | `10802000` | `false` | `true` |
| `10901001` | `MB-COA-INTANGIBLE-SOFTWARE` | 소프트웨어 | `ASSET` | `DR` | `false` | `10901000` | `false` | `true` |
| `10901002` | `MB-COA-INTANGIBLE-SOFTWARE-ACC-AMORT` | 상각누계액-소프트웨어 | `ASSET` | `CR` | `true` | `10901000` | `false` | `true` |
| `20101001` | `MB-COA-ACCOUNTS-PAYABLE-TRADE` | 매입채무 | `LIABILITY` | `CR` | `false` | `20101000` | `true` | `true` |
| `20101002` | `MB-COA-ACCOUNTS-PAYABLE-FX` | 외화매입채무 | `LIABILITY` | `CR` | `false` | `20101000` | `true` | `true` |
| `20102001` | `MB-COA-OTHER-PAYABLES` | 미지급금 | `LIABILITY` | `CR` | `false` | `20102000` | `true` | `true` |
| `20102002` | `MB-COA-OTHER-PAYABLES-FX` | 외화미지급금 | `LIABILITY` | `CR` | `false` | `20102000` | `true` | `true` |
| `20102003` | `MB-COA-ACCRUED-EXPENSES-PAYABLE` | 미지급비용 | `LIABILITY` | `CR` | `false` | `20102000` | `true` | `true` |
| `20103001` | `MB-COA-ADVANCES-RECEIVED` | 선수금 | `LIABILITY` | `CR` | `false` | `20103000` | `false` | `true` |
| `20103002` | `MB-COA-CONTRACT-LIABILITY` | 계약부채 | `LIABILITY` | `CR` | `false` | `20103000` | `false` | `true` |
| `20201001` | `MB-COA-VAT-OUTPUT-PAYABLE` | 부가세예수금 | `LIABILITY` | `CR` | `false` | `20201000` | `false` | `true` |
| `20202001` | `MB-COA-WITHHOLDING-INCOME-TAX` | 소득세예수금 | `LIABILITY` | `CR` | `false` | `20202000` | `true` | `true` |
| `20202002` | `MB-COA-WITHHOLDING-SOCIAL-INSURANCE` | 사회보험예수금 | `LIABILITY` | `CR` | `false` | `20202000` | `true` | `true` |
| `20301001` | `MB-COA-LOANS-CURRENT` | 단기차입금 | `LIABILITY` | `CR` | `false` | `20301000` | `true` | `true` |
| `20302001` | `MB-COA-LOANS-NONCURRENT` | 장기차입금 | `LIABILITY` | `CR` | `false` | `20302000` | `true` | `true` |
| `20401001` | `MB-COA-NET-DEFINED-BENEFIT-LIABILITY` | 순확정급여부채 | `LIABILITY` | `CR` | `false` | `20401000` | `false` | `true` |
| `20501001` | `MB-COA-LEASE-LIABILITY` | 리스부채 | `LIABILITY` | `CR` | `false` | `20501000` | `true` | `true` |
| `30101001` | `MB-COA-SHARE-CAPITAL` | 자본금 | `EQUITY` | `CR` | `false` | `30101000` | `false` | `true` |
| `30102001` | `MB-COA-SHARE-PREMIUM` | 주식발행초과금 | `EQUITY` | `CR` | `false` | `30102000` | `false` | `true` |
| `30201001` | `MB-COA-RETAINED-EARNINGS` | 이익잉여금 | `EQUITY` | `CR` | `false` | `30201000` | `false` | `true` |
| `30301001` | `MB-COA-OTHER-COMPREHENSIVE-INCOME-RESERVE` | 기타포괄손익누계액 | `EQUITY` | `CR` | `false` | `30301000` | `false` | `true` |
| `40101001` | `MB-COA-SALES-FINISHED-GOODS` | 제품매출 | `REVENUE` | `CR` | `false` | `40101000` | `false` | `true` |
| `40101002` | `MB-COA-SALES-MERCHANDISE` | 상품매출 | `REVENUE` | `CR` | `false` | `40101000` | `false` | `true` |
| `40101003` | `MB-COA-SALES-SERVICES` | 용역매출 | `REVENUE` | `CR` | `false` | `40101000` | `false` | `true` |
| `40101004` | `MB-COA-SALES-PROJECT-SERVICE` | 프로젝트수행매출 | `REVENUE` | `CR` | `false` | `40101000` | `false` | `true` |
| `40102001` | `MB-COA-SALES-ALLOWANCES` | 매출에누리 | `REVENUE` | `DR` | `true` | `40102000` | `false` | `true` |
| `50101001` | `MB-COA-COGS-RAW-MATERIAL` | 원재료 관련 매출원가 | `EXPENSE` | `DR` | `false` | `50101000` | `false` | `true` |
| `50101002` | `MB-COA-COGS-FINISHED-GOODS` | 제품매출원가 | `EXPENSE` | `DR` | `false` | `50101000` | `false` | `true` |
| `50101003` | `MB-COA-COGS-MERCHANDISE` | 상품매출원가 | `EXPENSE` | `DR` | `false` | `50101000` | `false` | `true` |
| `50101004` | `MB-COA-COGS-SERVICES` | 용역매출원가 | `EXPENSE` | `DR` | `false` | `50101000` | `false` | `true` |
| `50201001` | `MB-COA-PROJECT-DIRECT-LABOR` | 직접노무원가 | `EXPENSE` | `DR` | `false` | `50201000` | `false` | `true` |
| `50201002` | `MB-COA-PROJECT-SUBCONTRACT-COST` | 프로젝트 외주원가 | `EXPENSE` | `DR` | `false` | `50201000` | `false` | `true` |
| `50201003` | `MB-COA-PROJECT-INDIRECT-COST` | 프로젝트 간접원가 | `EXPENSE` | `DR` | `false` | `50201000` | `false` | `true` |
| `50201004` | `MB-COA-PROJECT-EQUIPMENT-COST` | 프로젝트 장비사용원가 | `EXPENSE` | `DR` | `false` | `50201000` | `false` | `true` |
| `50301001` | `MB-COA-INVENTORY-WRITEDOWN-EXPENSE` | 재고자산평가손실 | `EXPENSE` | `DR` | `false` | `50301000` | `false` | `true` |
| `60101001` | `MB-COA-SGA-PAYROLL-SALARY` | 급여 | `EXPENSE` | `DR` | `false` | `60101000` | `false` | `true` |
| `60101002` | `MB-COA-SGA-PAYROLL-BONUS` | 상여금 | `EXPENSE` | `DR` | `false` | `60101000` | `false` | `true` |
| `60101003` | `MB-COA-SGA-PAYROLL-ALLOWANCE` | 제수당 | `EXPENSE` | `DR` | `false` | `60101000` | `false` | `true` |
| `60101004` | `MB-COA-SGA-RETIREMENT-BENEFIT` | 퇴직급여 | `EXPENSE` | `DR` | `false` | `60101000` | `false` | `true` |
| `60101005` | `MB-COA-SGA-EMPLOYEE-BENEFIT` | 복리후생비 | `EXPENSE` | `DR` | `false` | `60101000` | `false` | `true` |
| `60102001` | `MB-COA-SGA-TRAVEL` | 여비교통비 | `EXPENSE` | `DR` | `false` | `60102000` | `false` | `true` |
| `60102002` | `MB-COA-SGA-BUSINESS-ENTERTAINMENT` | 업무추진비 | `EXPENSE` | `DR` | `false` | `60102000` | `false` | `true` |
| `60103001` | `MB-COA-SGA-FEES` | 지급수수료 | `EXPENSE` | `DR` | `false` | `60103000` | `false` | `true` |
| `60103002` | `MB-COA-SGA-SUBCONTRACT-SERVICE` | 외주용역비 | `EXPENSE` | `DR` | `false` | `60103000` | `false` | `true` |
| `60104001` | `MB-COA-SGA-DEPRECIATION` | 감가상각비 | `EXPENSE` | `DR` | `false` | `60104000` | `false` | `true` |
| `60104002` | `MB-COA-SGA-AMORTIZATION` | 무형자산상각비 | `EXPENSE` | `DR` | `false` | `60104000` | `false` | `true` |
| `60105001` | `MB-COA-SGA-RENT` | 임차료 | `EXPENSE` | `DR` | `false` | `60105000` | `false` | `true` |
| `60105002` | `MB-COA-SGA-TELECOM` | 통신비 | `EXPENSE` | `DR` | `false` | `60105000` | `false` | `true` |
| `60105003` | `MB-COA-SGA-UTILITIES` | 수도광열비 | `EXPENSE` | `DR` | `false` | `60105000` | `false` | `true` |
| `60106001` | `MB-COA-SGA-TAXES-DUES` | 세금과공과 | `EXPENSE` | `DR` | `false` | `60106000` | `false` | `true` |
| `60106002` | `MB-COA-SGA-INSURANCE` | 보험료 | `EXPENSE` | `DR` | `false` | `60106000` | `false` | `true` |
| `60107001` | `MB-COA-SGA-SUPPLIES` | 소모품비 | `EXPENSE` | `DR` | `false` | `60107000` | `false` | `true` |
| `60107002` | `MB-COA-SGA-TRAINING` | 교육훈련비 | `EXPENSE` | `DR` | `false` | `60107000` | `false` | `true` |
| `60108001` | `MB-COA-SGA-RESEARCH-DEVELOPMENT-EXPENSE` | 연구개발비-비용처리 | `EXPENSE` | `DR` | `false` | `60108000` | `false` | `true` |
| `60109001` | `MB-COA-SGA-IMPAIRMENT-RECEIVABLE` | 대손상각비 | `EXPENSE` | `DR` | `false` | `60109000` | `false` | `true` |
| `70101001` | `MB-COA-FX-REALIZED-GAIN` | 외환차익 | `REVENUE` | `CR` | `false` | `70101000` | `false` | `true` |
| `70101002` | `MB-COA-FX-REVALUATION-GAIN` | 외화환산이익 | `REVENUE` | `CR` | `false` | `70101000` | `false` | `true` |
| `70102001` | `MB-COA-FINANCE-INTEREST-INCOME` | 이자수익 | `REVENUE` | `CR` | `false` | `70102000` | `false` | `true` |
| `70102002` | `MB-COA-FINANCE-DIVIDEND-INCOME` | 배당금수익 | `REVENUE` | `CR` | `false` | `70102000` | `false` | `true` |
| `70201001` | `MB-COA-OTHER-GAIN-ON-PPE-DISPOSAL` | 유형자산처분이익 | `REVENUE` | `CR` | `false` | `70201000` | `false` | `true` |
| `70201002` | `MB-COA-OTHER-INCOME` | 기타수익 | `REVENUE` | `CR` | `false` | `70201000` | `false` | `true` |
| `80101001` | `MB-COA-FX-REALIZED-LOSS` | 외환차손 | `EXPENSE` | `DR` | `false` | `80101000` | `false` | `true` |
| `80101002` | `MB-COA-FX-REVALUATION-LOSS` | 외화환산손실 | `EXPENSE` | `DR` | `false` | `80101000` | `false` | `true` |
| `80102001` | `MB-COA-FINANCE-INTEREST-EXPENSE` | 이자비용 | `EXPENSE` | `DR` | `false` | `80102000` | `false` | `true` |
| `80201001` | `MB-COA-OTHER-LOSS-ON-PPE-DISPOSAL` | 유형자산처분손실 | `EXPENSE` | `DR` | `false` | `80201000` | `false` | `true` |
| `80201002` | `MB-COA-OTHER-EXPENSE` | 기타비용 | `EXPENSE` | `DR` | `false` | `80201000` | `false` | `true` |
| `90101001` | `MB-COA-CORPORATE-INCOME-TAX-EXPENSE` | 법인세비용 | `EXPENSE` | `DR` | `false` | `90101000` | `false` | `true` |
| `90101002` | `MB-COA-DEFERRED-INCOME-TAX-EXPENSE` | 이연법인세비용 | `EXPENSE` | `DR` | `false` | `90101000` | `false` | `true` |

## 3. Approval Checklist

The Product Accounting Owner must review the exact table above and supply an
immutable proof reference bound to the three hashes in Section 1. Approval
must explicitly cover names, category, balance, contra treatment, parent,
monetary default and posting eligibility. A new version and new hashes are
required after any row change.

Until that proof exists, `approved_seed_manifest.json` remains empty and
`COA-02` may build only test scaffolding; it must not publish or adopt this
candidate as an operational chart.
