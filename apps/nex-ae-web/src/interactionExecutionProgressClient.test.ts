import { describe, expect, it, vi } from "vitest";

import {
  createFetchInteractionExecutionProgressClient,
  interactionExecutionProgressRoute,
  projectInteractionExecutionProgress,
} from "./interactionExecutionProgressClient.js";

const INTERACTION = "10000000-0000-4000-8000-000000000001";
const WORKSPACE = "20000000-0000-4000-8000-000000000001";

describe("interaction execution progress client", () => {
  it("projects ordered safe events and Korean presentation messages", () => {
    const projection = projectInteractionExecutionProgress(payload());

    expect(projection).toMatchObject({
      interactionId: INTERACTION,
      terminal: false,
      nextSequence: 2,
      rawPromptIncluded: false,
      privatePayloadIncluded: false,
    });
    expect(projection.events.map(event => event.message)).toEqual([
      "IA가 요청을 접수했습니다.",
      "IA가 요청 의도를 파악하고 있습니다.",
    ]);
  });

  it("uses owner-cookie fetch mode and cursor route", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify(payload()), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    const client = createFetchInteractionExecutionProgressClient({
      baseUrl: "/ae-api",
      fetchImpl,
    });

    await client.getInteractionExecutionProgress(INTERACTION, 1);

    expect(interactionExecutionProgressRoute(INTERACTION, 1)).toContain("after_sequence=1");
    expect(fetchImpl).toHaveBeenCalledWith(
      expect.stringContaining("/execution-progress?after_sequence=1"),
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
  });

  it("rejects unordered projections and invalid cursors", () => {
    const unordered = payload();
    unordered.events[1]!.sequence = 1;
    expect(() => projectInteractionExecutionProgress(unordered)).toThrow(
      "projection is invalid",
    );
    expect(() => interactionExecutionProgressRoute(INTERACTION, -1)).toThrow(
      "afterSequence is invalid",
    );
  });
});

function payload() {
  return {
    schema_version: "ae_interaction_execution_progress.v1",
    interaction_id: INTERACTION,
    workspace_id: WORKSPACE,
    status: "IN_PROGRESS",
    terminal: false,
    next_sequence: 2,
    events: [
      event(1, "CHAT_REQUEST_ACCEPTED"),
      event(2, "IA_INTENT_STARTED"),
    ],
    metadata: {
      owner_scoped: true,
      ordered_projection: true,
      raw_prompt_included: false,
      private_payload_included: false,
      debug_time_available: true,
    },
  };
}

function event(sequence: number, eventCode: string) {
  return {
    event_id: `${sequence}0000000-0000-4000-8000-000000000001`,
    sequence,
    event_code: eventCode,
    state: "STARTED",
    agent_type: "IA",
    source_ref: null,
    occurred_at: `2026-11-25T01:02:0${sequence}Z`,
    terminal: false,
  };
}
