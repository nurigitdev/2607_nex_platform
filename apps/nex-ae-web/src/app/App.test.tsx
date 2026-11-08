import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { SessionState } from "./domain/session";
import type { SessionClientPort } from "./legacyAdapters/sessionAdapter";

afterEach(cleanup);

const memberSession: SessionState = {
  status: "authenticated",
  sessionId: "session-1",
  tenantRef: { type: "oa.tenant", id: "VO00" },
  subjectRef: { type: "oa.user", id: "employee-1" },
  scopes: [],
  roles: ["member"],
};

function sessionClient({
  loginResult = memberSession,
  loginError,
}: {
  readonly loginResult?: SessionState;
  readonly loginError?: Error & { status?: string };
} = {}) {
  const anonymous: SessionState = {
    status: "anonymous",
    scopes: [],
    roles: [],
    reason: "not_authenticated",
  };
  const loggedOut: SessionState = { ...anonymous, reason: "logout" };
  const login = vi.fn(async () => {
    if (loginError) throw loginError;
    return loginResult;
  });
  const client: SessionClientPort = {
    getCurrentSession: vi.fn(async () => anonymous),
    login,
    logout: vi.fn(async () => loggedOut),
  };
  return { client, login };
}

describe("modern application foundation", () => {
  it("redirects an anonymous visitor to the login route", async () => {
    window.history.pushState({}, "", "/workspace");
    render(<App />);

    expect(await screen.findByRole("heading", { name: "사번 로그인" })).toBeTruthy();
    expect(screen.getByText("NeX AE")).toBeTruthy();
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

  it("submits the existing credential contract and activates the requested route", async () => {
    const user = userEvent.setup();
    const { client, login } = sessionClient();
    window.history.pushState({}, "", "/approvals");
    render(<App sessionClient={client} tenantId="VO00" />);

    await user.type(await screen.findByLabelText(/^사번\s*\*?$/), "EMP-1001");
    await user.type(screen.getByLabelText(/^비밀번호\s*\*?$/), "Nuri1004!{Enter}");

    expect(await screen.findByRole("heading", { name: "승인함" })).toBeTruthy();
    expect(screen.getByText("EMP-1001")).toBeTruthy();
    expect(login).toHaveBeenCalledWith({
      tenant_id: "VO00",
      employee_id: "EMP-1001",
      password: "Nuri1004!",
      requested_scopes: ["workspace:use"],
      ttl_seconds: 3600,
    });
  });

  it("validates fields without submitting credential material", async () => {
    const user = userEvent.setup();
    const { client, login } = sessionClient();
    window.history.pushState({}, "", "/login");
    render(<App sessionClient={client} />);

    await user.click(await screen.findByRole("button", { name: "로그인" }));

    expect(screen.getByText("사번을 입력해 주세요.")).toBeTruthy();
    expect(screen.getByText("비밀번호를 입력해 주세요.")).toBeTruthy();
    expect(login).not.toHaveBeenCalled();
  });

  it("maps invalid credentials and clears the password field", async () => {
    const user = userEvent.setup();
    const error = Object.assign(new Error("unauthorized"), { status: "HTTP_401" });
    const { client } = sessionClient({ loginError: error });
    window.history.pushState({}, "", "/login");
    render(<App sessionClient={client} />);

    await user.type(await screen.findByLabelText(/^사번\s*\*?$/), "EMP-1001");
    const password = screen.getByLabelText(/^비밀번호\s*\*?$/) as HTMLInputElement;
    await user.type(password, "wrong-password{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("사번 또는 비밀번호를 확인해 주세요.");
    expect(password.value).toBe("");
    expect(document.body.textContent).not.toContain("wrong-password");
  });

  it("supports password visibility and Caps Lock indication", async () => {
    const user = userEvent.setup();
    const { client } = sessionClient();
    window.history.pushState({}, "", "/login");
    render(<App sessionClient={client} />);

    const password = await screen.findByLabelText(/^비밀번호\s*\*?$/) as HTMLInputElement;
    expect(password.type).toBe("password");
    await user.click(screen.getByRole("button", { name: "비밀번호 보기" }));
    expect(password.type).toBe("text");
    const keyboardEvent = new KeyboardEvent("keydown", { key: "A", bubbles: true });
    Object.defineProperty(keyboardEvent, "getModifierState", { value: () => true });
    fireEvent(password, keyboardEvent);
    expect(screen.getByRole("status")).toHaveTextContent("Caps Lock이 켜져 있습니다.");
  });

  it("clears the local session immediately on logout", async () => {
    const user = userEvent.setup();
    const { client } = sessionClient();
    window.history.pushState({}, "", "/workspace");
    render(<App initialSession={memberSession} sessionClient={client} />);

    await user.click(await screen.findByRole("button", { name: "로그아웃" }));

    expect(await screen.findByRole("heading", { name: "사번 로그인" })).toBeTruthy();
    await waitFor(() => expect(window.location.pathname).toBe("/login"));
  });

  it("shows an expiration message without technical session metadata", async () => {
    window.history.pushState({}, "", "/workspace");
    render(<App initialSession={{ ...memberSession, status: "expired", reason: "expired" }} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("세션이 만료되었습니다.");
    expect(document.body.textContent).not.toContain("READY_FOR_LOGIN");
    expect(document.body.textContent).not.toContain("session schema");
    expect(screen.queryByLabelText("테넌트")).toBeNull();
  });
});
