#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import {
  configuredPage,
  contextOptions,
  driveApprovalsUntilResult,
  launchBrowser,
  login,
  logout,
  myBeeM1RuntimeTimeouts,
  observeResponses,
  screenCapture,
  submitPrompt,
  waitForResult
} from "./runMyBeeW70CpM1ProductGoldenJourney.mjs";

export const W80_CA00F5_SPLIT_SCHEMA_VERSION =
  "mybee_w80_ca00f5_split_journey_playwright.v1";

const ENV = Object.freeze({
  webUrl: "NEX_MYBEE_W80_SPLIT_WEB_URL",
  tenantId: "NEX_MYBEE_W80_SPLIT_TENANT_ID",
  mode: "NEX_MYBEE_W80_SPLIT_MODE",
  prompt: "NEX_MYBEE_W80_SPLIT_PROMPT",
  submitterEmployeeId: "NEX_MYBEE_W80_SPLIT_SUBMITTER_EMPLOYEE_ID",
  submitterPassword: "NEX_MYBEE_W80_SPLIT_SUBMITTER_PASSWORD",
  businessApproverEmployeeId: "NEX_MYBEE_W80_SPLIT_BUSINESS_APPROVER_EMPLOYEE_ID",
  businessApproverPassword: "NEX_MYBEE_W80_SPLIT_BUSINESS_APPROVER_PASSWORD",
  accountingApproverEmployeeId: "NEX_MYBEE_W80_SPLIT_ACCOUNTING_APPROVER_EMPLOYEE_ID",
  accountingApproverPassword: "NEX_MYBEE_W80_SPLIT_ACCOUNTING_APPROVER_PASSWORD",
  screenshotDir: "NEX_MYBEE_W80_SPLIT_SCREENSHOT_DIR",
  recoveryInteractionId: "NEX_MYBEE_W80_SPLIT_RECOVERY_INTERACTION_ID"
});

const MODES = Object.freeze({
  journal: Object.freeze({
    resultHeading: "전표 등록 결과",
    approvalSequence: Object.freeze([
      Object.freeze({ domain: "BUSINESS_FORMAL", role: "BUSINESS_APPROVER" }),
      Object.freeze({ domain: "BUSINESS_FORMAL", role: "ACCOUNTING_APPROVER" }),
      Object.freeze({ domain: "NSL_WRITE", role: "ACCOUNTING_APPROVER" })
    ])
  }),
  allocation: Object.freeze({
    resultHeading: "프로젝트 배부 결과",
    approvalSequence: Object.freeze([
      Object.freeze({ domain: "NSL_WRITE", role: "ACCOUNTING_APPROVER" })
    ])
  })
});

export function splitJourneyContract(mode) {
  const contract = MODES[mode];
  if (!contract) throw new Error("SplitJourneyModeInvalid");
  return contract;
}

export function splitJourneyChecks({ mode, approvalDomains, approvalActorRoles }) {
  const expected = splitJourneyContract(mode).approvalSequence;
  const exact =
    approvalDomains.length === expected.length &&
    approvalActorRoles.length === expected.length &&
    expected.every(
      (item, index) =>
        approvalDomains[index] === item.domain &&
        approvalActorRoles[index] === item.role
    );
  return {
    exact_sequential_approval_observed: exact,
    journal_business_before_accounting:
      mode !== "journal" ||
      (approvalDomains[0] === "BUSINESS_FORMAL" &&
        approvalActorRoles[0] === "BUSINESS_APPROVER" &&
        approvalActorRoles[1] === "ACCOUNTING_APPROVER"),
    allocation_independent_from_business_approval:
      mode !== "allocation" || !approvalDomains.includes("BUSINESS_FORMAL")
  };
}

