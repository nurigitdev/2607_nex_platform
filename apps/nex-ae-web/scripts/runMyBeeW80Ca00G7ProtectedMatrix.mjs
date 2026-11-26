#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

import {
  browserJson,
  configuredPage,
  contextOptions,
  launchBrowser,
  login,
  logout,
  myBeeM1RuntimeTimeouts,
  observeResponses,
  pendingApprovalGates,
  prepareApprovalInbox,
  readResult,
  screenCapture,
  submitPrompt
} from "./runMyBeeW70CpM1ProductGoldenJourney.mjs";

export const W80_CA00G7_SCHEMA_VERSION =
  "mybee_w80_ca00g7_protected_live_matrix.v1";

const ENV = Object.freeze({
  webUrl: "NEX_MYBEE_W80_CA00G7_WEB_URL",
  tenantId: "NEX_MYBEE_W80_CA00G7_TENANT_ID",
  scenarios: "NEX_MYBEE_W80_CA00G7_SCENARIOS_JSON",
  requesterEmployeeId: "NEX_MYBEE_W80_CA00G7_REQUESTER_EMPLOYEE_ID",
  requesterPassword: "NEX_MYBEE_W80_CA00G7_REQUESTER_PASSWORD",
  requesterSubjectId: "NEX_MYBEE_W80_CA00G7_REQUESTER_SUBJECT_ID",
  businessEmployeeId: "NEX_MYBEE_W80_CA00G7_BUSINESS_EMPLOYEE_ID",
  businessPassword: "NEX_MYBEE_W80_CA00G7_BUSINESS_PASSWORD",
  businessSubjectId: "NEX_MYBEE_W80_CA00G7_BUSINESS_SUBJECT_ID",
  accountingEmployeeId: "NEX_MYBEE_W80_CA00G7_ACCOUNTING_EMPLOYEE_ID",
  accountingPassword: "NEX_MYBEE_W80_CA00G7_ACCOUNTING_PASSWORD",
  screenshotDir: "NEX_MYBEE_W80_CA00G7_SCREENSHOT_DIR"
});

const pageCredentials = new WeakMap();

export function parseProtectedScenarios(raw) {
  let values;
  try {
    values = JSON.parse(raw || "");
  } catch {
    throw new Error("ProtectedMatrixScenariosInvalid");
  }
  if (!Array.isArray(values) || values.length !== 6) {
    throw new Error("ProtectedMatrixScenarioCountInvalid");
  }
  const ids = new Set();
  return values.map((item, index) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      throw new Error("ProtectedMatrixScenarioInvalid");
    }
    const scenarioId = String(item.scenario_id || "");
    const prompt = String(item.prompt || "");
    const expectedStages = Number(item.expected_business_stages);
    const outcome = String(item.outcome || "");
    if (
      !/^[a-z][a-z0-9-]{2,63}$/.test(scenarioId) ||
      ids.has(scenarioId) ||
      prompt.length < 20 ||
      ![1, 2, 3].includes(expectedStages) ||
      ![
        "ENVELOPE_ONLY",
        "JOURNAL_SUCCESS",
        "MIDDLE_REJECTION",
        "FINAL_REJECTION",
        "ACCOUNTING_CORRECTION"
      ].includes(outcome)
    ) {
      throw new Error(`ProtectedMatrixScenarioInvalid${index + 1}`);
    }
    ids.add(scenarioId);
    return Object.freeze({
      scenarioId,
      prompt,
      expectedStages,
      outcome
    });
  });
}

export function protectedMatrixChecks(results) {
  const byOutcome = new Map(results.map(item => [item.outcome, item]));
  const successes = results.filter(item =>
    ["ENVELOPE_ONLY", "JOURNAL_SUCCESS", "ACCOUNTING_CORRECTION"].includes(item.outcome)
  );
  const rejections = results.filter(item => item.outcome.endsWith("REJECTION"));
  return {
    six_independent_journeys: results.length === 6 &&
      new Set(results.map(item => item.scenario_id)).size === 6,
    one_two_three_stage_routes_observed:
      [1, 2, 3].every(count => results.some(item => item.business_stage_count === count)),
    successful_routes_materialized_exact_envelopes:
      successes.every(item => item.approved_envelope_present === true),
    middle_rejection_is_terminal:
      byOutcome.get("MIDDLE_REJECTION")?.rejected_stage === 2,
    final_rejection_is_terminal:
      byOutcome.get("FINAL_REJECTION")?.rejected_stage === 3,
    rejected_routes_created_no_voucher:
      rejections.every(item => item.voucher_created === false),
    journal_route_completed:
      byOutcome.get("JOURNAL_SUCCESS")?.terminal_status === "SUCCEEDED",
    correction_used_latest_revision:
      byOutcome.get("ACCOUNTING_CORRECTION")?.correction_cycle === 1 &&
      byOutcome.get("ACCOUNTING_CORRECTION")?.terminal_status === "SUCCEEDED",
    all_decision_replays_idempotent:
      results.every(item => item.decision_replay_statuses.every(status => status === 200)),
    all_screen_evidence_present:
      results.every(item => item.screen_capture_count > 0)
  };
}

