import { buildCredentialLoginRequest } from "../../credentialLoginSurface.js";
import {
  createFetchSessionClient,
  createMockSessionClient,
} from "../../sessionClient.js";
import { buildSessionIdentityPresentation } from "../../sessionIdentityPresentation.js";

import type { SessionState } from "../domain/session";

export interface SessionLoginInput {
  readonly tenantId: string;
  readonly employeeId: string;
  readonly password: string;
}

export interface SessionClientPort {
  readonly getCurrentSession: () => Promise<SessionState>;
  readonly login: (request: Readonly<Record<string, unknown>>) => Promise<SessionState>;
  readonly logout: () => Promise<SessionState>;
}

export function createModernSessionClient({
  mode = "mock",
  baseUrl = "",
  fetchImpl,
}: {
  readonly mode?: "mock" | "fetch";
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof globalThis.fetch;
} = {}): SessionClientPort {
  const client = mode === "fetch"
    ? createFetchSessionClient({ baseUrl, fetchImpl })
    : createMockSessionClient();
  return client as unknown as SessionClientPort;
}

export function buildModernCredentialLoginRequest(input: SessionLoginInput) {
  const buildRequest = buildCredentialLoginRequest as unknown as (options: {
    readonly tenantId: string;
    readonly employeeId: string;
    readonly password: string;
  }) => Readonly<Record<string, unknown>>;
  return buildRequest({
    tenantId: input.tenantId,
    employeeId: input.employeeId,
    password: input.password,
  });
}

export function projectSessionIdentity({
  sessionState,
  employeeId,
}: {
  readonly sessionState: SessionState;
  readonly employeeId?: string;
}) {
  const buildPresentation = buildSessionIdentityPresentation as unknown as (options: {
    readonly sessionState: SessionState;
    readonly employeeId?: string;
  }) => { readonly visible: boolean; readonly account: string };
  const presentation = buildPresentation({ sessionState, employeeId });
  return Object.freeze({
    visible: presentation.visible,
    account: presentation.account,
  });
}