export async function runSplitJourney({
  environ = process.env,
  importPlaywright = () => import("playwright")
} = {}) {
  const mode = environ[ENV.mode];
  let contract;
  try {
    contract = splitJourneyContract(mode);
  } catch (error) {
    return failure(String(error.message || "SplitJourneyModeInvalid"));
  }
  const required = [
    ENV.webUrl,
    ENV.tenantId,
    ENV.prompt,
    ENV.submitterEmployeeId,
    ENV.submitterPassword,
    ENV.accountingApproverEmployeeId,
    ENV.accountingApproverPassword,
    ...(mode === "journal"
      ? [ENV.businessApproverEmployeeId, ENV.businessApproverPassword]
      : [])
  ];
  const missing = required.filter(name => !environ[name]);
  if (missing.length > 0) return failure("SplitJourneyRequiredEnvMissing", { missing_count: missing.length });

  const { actionTimeout, semanticSubmitTimeout, resultTimeout } =
    myBeeM1RuntimeTimeouts(environ);
  const captures = screenCapture(environ[ENV.screenshotDir], `w80-${mode}`);
  const responses = [];
  let browser;
  const contexts = [];
  let stage = "launch";
  try {
    const playwright = await importPlaywright();
    browser = await launchBrowser(playwright, environ);
    const submitter = await newPage(browser, contexts, responses);
    const accountingApprover = await newPage(browser, contexts, responses);
    const businessApprover = mode === "journal"
      ? await newPage(browser, contexts, responses)
      : null;

    stage = "submitter_login";
    await submitter.goto(environ[ENV.webUrl], { waitUntil: "domcontentloaded", timeout: actionTimeout });
    await login(submitter, {
      tenantId: environ[ENV.tenantId],
      employeeId: environ[ENV.submitterEmployeeId],
      password: environ[ENV.submitterPassword],
      timeout: actionTimeout
    });
    await captures.capture(submitter, "submitter-workspace", {
      expectedState: "SUBMITTER_WORKSPACE_READY",
      assertion: "workspace-heading-visible"
    });

    stage = "accounting_approver_login";
    await accountingApprover.goto(environ[ENV.webUrl], { waitUntil: "domcontentloaded", timeout: actionTimeout });
    await login(accountingApprover, {
      tenantId: environ[ENV.tenantId],
      employeeId: environ[ENV.accountingApproverEmployeeId],
      password: environ[ENV.accountingApproverPassword],
      timeout: actionTimeout
    });

    if (businessApprover) {
      stage = "business_approver_login";
      await businessApprover.goto(environ[ENV.webUrl], { waitUntil: "domcontentloaded", timeout: actionTimeout });
      await login(businessApprover, {
        tenantId: environ[ENV.tenantId],
        employeeId: environ[ENV.businessApproverEmployeeId],
        password: environ[ENV.businessApproverPassword],
        timeout: actionTimeout
      });
    }

    stage = "semantic_submit";
    const admitted = await submitPrompt(
      submitter,
      environ[ENV.prompt],
      semanticSubmitTimeout,
      { observeWorkspace: true }
    );
    const semanticPlanning = admitted.payload?.generation?.semantic_planning;
    if (
      !splitJourneyAdmissionAccepted({
        mode,
        httpStatus: admitted.status,
        semanticPlanning
      }) ||
      !admitted.payload?.interaction_id
    ) {
      throw new Error(`SplitJourneyAdmissionStatus${admitted.status}`);
    }
    const interactionId = admitted.payload.interaction_id;
    await captures.capture(submitter, "request-admitted", {
      expectedState: "REQUEST_ADMITTED",
      assertion: "request-message-visible",
      interactionId
    });

    stage = "approval_and_result";
    const approvers = [
      ...(businessApprover
        ? [{ role: "BUSINESS_APPROVER", page: businessApprover }]
        : []),
      { role: "ACCOUNTING_APPROVER", page: accountingApprover }
    ];
    const completed = await driveApprovalsUntilResult({
      requester: submitter,
      approvers,
      interactionId,
      actionTimeout,
      resultTimeout,
      captures,
      transactionIndex: 1
    });
    if (completed.result?.status !== "SUCCEEDED") {
      throw new Error("SplitJourneyResultNotSucceeded");
    }
    const resultRegion = submitter.locator('[data-ux-region="primary-result"]');
    await resultRegion.getByRole("heading", { name: contract.resultHeading, exact: true }).waitFor({
      timeout: actionTimeout
    });
    await captures.capture(submitter, "result-rendered", {
      expectedState: "RESULT_RENDERED",
      assertion: mode === "journal" ? "journal-result-visible" : "allocation-result-visible",
      interactionId
    });

    const checks = {
      live_plan_compiled: splitJourneyAdmissionAccepted({
        mode,
        httpStatus: admitted.status,
        semanticPlanning
      }),
      terminal_result_succeeded: completed.terminal === true && completed.result?.status === "SUCCEEDED",
      delivery_acknowledged: completed.result?.delivery?.state === "ACKNOWLEDGED",
      result_heading_rendered: true,
      approval_replay_idempotent: completed.replayStatuses.every(status => status === 200),
      ...splitJourneyChecks({
        mode,
        approvalDomains: completed.approvalDomains,
        approvalActorRoles: completed.approvalActorRoles
      })
    };
    await logout(submitter, actionTimeout);
    const evidence = {
      smoke_schema_version: W80_CA00F5_SPLIT_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      mode,
      observations: {
        approval_domains: completed.approvalDomains,
        approval_actor_roles: completed.approvalActorRoles,
        authenticated_http_response_count: responses.length
      },
      screen_capture: captures.evidence(),
      checks,
      runtime: {
        interaction_id: interactionId,
        workspace_id: admitted.workspace?.workspace_id,
        chat_document_id: admitted.workspace?.chat_document_id,
        result_projection: completed
      }
    };
    assertRedacted(evidence, environ);
    return evidence;
  } catch (error) {
    const evidence = failure(safeCode(error), {
      mode,
      stage,
      recent_api_responses: responses.slice(-8)
    });
    evidence.screen_capture = captures.evidence();
    assertRedacted(evidence, environ);
    return evidence;
  } finally {
    for (const context of contexts.reverse()) await context.close();
    if (browser) await browser.close();
  }
}

