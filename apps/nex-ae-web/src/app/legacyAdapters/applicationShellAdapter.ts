import {
  buildApplicationShellSummary,
  resolveApplicationShell,
} from "../../applicationShell.js";

interface LegacyApplicationShell {
  readonly application_shell_schema_version: string;
  readonly authenticated: boolean;
  readonly activeView: string | null;
  readonly allowedViews: readonly string[];
  readonly operationsVisible: boolean;
}

export interface ApplicationShellProjection {
  readonly schemaVersion: string;
  readonly authenticated: boolean;
  readonly currentView: string;
  readonly defaultView: string;
  readonly allowedViews: readonly string[];
  readonly operationsVisible: boolean;
}

export function projectApplicationShell({
  sessionState,
  requestedView,
}: {
  readonly sessionState: unknown;
  readonly requestedView?: string;
}): ApplicationShellProjection {
  const resolveShell = resolveApplicationShell as unknown as (options: {
    sessionState: unknown;
    requestedView?: string;
  }) => LegacyApplicationShell;
  const shell = resolveShell({ sessionState, requestedView });
  const summary = buildApplicationShellSummary(shell);

  return Object.freeze({
    schemaVersion: summary.application_shell_schema_version,
    authenticated: summary.authenticated,
    currentView: summary.active_view ?? "login",
    defaultView: shell.authenticated ? "workspace" : "login",
    allowedViews: Object.freeze(
      shell.authenticated ? [...shell.allowedViews] : ["login"],
    ),
    operationsVisible: summary.operations_visible,
  });
}
