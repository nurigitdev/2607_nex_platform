import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { readFile } from "node:fs/promises";

import {
  AE_PROJECT_MEMBERSHIP_BATCH_RESULT_SCHEMA_VERSION,
  ProjectMembershipBatchResultError,
  buildProjectMembershipBatchResultSurface,
  renderProjectMembershipBatchResult
} from "../src/projectMembershipBatchResult.js";

function projection(overrides = {}) {
  return {
    schema_version: AE_PROJECT_MEMBERSHIP_BATCH_RESULT_SCHEMA_VERSION,
    operation_id: "PROJECT.MEMBERSHIP.ADD_MANY",
    payload_hash: `sha256:${"a".repeat(64)}`,
    project_id: "project-demo",
    member_role: "MEMBER",
    overall_status: "PARTIALLY_APPLIED",
    business_result_ref: "eos.project-membership-batch:demo",
    summary: {
      requested_count: 3,
      admitted_count: 2,
      applied_count: 2,
      pre_admission_rejected_count: 1,
      commit_rejected_count: 0,
      total_rejected_count: 1
    },
    items: [
      {
        stage: "OA_RESOLUTION",
        input_index: 1,
        subject_id: null,
        normalized_employee_id: "emp-0002",
        outcome: "NAME_MISMATCH",
        applied: false
      },
      {
        stage: "EOS_COMMIT",
        input_index: null,
        subject_id: "subject-a",
        normalized_employee_id: null,
        outcome: "ADDED",
        applied: true
      },
      {
        stage: "EOS_COMMIT",
        input_index: null,
        subject_id: "subject-b",
        normalized_employee_id: null,
        outcome: "ALREADY_ACTIVE",
        applied: true
      }
    ],
    metadata: {
      model_authority: false,
      raw_prompt_included: false,
      credentials_included: false,
      provider_configuration_included: false
    },
    result_hash: `sha256:${"b".repeat(64)}`,
    ...overrides
  };
}

describe("AE Web Project membership batch result", () => {
  it("builds a safe Korean result surface with mixed outcomes", () => {
    const surface = buildProjectMembershipBatchResultSurface(projection());
    const html = renderProjectMembershipBatchResult(surface);

    assert.equal(surface.requestedCount, 3);
    assert.equal(surface.appliedCount, 2);
    assert.equal(surface.rejectedCount, 1);
    assert.equal(surface.items[0].outcomeLabel, "사번과 이름 불일치");
    assert.match(html, /프로젝트 멤버 처리 결과/);
    assert.match(html, /반영/);
    assert.match(html, /emp-0002/);
    assert.doesNotMatch(
      html,
      /api_key|service_token|database_url|provider_endpoint|raw_prompt|password/
    );
  });

  it("escapes projected identities and never renders markup", () => {
    const changed = projection();
    changed.items[1].subject_id = '<script>alert("x")</script>';
    const html = renderProjectMembershipBatchResult(
      buildProjectMembershipBatchResultSurface(changed)
    );
    assert.doesNotMatch(html, /<script>/);
    assert.match(html, /&lt;script&gt;/);
  });

  it("rejects schema drift, count drift, outcomes, and private keys", () => {
    const cases = [
      projection({ schema_version: "wrong" }),
      projection({ operation_id: "PROJECT.MEMBERSHIP.ADD" }),
      projection({ summary: { ...projection().summary, requested_count: 4 } }),
      projection({
        items: [{ ...projection().items[0], outcome: "UNKNOWN" }],
        summary: {
          ...projection().summary,
          requested_count: 1,
          applied_count: 0,
          total_rejected_count: 1
        }
      }),
      projection({ service_token: "private" })
    ];
    for (const value of cases) {
      assert.throws(
        () => buildProjectMembershipBatchResultSurface(value),
        ProjectMembershipBatchResultError
      );
    }
  });

  it("is wired into the authenticated Chat message renderer", async () => {
    const mainSource = await readFile(new URL("../src/main.js", import.meta.url), "utf8");
    assert.match(mainSource, /renderProjectMembershipBatchResult/);
    assert.match(mainSource, /message\.projectMembershipBatchResult/);
  });
});
