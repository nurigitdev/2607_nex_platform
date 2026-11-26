import { describe, expect, it, vi } from "vitest";

import { createBusinessVoucherClient } from "./businessVoucherClientPort";

describe("business voucher client port", () => {
  it("sends exact revision identity for explicit validation and accounting submit", async () => {
    const fetchImpl = vi.fn(async () => response({ status: "PASS" })) as unknown as typeof globalThis.fetch;
    const client = createBusinessVoucherClient({ mode: "fetch", baseUrl: "/ae-api", fetchImpl });
    await client.validate(DRAFT);
    await client.submit(DRAFT);

    expect(fetchImpl).toHaveBeenNthCalledWith(
      1,
      `/ae-api/api/v1/business-voucher-drafts/${DRAFT.candidate_id}:validate`,
      expect.objectContaining({ credentials: "include" }),
    );
    expect(JSON.parse(String((fetchImpl as ReturnType<typeof vi.fn>).mock.calls[1][1]?.body))).toEqual(
      expect.objectContaining({
        expected_version: 2,
        expected_revision: 2,
        expected_candidate_hash: DRAFT.candidate_hash,
        confirmed: true,
      }),
    );
  });

  it("fails closed on malformed owner lists", async () => {
    const client = createBusinessVoucherClient({
      mode: "fetch",
      fetchImpl: vi.fn(async () => response({ items: "unsafe" })) as unknown as typeof globalThis.fetch,
    });
    await expect(client.list()).rejects.toMatchObject({ status: "INVALID_RESPONSE" });
  });
});

const DRAFT = {
  candidate_id: "d1000000-0000-4000-8000-000000000051",
  state: "DRAFT" as const,
  version: 2,
  current_revision_no: 2,
  candidate_hash: "sha256:" + "a".repeat(64),
  project_code: "VO00D260001",
  recognition_date: "2026-11-26",
  transaction_currency: "KRW",
  source_kind: "EXPENSE_CLAIM",
  source_record_ref: "expense:51",
  business_work_code: "FL0004011",
  document_envelope_id: "d2000000-0000-4000-8000-000000000051",
  approved_document: null,
  lines: [],
  balance: { debit: "1000.0000", credit: "1000.0000", balanced: true },
};

function response(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