export async function runProtectedMatrix({
  environ = process.env,
  importPlaywright = () => import("playwright")
} = {}) {
  const required = Object.values(ENV);
  const missing = required.filter(name => !environ[name]);
  if (missing.length) return failure("ProtectedMatrixRequiredEnvMissing", { missing_count: missing.length });

  let scenarios;
  try {
    scenarios = parseProtectedScenarios(environ[ENV.scenarios]);
  } catch (error) {
    return failure(safeCode(error));
  }
  const { actionTimeout, semanticSubmitTimeout, resultTimeout } =
    myBeeM1RuntimeTimeouts(environ);
  const responses = [];
  const contexts = [];
  let browser;
  let requester;
  let stage = "launch";
  let currentScenario = null;
  try {
    const playwright = await importPlaywright();
    browser = await launchBrowser(playwright, environ);
    requester = await newAuthenticatedPage(
      browser,
      contexts,
      responses,
      environ,
      environ[ENV.requesterEmployeeId],
      environ[ENV.requesterPassword],
      actionTimeout
    );
    const business = await newAuthenticatedPage(
      browser,
      contexts,
      responses,
      environ,
      environ[ENV.businessEmployeeId],
      environ[ENV.businessPassword],
      actionTimeout
    );
    const accounting = await newAuthenticatedPage(
      browser,
      contexts,
      responses,
      environ,
      environ[ENV.accountingEmployeeId],
      environ[ENV.accountingPassword],
      actionTimeout
    );

    const results = [];
    for (const scenario of scenarios) {
      currentScenario = scenario.scenarioId;
      stage = `${currentScenario}-execute`;
      results.push(await executeScenario({
        scenario,
        requester,
        business,
        accounting,
        environ,
        actionTimeout,
        semanticSubmitTimeout,
        resultTimeout
      }));
    }
    const checks = protectedMatrixChecks(results);
    await logout(requester, actionTimeout);
    const evidence = {
      smoke_schema_version: W80_CA00G7_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      scenario_count: results.length,
      scenarios: results,
      checks,
      observations: { authenticated_http_response_count: responses.length },
      raw_prompt_included: false,
      private_payload_included: false
    };
    assertRedacted(evidence, environ, scenarios);
    return evidence;
  } catch (error) {
    let failurePageText = "";
    let failureScreenshotWritten = false;
    if (requester) {
      try {
        failurePageText = await requester.locator("body").innerText();
        const failureScreenshot = path.join(
          environ[ENV.screenshotDir],
          "protected-matrix-failure.png"
        );
        await requester.screenshot({ path: failureScreenshot, fullPage: true });
        fs.chmodSync(failureScreenshot, 0o600);
        failureScreenshotWritten = true;
      } catch {
        failurePageText = "failure page unavailable";
      }
    }
    const failureLogWritten = writeRestrictedFailureLog(
      error,
      environ,
      scenarios,
      failurePageText
    );
    const evidence = failure(safeCode(error), {
      stage,
      scenario_id: currentScenario,
      failure_log_written: failureLogWritten,
      failure_screenshot_written: failureScreenshotWritten,
      recent_api_responses: responses.slice(-10)
    });
    assertRedacted(evidence, environ, scenarios);
    return evidence;
  } finally {
    for (const context of contexts.reverse()) await context.close();
    if (browser) await browser.close();
  }
}