export function splitJourneyAdmissionAccepted({ mode, httpStatus, semanticPlanning }) {
  splitJourneyContract(mode);
  if (httpStatus !== 202 || !semanticPlanning) return false;
  const stages = semanticPlanning.stages;
  if (!Array.isArray(stages)) return false;
  if (mode === "journal") {
    return semanticPlanning.status === "COMPILED" && stages.length === 3;
  }
  return semanticPlanning.status === "PRODUCT_COORDINATION_STARTED" &&
    semanticPlanning.directive === "WAIT_FOR_PRODUCT_COORDINATION" &&
    semanticPlanning.product_planning_admission != null &&
    stages.length === 2 &&
    stages[0]?.semantic_stage === "INTENT" &&
    stages[1]?.semantic_stage === "CONTEXT";
}

export async function runSplitJourneyRecovery({
  environ = process.env,
  importPlaywright = () => import("playwright")
} = {}) {
  const mode = environ[ENV.mode];
  let contract;
  try {
    contract = splitJourneyContract(mode);
  } catch (error) {
    return failure(String(error.message || "SplitJourneyModeInvalid"));
  }
  const required = [
    ENV.webUrl,
    ENV.tenantId,
    ENV.submitterEmployeeId,
    ENV.submitterPassword,
    ENV.recoveryInteractionId
  ];
  const missing = required.filter(name => !environ[name]);
  if (missing.length > 0) return failure("SplitJourneyRecoveryEnvMissing", { missing_count: missing.length });
  const { actionTimeout, resultTimeout } = myBeeM1RuntimeTimeouts(environ);
  const captures = screenCapture(environ[ENV.screenshotDir], `w80-${mode}-recovery`);
  let browser;
  let context;
  try {
    const playwright = await importPlaywright();
    browser = await launchBrowser(playwright, environ);
    context = await browser.newContext(contextOptions());
    const page = await configuredPage(context);
    await page.goto(environ[ENV.webUrl], { waitUntil: "domcontentloaded", timeout: actionTimeout });
    await login(page, {
      tenantId: environ[ENV.tenantId],
      employeeId: environ[ENV.submitterEmployeeId],
      password: environ[ENV.submitterPassword],
      timeout: actionTimeout
    });
    const interactionId = environ[ENV.recoveryInteractionId];
    const projection = await waitForResult(page, interactionId, resultTimeout);
    const recoveryUrl = new URL("/workspace", environ[ENV.webUrl]);
    recoveryUrl.searchParams.set("interaction_id", interactionId);
    await page.goto(recoveryUrl.toString(), { waitUntil: "domcontentloaded", timeout: actionTimeout });
    await page.locator('[data-ux-region="primary-result"]')
      .getByRole("heading", { name: contract.resultHeading, exact: true })
      .waitFor({ timeout: actionTimeout });
    await captures.capture(page, "result-recovered", {
      expectedState: "RESULT_RECOVERED",
      assertion: mode === "journal" ? "journal-result-recovered" : "allocation-result-recovered",
      interactionId
    });
    const checks = {
      authoritative_result_recovered: projection.terminal === true,
      recovered_result_succeeded: projection.result?.status === "SUCCEEDED",
      recovered_delivery_acknowledged: projection.result?.delivery?.state === "ACKNOWLEDGED",
      recovered_result_heading_rendered: true
    };
    const evidence = {
      smoke_schema_version: W80_CA00F5_SPLIT_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      mode,
      recovery_mode: true,
      screen_capture: captures.evidence(),
      checks,
      runtime: { interaction_id: interactionId, result_projection: projection }
    };
    assertRedacted(evidence, environ);
    return evidence;
  } catch (error) {
    return failure(safeCode(error), { mode, recovery_mode: true });
  } finally {
    if (context) await context.close();
    if (browser) await browser.close();
  }
}

async function newPage(browser, contexts, responses) {
  const context = await browser.newContext(contextOptions());
  contexts.push(context);
  const page = await configuredPage(context);
  observeResponses(page, responses);
  return page;
}

function failure(failureCode, observations = {}) {
  return {
    smoke_schema_version: W80_CA00F5_SPLIT_SCHEMA_VERSION,
    status: "FAIL",
    failure_code: failureCode,
    observations,
    checks: {}
  };
}

function safeCode(error) {
  const value = String(error?.message || "SplitJourneyFailed");
  return /^[A-Za-z][A-Za-z0-9_.-]{0,95}$/.test(value)
    ? value
    : "SplitJourneyFailed";
}

function assertRedacted(evidence, environ) {
  const serialized = JSON.stringify(evidence);
  for (const name of [
    ENV.prompt,
    ENV.submitterPassword,
    ENV.businessApproverPassword,
    ENV.accountingApproverPassword
  ]) {
    const value = environ[name];
    if (value && value.length >= 8 && serialized.includes(value)) {
      throw new Error(`SplitJourneyEvidenceLeak${name}`);
    }
  }
}

export async function main(output = console.log) {
  const evidence = process.argv.includes("--recovery")
    ? await runSplitJourneyRecovery()
    : await runSplitJourney();
  output(JSON.stringify(evidence));
  return evidence.status === "PASS" ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
