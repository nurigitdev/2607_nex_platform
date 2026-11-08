import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { App } from "./App";

afterEach(cleanup);

describe("modern application foundation", () => {
  it("mounts independently from the legacy application", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "UI Modernization Foundation" }),
    ).toBeTruthy();
    expect(screen.getByText("NeX AE")).toBeTruthy();
  });
});