function writeRestrictedFailureLog(error, environ, scenarios, pageText = "") {
  try {
    const directory = environ[ENV.screenshotDir];
    if (!directory) return false;
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    fs.chmodSync(directory, 0o700);
    let detail = `${String(error?.stack || error?.message || error)}\n\nPAGE\n${pageText}`;
    for (const name of [
      ENV.requesterPassword,
      ENV.businessPassword,
      ENV.accountingPassword
    ]) {
      const value = environ[name];
      if (value) detail = detail.replaceAll(value, "[REDACTED]");
    }
    for (const scenario of scenarios) {
      if (scenario.prompt) detail = detail.replaceAll(scenario.prompt, "[PROMPT]");
    }
    const target = path.join(directory, "protected-matrix-failure.log");
    fs.writeFileSync(target, `${detail}\n`, { encoding: "utf8", mode: 0o600 });
    fs.chmodSync(target, 0o600);
    return true;
  } catch {
    return false;
  }
}

async function executeScenario({
  scenario,
  requester,
  business,
  accounting,
  environ,
  actionTimeout,
  semanticSubmitTimeout,
  resultTimeout
}) {
  const captures = screenCapture(environ[ENV.screenshotDir], `w80-ca00g7-${scenario.scenarioId}`);
  const knownProposals = new Set((await proposalItems(requester)).map(item => item.proposal_id));
  const knownVouchers = new Set((await voucherItems(requester)).map(item => item.candidate_id));
  await gotoRoute(requester, environ[ENV.webUrl], "/workspace", actionTimeout);
  const admitted = await submitPrompt(requester, scenario.prompt, semanticSubmitTimeout, {
    observeWorkspace: true
  });
  if (admitted.status !== 202 || !admitted.payload?.interaction_id) {
    throw new Error("ProtectedMatrixAdmissionFailed");
  }
  const interactionId = admitted.payload.interaction_id;
  const proposal = await waitForNewItem(
    requester,
    proposalItems,
    knownProposals,
    resultTimeout,
    "proposal_id",
    "ProposalDraftTimeout"
  );
  const proposalReview = await reviewAndSubmitProposal({
    page: requester,
    webUrl: environ[ENV.webUrl],
    proposal,
    scenario,
    businessSubjectId: environ[ENV.businessSubjectId],
    captures,
    actionTimeout
  });

  const decisionReplayStatuses = [proposalReview.replay_status];
  const businessDecisions = [];
  const rejectAt = scenario.outcome === "MIDDLE_REJECTION"
    ? 2
    : scenario.outcome === "FINAL_REJECTION" ? 3 : null;
  for (let stageOrder = 1; stageOrder <= scenario.expectedStages; stageOrder += 1) {
    const decision = rejectAt === stageOrder ? "REJECT" : "APPROVE";
    const decided = await decideNextGate({
      page: business,
      role: "BUSINESS_APPROVER",
      decision,
      captures,
      actionTimeout,
      interactionId,
      label: `business-${stageOrder}`,
      expectedDomain: "BUSINESS_FORMAL"
    });
    businessDecisions.push(decided);
    decisionReplayStatuses.push(decided.replay_status);
    if (decision === "REJECT") break;
  }

  if (rejectAt !== null) {
    const rejected = await waitForProposalState(
      requester,
      proposal.proposal_id,
      "REJECTED",
      resultTimeout
    );
    const afterVouchers = await voucherItems(requester);
    await gotoRoute(requester, environ[ENV.webUrl], "/proposals", actionTimeout);
    await captures.capture(requester, "business-rejected", {
      expectedState: "BUSINESS_PROPOSAL_REJECTED",
      assertion: "rejected-proposal-visible",
      interactionId
    });
    return publicScenario({
      scenario,
      interactionId,
      businessDecisions,
      decisionReplayStatuses,
      captures,
      approvedEnvelopePresent: false,
      voucherCreated: afterVouchers.some(item => !knownVouchers.has(item.candidate_id)),
      rejectedStage: rejectAt,
      proposalRevision: rejected.current_revision_no,
      terminalStatus: "REJECTED",
      correctionCycle: 0
    });
  }

  const approved = await waitForProposalState(
    requester,
    proposal.proposal_id,
    "APPROVED",
    resultTimeout
  );
  const voucher = await waitForNewItem(
    requester,
    voucherItems,
    knownVouchers,
    resultTimeout,
    "candidate_id",
    "VoucherDraftTimeout"
  );
  if (scenario.outcome === "ENVELOPE_ONLY") {
    await gotoRoute(requester, environ[ENV.webUrl], "/proposals", actionTimeout);
    await captures.capture(requester, "business-approved", {
      expectedState: "BUSINESS_PROPOSAL_APPROVED",
      assertion: "approved-envelope-visible",
      interactionId
    });
    return publicScenario({
      scenario,
      interactionId,
      businessDecisions,
      decisionReplayStatuses,
      captures,
      approvedEnvelopePresent: Boolean(approved.approved_envelope_id),
      voucherCreated: true,
      rejectedStage: null,
      proposalRevision: approved.current_revision_no,
      terminalStatus: "WAITING_VOUCHER_REVIEW",
      correctionCycle: 0
    });
  }

  const voucherReview = await reviewAndSubmitVoucher({
    page: requester,
    webUrl: environ[ENV.webUrl],
    voucher,
    scenario,
    captures,
    actionTimeout
  });
  decisionReplayStatuses.push(voucherReview.replay_status);
  let correctionCycle = 0;
  if (scenario.outcome === "ACCOUNTING_CORRECTION") {
    const rejected = await decideNextGate({
      page: accounting,
      role: "ACCOUNTING_APPROVER",
      decision: "REJECT",
      captures,
      actionTimeout,
      interactionId,
      label: "accounting-return",
      expectedDomain: "BUSINESS_FORMAL"
    });
    decisionReplayStatuses.push(rejected.replay_status);
    const returned = await waitForVoucherState(
      requester,
      voucher.candidate_id,
      "RETURNED_FOR_CORRECTION",
      resultTimeout
    );
    const correction = await reviewAndSubmitVoucher({
      page: requester,
      webUrl: environ[ENV.webUrl],
      voucher: returned,
      scenario,
      captures,
      actionTimeout,
      correction: true
    });
    decisionReplayStatuses.push(correction.replay_status);
    correctionCycle = 1;
  }

  const accountingFormal = await decideNextGate({
    page: accounting,
    role: "ACCOUNTING_APPROVER",
    decision: "APPROVE",
    captures,
    actionTimeout,
    interactionId,
    label: "accounting-formal",
    expectedDomain: "BUSINESS_FORMAL"
  });
  decisionReplayStatuses.push(accountingFormal.replay_status);
  const writeApproval = await decideNextGate({
    page: accounting,
    role: "ACCOUNTING_APPROVER",
    decision: "APPROVE",
    captures,
    actionTimeout,
    interactionId,
    label: "nsl-write",
    expectedDomain: "NSL_WRITE"
  });
  decisionReplayStatuses.push(writeApproval.replay_status);
  const result = await waitForTerminalResult(requester, interactionId, resultTimeout);
  await gotoRoute(requester, environ[ENV.webUrl], `/workspace?interaction_id=${encodeURIComponent(interactionId)}`, actionTimeout);
  await captures.capture(requester, "terminal-result", {
    expectedState: "RESULT_RENDERED",
    assertion: "journal-result-visible",
    interactionId
  });
  return publicScenario({
    scenario,
    interactionId,
    businessDecisions,
    decisionReplayStatuses,
    captures,
    approvedEnvelopePresent: Boolean(approved.approved_envelope_id),
    voucherCreated: true,
    rejectedStage: null,
    proposalRevision: approved.current_revision_no,
    terminalStatus: result.result?.status || "UNKNOWN",
    correctionCycle
  });
}

