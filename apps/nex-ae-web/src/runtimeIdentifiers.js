export class RuntimeIdentifierError extends Error {
  constructor(message, { status = "RUNTIME_IDENTIFIER_UNAVAILABLE" } = {}) {
    super(message);
    this.name = "RuntimeIdentifierError";
    this.status = status;
  }
}

export function createInteractionId({ cryptoRef = globalThis.crypto } = {}) {
  if (typeof cryptoRef?.randomUUID !== "function") {
    throw new RuntimeIdentifierError(
      "Secure UUID generation is unavailable for the chat interaction."
    );
  }
  return cryptoRef.randomUUID();
}
