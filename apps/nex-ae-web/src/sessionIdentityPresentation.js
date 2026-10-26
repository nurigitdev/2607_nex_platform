export const AE_WEB_SESSION_IDENTITY_PRESENTATION_SCHEMA_VERSION =
  "ae_web_session_identity_presentation.v1";

export function buildSessionIdentityPresentation({
  sessionState,
  employeeId = ""
} = {}) {
  const authenticated = sessionState?.status === "authenticated";
  const account = normalizedText(employeeId) || normalizedText(sessionState?.subjectRef?.id);

  return {
    session_identity_presentation_schema_version:
      AE_WEB_SESSION_IDENTITY_PRESENTATION_SCHEMA_VERSION,
    visible: authenticated,
    account: authenticated ? account || "authenticated-user" : "",
    subjectRef: authenticated ? normalizedText(sessionState?.subjectRef?.id) : ""
  };
}

function normalizedText(value) {
  return typeof value === "string" ? value.trim() : "";
}