async function reviewAndSubmitProposal({
  page,
  webUrl,
  proposal,
  scenario,
  businessSubjectId,
  captures,
  actionTimeout
}) {
  await gotoRoute(page, webUrl, "/proposals", actionTimeout);
  const list = page.getByLabel("품의서 목록");
  await list.getByRole("button").filter({ hasText: proposal.current_revision.title }).click();
  const justification = page.getByLabel(/^업무 필요성/);
  await justification.fill(`${await justification.inputValue()} · ${scenario.scenarioId}`);
  const saveRequest = await clickAndCaptureRequest(
    page,
    () => page.getByRole("button", { name: "revision 저장", exact: true }).click(),
    request => request.method() === "PATCH" && new URL(request.url()).pathname.includes("/business-proposals/")
  );
  await page.getByText("새 revision으로 저장했습니다.", { exact: true }).waitFor({ timeout: actionTimeout });
  await page.getByRole("button", { name: "결재선 미리보기", exact: true }).click();
  await page.getByRole("heading", { name: "결재선", exact: true }).waitFor({ timeout: actionTimeout });
  const selects = page.getByRole("combobox", { name: /단계/ });
  if (await selects.count() !== scenario.expectedStages) throw new Error("ApprovalStageCountMismatch");
  for (let index = 0; index < scenario.expectedStages; index += 1) {
    await selects.nth(index).selectOption(businessSubjectId);
  }
  await page.getByRole("button", { name: "상신", exact: true }).click();
  const submitRequest = await clickAndCaptureRequest(
    page,
    () => page.getByRole("button", { name: "상신 확인", exact: true }).click(),
    request => request.method() === "POST" && new URL(request.url()).pathname.endsWith(":submit")
  );
  await page.getByText("품의서를 상신했습니다.", { exact: true }).waitFor({ timeout: actionTimeout });
  const replay = await browserJson(page, submitRequest.route, {
    method: "POST",
    body: submitRequest.payload
  });
  const stale = await browserJson(page, saveRequest.route, {
    method: "PATCH",
    body: saveRequest.payload
  });
  if (stale.status !== 409) throw new Error("ProposalStaleRevisionAccepted");
  await captures.capture(page, "proposal-submitted", {
    expectedState: "PROPOSAL_SUBMITTED",
    assertion: "reviewed-proposal-and-line-visible"
  });
  return { replay_status: replay.status };
}

