export type LegacyClientMode = "mock" | "fetch";

export interface RuntimeFeatureFlags {
  readonly approval_inbox_enabled: boolean;
  readonly document_detail_enabled: boolean;
  readonly upload_submit_enabled: boolean;
  readonly retrieval_submit_enabled: boolean;
  readonly fetch_clients_enabled: boolean;
}

export interface RuntimeConfigInput {
  readonly client_mode?: LegacyClientMode;
  readonly clientMode?: LegacyClientMode;
  readonly ae_base_url?: string;
  readonly aeBaseUrl?: string;
  readonly features?: Partial<RuntimeFeatureFlags>;
}

export interface RuntimeProjection {
  readonly schemaVersion: string;
  readonly clientMode: LegacyClientMode;
  readonly aeBaseUrl: string;
  readonly features: RuntimeFeatureFlags;
  readonly metadata: Readonly<Record<string, boolean>>;
}

export interface ClientGatewaySummary {
  readonly schemaVersion: string;
  readonly clientMode: LegacyClientMode;
  readonly baseUrl: string;
  readonly clients: Readonly<Record<string, LegacyClientMode>>;
  readonly metadata: Readonly<Record<string, boolean>>;
}
