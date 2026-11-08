import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { App } from "./App";
import type { SessionState } from "./domain/session";

afterEach(cleanup);

const memberSession: SessionState = {
  status: "authenticated",
  sessionId: "session-1",
  tenantRef: { type: "oa.tenant", id: "VO00" },
  subjectRef: { type: "oa.user", id: "employee-1" },
  scopes: [],
  roles: ["member"],
};

describe("modern application foundation", () => {
  it("redirects an anonymous visitor to the login route", async () => {
    window.history.pushState({}, "", "/workspace");
    render(<App />);

    expect(await screen.findByRole("heading", { name: "NeX AE" })).toBeTruthy();
    expect(window.location.pathname).toBe("/login");
  });

  it("renders an authenticated application route", async () => {
    window.history.pushState({}, "", "/documents");
    render(<App initialSession={memberSession} />);

    expect(await screen.findByRole("heading", { name: "문서" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "주요 탐색" })).toBeTruthy();
  });

  it("guards operations routes by the legacy role policy", async () => {
    window.history.pushState({}, "", "/operations");
    render(<App initialSession={memberSession} />);

    expect(await screen.findByRole("heading", { name: "워크스페이스" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "운영/진단" })).toBeNull();
    expect(window.location.pathname).toBe("/workspace");
  });

  it("allows an operator to enter the operations route", async () => {
    window.history.pushState({}, "", "/operations");
    render(<App initialSession={{ ...memberSession, roles: ["operator"] }} />);

    expect(await screen.findByRole("heading", { name: "운영/진단" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "운영/진단" })).toBeTruthy();
  });

  it("returns an unknown authenticated route to the workspace", async () => {
    window.history.pushState({}, "", "/not-a-route");
    render(<App initialSession={memberSession} />);

    expect(await screen.findByRole("heading", { name: "워크스페이스" })).toBeTruthy();
    expect(window.location.pathname).toBe("/workspace");
  });

  it("keeps the core navigation available for compact viewports", async () => {
    window.history.pushState({}, "", "/workspace");
    window.matchMedia = query => ({
      matches: query === "(max-width: 760px)",
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    });
    render(<App initialSession={memberSession} />);

    expect(await screen.findByRole("link", { name: "워크스페이스" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "승인함" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "문서" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "아티팩트" })).toBeTruthy();
  });
});