async function reviewAndSubmitVoucher({
  page,
  webUrl,
  voucher,
  scenario,
  captures,
  actionTimeout,
  correction = false
}) {
  await gotoRoute(page, webUrl, "/vouchers", actionTimeout);
  const list = page.getByLabel("전표 초안 목록");
  const buttons = list.getByRole("button");
  let candidateButton = null;
  const candidateDeadline = Date.now() + actionTimeout;
  while (!candidateButton && Date.now() < candidateDeadline) {
    for (let index = 0; index < await buttons.count(); index += 1) {
      const button = buttons.nth(index);
      if (await button.getAttribute("data-candidate-id") === voucher.candidate_id) {
        candidateButton = button;
        break;
      }
    }
    if (!candidateButton) await page.waitForTimeout(250);
  }
  if (!candidateButton) throw new Error("VoucherCandidateListItemMissing");
  await candidateButton.click();
  const description = page.getByLabel(/^1번 적요/);
  await description.fill(`${await description.inputValue()} · ${scenario.scenarioId}${correction ? " · correction" : ""}`);
  const saveRequest = await clickAndCaptureRequest(
    page,
    () => page.getByRole("button", { name: "revision 저장", exact: true }).click(),
    request => request.method() === "PATCH" && new URL(request.url()).pathname.includes("/business-voucher-drafts/")
  );
  await page.getByText("새 revision으로 저장했습니다.", { exact: true }).waitFor({ timeout: actionTimeout });
  await page.getByRole("button", { name: "검증", exact: true }).click();
  await page.getByText("현재 revision 검증을 통과했습니다.", { exact: true }).waitFor({ timeout: actionTimeout });
  await page.getByRole("button", { name: "회계 상신", exact: true }).click();
  const submitRequest = await clickAndCaptureRequest(
    page,
    () => page.getByRole("button", { name: "상신 확인", exact: true }).click(),
    request => request.method() === "POST" && new URL(request.url()).pathname.endsWith(":submit-for-accounting")
  );
  await page.getByText("회계 검토를 요청했습니다.", { exact: true }).waitFor({ timeout: actionTimeout });
  const replay = await browserJson(page, submitRequest.route, {
    method: "POST",
    body: submitRequest.payload
  });
  const stale = await browserJson(page, saveRequest.route, {
    method: "PATCH",
    body: saveRequest.payload
  });
  if (stale.status !== 409) throw new Error("VoucherStaleRevisionAccepted");
  await captures.capture(page, correction ? "voucher-correction-submitted" : "voucher-submitted", {
    expectedState: correction ? "VOUCHER_CORRECTION_SUBMITTED" : "VOUCHER_SUBMITTED",
    assertion: "reviewed-voucher-visible"
  });
  return { replay_status: replay.status };
}

