import {
  applyGenerationAdmission,
  applyGenerationRecovery,
  buildGenerationLifecycleReadModel,
  createGenerationLifecycleState,
  markGenerationActionFailure,
  markGenerationActionRunning
} from "./generationLifecycleState.js";
import { runGroundedGenerationWorkflow } from "./groundedGenerationWorkflow.js";

export const AE_WEB_GROUNDED_GENERATION_RECOVERY_SCHEMA_VERSION =
  "ae_web_grounded_generation_recovery.v1";

export class GroundedGenerationRecoveryError extends Error {
  constructor(message, { status = "GENERATION_RECOVERY_ACTION_INVALID" } = {}) {
    super(message);
    this.name = "GroundedGenerationRecoveryError";
    this.status = status;
  }
}

export async function cancelGroundedGeneration({ client, state, onState = () => {} }) {
  assertClient(client);
  const controls = buildGenerationLifecycleReadModel(state).controls;
  if (!controls.cancelEnabled) {
    throw new GroundedGenerationRecoveryError("Generation cannot be cancelled.", {
      status: "GENERATION_CANCEL_NOT_ALLOWED"
    });
  }
  let next = markGenerationActionRunning(state, "cancel");
  onState(next);
  try {
    const cancellation = await client.cancelInteraction(next.interactionId);
    next = applyGenerationAdmission(next, cancellation);
    onState(next);
    return buildActionResult("CANCEL", next);
  } catch (error) {
    next = markGenerationActionFailure(next, error);
    onState(next);
    throw error;
  }
}

export async function inspectGroundedGenerationRecovery({
  client,
  state,
  onState = () => {}
}) {
  assertClient(client);
  if (!state?.interactionId || state.terminal !== true) {
    throw new GroundedGenerationRecoveryError(
      "Recovery inspection requires a terminal interaction.",
      { status: "GENERATION_RECOVERY_NOT_ALLOWED" }
    );
  }
  let next = markGenerationActionRunning(state, "recovery");
  onState(next);
  try {
    const recovery = await client.getRecovery(next.interactionId);
    next = applyGenerationRecovery(next, recovery);
    onState(next);
    return buildActionResult("RECOVERY", next);
  } catch (error) {
    next = markGenerationActionFailure(next, error);
    onState(next);
    throw error;
  }
}

export async function retryGroundedGeneration({
  client,
  state,
  request,
  onState = () => {},
  wait,
  maxPolls = 30,
  signal = null
}) {
  const inspected = await inspectGroundedGenerationRecovery({
    client,
    state,
    onState
  });
  if (!inspected.state.retryable) {
    throw new GroundedGenerationRecoveryError("Generation retry is not eligible.", {
      status: "GENERATION_RETRY_NOT_ELIGIBLE"
    });
  }
  if (
    !request ||
    typeof request !== "object" ||
    request.interaction_id === state.interactionId
  ) {
    throw new GroundedGenerationRecoveryError(
      "Generation retry requires a new interaction.",
      { status: "GENERATION_RETRY_INTERACTION_REQUIRED" }
    );
  }

  const retryClient = {
    ...client,
    admitInteraction: payload => client.retryInteraction(state.interactionId, payload)
  };
  const workflow = await runGroundedGenerationWorkflow({
    client: retryClient,
    request,
    initialState: createGenerationLifecycleState({ clientMode: client.clientMode }),
    onState,
    wait,
    maxPolls,
    signal
  });
  return {
    ...workflow,
    recoverySchemaVersion: AE_WEB_GROUNDED_GENERATION_RECOVERY_SCHEMA_VERSION,
    action: "RETRY",
    parentInteractionId: state.interactionId,
    summary: {
      ...workflow.summary,
      action: "RETRY",
      parent_interaction_id_included: true,
      raw_prompt_included: false
    }
  };
}

function buildActionResult(action, state) {
  return {
    recoverySchemaVersion: AE_WEB_GROUNDED_GENERATION_RECOVERY_SCHEMA_VERSION,
    action,
    status: "COMPLETED",
    state,
    readModel: buildGenerationLifecycleReadModel(state),
    summary: {
      recovery_schema_version:
        AE_WEB_GROUNDED_GENERATION_RECOVERY_SCHEMA_VERSION,
      action,
      lifecycle_status: state.lifecycleStatus,
      recovery_action: state.recovery?.action || null,
      recovery_eligible: Boolean(state.recovery?.eligible),
      raw_prompt_included: false,
      generated_content_included: false,
      browser_service_token_included: false
    }
  };
}

function assertClient(client) {
  if (
    !client ||
    typeof client.cancelInteraction !== "function" ||
    typeof client.retryInteraction !== "function" ||
    typeof client.getRecovery !== "function"
  ) {
    throw new GroundedGenerationRecoveryError("Generation client is invalid.", {
      status: "GENERATION_RECOVERY_CLIENT_INVALID"
    });
  }
}
