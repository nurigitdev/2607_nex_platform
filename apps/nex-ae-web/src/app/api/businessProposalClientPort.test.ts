import { describe, expect, it, vi } from "vitest";

import { createBusinessProposalClient } from "./businessProposalClientPort";

describe("business proposal client port", () => {
  it("uses only the same-origin AE facade and preserves preview effective time", async () => {
    const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes(":preview-approval")) {
        return response({
          preview_hash: "sha256:" + "a".repeat(64),
          proposal_id: PROPOSAL_ID,
          revision_no: 1,
          proposal_version: 1,
          effective_at: "2026-11-26T09:00:00+00:00",
          required_stages: [{
            stage_order: 1,
            position_type: "TEAM_LEAD",
            candidates: [{
              subject_id: "lead-1",
              display_name: "김 팀장",
              authority_hash: "sha256:" + "b".repeat(64),
            }],
          }],
          normalized_amount_evidence: { normalized_amount: "1000.0000", functional_currency: "KRW" },
        });
      }
      return response({ approval_line_hash: "sha256:" + "c".repeat(64) });
    }) as unknown as typeof globalThis.fetch;
    const client = createBusinessProposalClient({ mode: "fetch", baseUrl: "/ae-api", fetchImpl });
    const preview = await client.previewApproval(PROPOSAL_ID, "2026-11-26T09:00:00Z");
    await client.selectApprovalLine(PROPOSAL_ID, {
      preview,
      selectedApprovers: [{ stage_order: 1, subject_id: "lead-1" }],
    });

    expect(fetchImpl).toHaveBeenNthCalledWith(
      1,
      `/ae-api/api/v1/business-proposals/${PROPOSAL_ID}:preview-approval`,
      expect.objectContaining({ credentials: "include" }),
    );
    expect(JSON.parse(String((fetchImpl as ReturnType<typeof vi.fn>).mock.calls[1][1]?.body))).toEqual(
      expect.objectContaining({ effective_at: "2026-11-26T09:00:00+00:00" }),
    );
  });

  it("fails closed on malformed list responses", async () => {
    const client = createBusinessProposalClient({
      mode: "fetch",
      fetchImpl: vi.fn(async () => response({ items: "unsafe" })) as unknown as typeof globalThis.fetch,
    });
    await expect(client.list()).rejects.toMatchObject({ status: "BUSINESS_PROPOSAL_RESPONSE_INVALID" });
  });
});

const PROPOSAL_ID = "d1000000-0000-4000-8000-000000000031";
function response(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