async function decideNextGate({
  page,
  role,
  decision,
  captures,
  actionTimeout,
  interactionId,
  label,
  expectedDomain
}) {
  const deadline = Date.now() + actionTimeout * 6;
  let found = null;
  while (Date.now() < deadline && !found) {
    const pending = await pendingApprovalGates([{ role, page }]);
    if (pending.length > 1) throw new Error("ApprovalGateAmbiguous");
    found = pending[0] || null;
    if (!found) await page.waitForTimeout(500);
  }
  if (!found) throw new Error("ApprovalGateTimeout");
  if (found.gate.approval_domain !== expectedDomain) {
    throw new Error("ApprovalDomainMismatch");
  }
  let observed = null;
  const observer = request => {
    const route = new URL(request.url()).pathname;
    if (request.method() === "POST" && route.endsWith("/decisions")) {
      observed = { route, payload: request.postDataJSON() };
    }
  };
  page.on("request", observer);
  try {
    await prepareApprovalInbox(page, actionTimeout);
    const gateButton = page.getByLabel("대기 중인 승인 요청")
      .getByRole("button").filter({ hasText: found.gate.title });
    await gateButton.waitFor({ timeout: actionTimeout });
    await gateButton.click();
    await page.getByRole("heading", { name: found.gate.title, exact: true }).waitFor({ timeout: actionTimeout });
    if (decision === "REJECT") {
      await page.getByLabel(/^반려 사유/).fill(`Protected acceptance ${label}`);
      await page.getByRole("button", { name: "반려", exact: true }).click();
      await page.getByRole("button", { name: "반려 확정", exact: true }).click();
    } else {
      await page.getByRole("button", { name: "승인", exact: true }).click();
      await page.getByRole("button", { name: "승인 확정", exact: true }).click();
    }
    await page.getByRole("heading", { name: "결정이 기록되었습니다", exact: true }).waitFor({ timeout: actionTimeout });
    if (!observed) throw new Error("ApprovalDecisionRequestMissing");
    const replay = await browserJson(page, observed.route, {
      method: "POST",
      body: observed.payload
    });
    await captures.capture(page, label, {
      expectedState: decision === "REJECT" ? "APPROVAL_REJECTED" : "APPROVAL_RECORDED",
      assertion: "decision-recorded-heading-visible",
      interactionId,
      approvalDomain: found.gate.approval_domain
    });
    return {
      gate_id: found.gate.gate_id,
      approval_domain: found.gate.approval_domain,
      decision,
      replay_status: replay.status
    };
  } finally {
    page.off("request", observer);
  }
}

async function clickAndCaptureRequest(page, action, predicate) {
  const requestPromise = page.waitForRequest(predicate);
  await action();
  const request = await requestPromise;
  return {
    route: new URL(request.url()).pathname,
    payload: request.postDataJSON()
  };
}

async function proposalItems(page) {
  const response = await browserJson(page, "/ae-api/api/v1/business-proposals");
  if (response.status !== 200 || !Array.isArray(response.payload?.items)) {
    throw new Error("ProposalListUnavailable");
  }
  return response.payload.items;
}

async function voucherItems(page) {
  const response = await browserJson(page, "/ae-api/api/v1/business-voucher-drafts");
  if (response.status !== 200 || !Array.isArray(response.payload?.items)) {
    throw new Error("VoucherListUnavailable");
  }
  return response.payload.items;
}

async function waitForNewItem(page, loader, known, timeout, idField, failureCode) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const values = await loader(page);
      const found = values.find(item => !known.has(item[idField]));
      if (found) return found;
    } catch (error) {
      if (!isTransientBrowserFetch(error)) throw error;
    }
    await page.waitForTimeout(750);
  }
  throw new Error(failureCode);
}

async function waitForProposalState(page, proposalId, state, timeout) {
  return waitForState(page, `/ae-api/api/v1/business-proposals/${encodeURIComponent(proposalId)}`, state, timeout);
}

async function waitForVoucherState(page, candidateId, state, timeout) {
  return waitForState(page, `/ae-api/api/v1/business-voucher-drafts/${encodeURIComponent(candidateId)}`, state, timeout);
}

async function waitForState(page, route, state, timeout) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const response = await browserJson(page, route);
      if (response.status === 200 && response.payload?.state === state) return response.payload;
    } catch (error) {
      if (!isTransientBrowserFetch(error)) throw error;
    }
    await page.waitForTimeout(750);
  }
  throw new Error(`${state}StateTimeout`);
}

