import { describe, expect, it, vi } from "vitest";

import { createBusinessAccountCatalogClient } from "./businessAccountCatalogClientPort";

describe("business account catalog client port", () => {
  it("queries the protected effective catalog and preserves code identity", async () => {
    const fetchImpl = vi.fn(async () => response({
      schema_version: "ae_business_account_catalog.v1",
      company_id: "company-1",
      effective_on: "2026-11-27",
      transaction_currency: "KRW",
      accounts: [
        { account_code: "510100", account_name: "외주비", category: "EXPENSE", account_type: "EXPENSE" },
      ],
    })) as unknown as typeof globalThis.fetch;
    const client = createBusinessAccountCatalogClient({ mode: "fetch", baseUrl: "/ae-api", fetchImpl });

    const catalog = await client.get({
      companyId: "company-1",
      effectiveOn: "2026-11-27",
      transactionCurrency: "KRW",
    });

    expect(catalog.accounts[0]).toEqual(expect.objectContaining({
      account_code: "510100",
      account_name: "외주비",
    }));
    expect(fetchImpl).toHaveBeenCalledWith(
      "/ae-api/api/v1/business-account-catalog?company_id=company-1&effective_on=2026-11-27&transaction_currency=KRW",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("fails closed for malformed or denied responses", async () => {
    const malformed = createBusinessAccountCatalogClient({
      mode: "fetch",
      fetchImpl: vi.fn(async () => response({ accounts: [] })) as unknown as typeof globalThis.fetch,
    });
    await expect(malformed.get({ companyId: "c", effectiveOn: "2026-11-27", transactionCurrency: "KRW" }))
      .rejects.toMatchObject({ status: "INVALID_RESPONSE" });

    const denied = createBusinessAccountCatalogClient({
      mode: "fetch",
      fetchImpl: vi.fn(async () => response({ error_code: "DENIED", detail: "denied" }, 403)) as unknown as typeof globalThis.fetch,
    });
    await expect(denied.get({ companyId: "c", effectiveOn: "2026-11-27", transactionCurrency: "KRW" }))
      .rejects.toMatchObject({ status: "DENIED", statusCode: 403 });
  });
});

function response(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
