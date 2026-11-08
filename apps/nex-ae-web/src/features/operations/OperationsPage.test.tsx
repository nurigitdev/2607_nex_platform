import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OperationsPage } from "./OperationsPage";

const SUMMARY = Object.freeze({
  overallStatus: "READY",
  services: Object.freeze([
    Object.freeze({ serviceId: "nex-ae-api", healthStatus: "HEALTHY", readinessStatus: "READY", version: "2.1.0" }),
    Object.freeze({ serviceId: "nex-mo", healthStatus: "UNKNOWN", readinessStatus: "NOT_OBSERVED", version: null }),
  ]),
  runtime: Object.freeze({ databaseStatus: "AVAILABLE", agentRuntimeStatus: "AVAILABLE", providerRouteStatus: "CONFIGURED" }),
  routes: Object.freeze([Object.freeze({ routeId: "ae-web-operations-summary", method: "GET", path: "/api/v1/web/operations/summary" })]),
});

describe("Operations page", () => {
  it("renders safe operator diagnostics without endpoints, ports, or credentials", () => {
    render(<OperationsPage summary={SUMMARY} />);
    expect(screen.getByRole("heading", { name: "운영/진단" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "서비스 상태" })).toBeInTheDocument();
    expect(screen.getByText("nex-ae-api")).toBeInTheDocument();
    expect(screen.getByText("/api/v1/web/operations/summary")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/127\.0\.0\.1:81\d\d|password|service_token|provider_endpoint/i);
  });

  it("supports refresh and bounded unavailable guidance", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn();
    const { rerender } = render(<OperationsPage summary={SUMMARY} onRefresh={onRefresh} />);
    await user.click(screen.getByRole("button", { name: "새로고침" }));
    expect(onRefresh).toHaveBeenCalledOnce();
    rerender(<OperationsPage error="운영 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요." />);
    expect(screen.getByRole("alert")).toHaveTextContent("운영 정보를 불러오지 못했습니다.");
    expect(screen.getByText("운영 정보를 표시할 수 없습니다")).toBeInTheDocument();
  });
});