async function waitForTerminalResult(page, interactionId, timeout) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const result = await readResult(page, interactionId);
      if (result?.terminal === true) return result;
    } catch (error) {
      if (!isTransientBrowserFetch(error)) throw error;
    }
    await page.waitForTimeout(750);
  }
  throw new Error("ProtectedMatrixResultTimeout");
}

export function isTransientBrowserFetch(error) {
  return String(error?.message || error).includes("Failed to fetch");
}

async function gotoRoute(page, webUrl, route, timeout) {
  const target = new URL(route, webUrl).toString();
  await page.goto(target, {
    waitUntil: "domcontentloaded",
    timeout
  });
  const authenticated = await page.getByRole("button", { name: "로그아웃", exact: true })
    .waitFor({ state: "visible", timeout: Math.min(timeout, 5000) })
    .then(() => true)
    .catch(() => false);
  if (authenticated) return;
  const loginHeading = page.getByRole("heading", { name: "사번 로그인", exact: true });
  if (await loginHeading.isVisible().catch(() => false)) {
    const credentials = pageCredentials.get(page);
    if (!credentials) throw new Error("ProtectedMatrixReauthenticationUnavailable");
    await login(page, { ...credentials, timeout });
    await page.goto(target, { waitUntil: "domcontentloaded", timeout });
    const restored = await page.getByRole("button", { name: "로그아웃", exact: true })
      .waitFor({ state: "visible", timeout: Math.min(timeout, 5000) })
      .then(() => true)
      .catch(() => false);
    if (!restored) {
      throw new Error("ProtectedMatrixReauthenticationFailed");
    }
  }
}

async function newAuthenticatedPage(browser, contexts, responses, environ, employeeId, password, timeout) {
  const context = await browser.newContext(contextOptions());
  contexts.push(context);
  const page = await configuredPage(context);
  observeResponses(page, responses);
  await page.goto(environ[ENV.webUrl], { waitUntil: "domcontentloaded", timeout });
  await login(page, {
    tenantId: environ[ENV.tenantId],
    employeeId,
    password,
    timeout
  });
  pageCredentials.set(page, {
    tenantId: environ[ENV.tenantId],
    employeeId,
    password
  });
  return page;
}

function publicScenario({
  scenario,
  interactionId,
  businessDecisions,
  decisionReplayStatuses,
  captures,
  approvedEnvelopePresent,
  voucherCreated,
  rejectedStage,
  proposalRevision,
  terminalStatus,
  correctionCycle
}) {
  return {
    scenario_id: scenario.scenarioId,
    outcome: scenario.outcome,
    interaction_id: interactionId,
    business_stage_count: businessDecisions.length,
    business_decisions: businessDecisions.map(item => ({
      approval_domain: item.approval_domain,
      decision: item.decision
    })),
    decision_replay_statuses: decisionReplayStatuses,
    approved_envelope_present: approvedEnvelopePresent,
    voucher_created: voucherCreated,
    rejected_stage: rejectedStage,
    proposal_revision: proposalRevision,
    terminal_status: terminalStatus,
    correction_cycle: correctionCycle,
    screen_capture_count: captures.evidence().count,
    screen_capture: captures.evidence()
  };
}

function failure(code, observations = {}) {
  return {
    smoke_schema_version: W80_CA00G7_SCHEMA_VERSION,
    status: "FAIL",
    failure_code: code,
    observations,
    checks: {}
  };
}

function safeCode(error) {
  const value = String(error?.message || "ProtectedMatrixFailed");
  return /^[A-Za-z][A-Za-z0-9_.-]{0,95}$/.test(value)
    ? value
    : "ProtectedMatrixFailed";
}

function assertRedacted(evidence, environ, scenarios = []) {
  const serialized = JSON.stringify(evidence);
  for (const name of [
    ENV.requesterPassword,
    ENV.businessPassword,
    ENV.accountingPassword
  ]) {
    const value = environ[name];
    if (value && serialized.includes(value)) throw new Error("ProtectedMatrixSecretLeak");
  }
  for (const scenario of scenarios) {
    if (scenario.prompt && serialized.includes(scenario.prompt)) {
      throw new Error("ProtectedMatrixPromptLeak");
    }
  }
}

export async function main(output = console.log) {
  const evidence = await runProtectedMatrix();
  output(JSON.stringify(evidence));
  return evidence.status === "PASS" ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
