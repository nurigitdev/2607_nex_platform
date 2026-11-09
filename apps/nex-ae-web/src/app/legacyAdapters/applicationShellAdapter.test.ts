import { describe, expect, it } from "vitest";

import { createAnonymousSessionState } from "../../sessionClient.js";
import { projectApplicationShell } from "./applicationShellAdapter";

describe("application shell legacy adapter", () => {
  it("projects anonymous state without exposing legacy internals", () => {
    const projection = projectApplicationShell({
      sessionState: createAnonymousSessionState(),
      requestedView: "operations",
    });

    expect(projection).toMatchObject({
      authenticated: false,
      currentView: "login",
      operationsVisible: false,
    });
    expect(projection.allowedViews).toEqual(["login"]);
  });
});
