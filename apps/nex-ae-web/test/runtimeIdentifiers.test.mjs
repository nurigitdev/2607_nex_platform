import test from "node:test";
import assert from "node:assert/strict";

import {
  RuntimeIdentifierError,
  createInteractionId
} from "../src/runtimeIdentifiers.js";

test("creates the UUID supplied by the secure browser runtime", () => {
  const expected = "fdb048ff-6620-48fc-8753-4f465d19c463";
  assert.equal(
    createInteractionId({ cryptoRef: { randomUUID: () => expected } }),
    expected
  );
});

test("fails closed when secure UUID generation is unavailable", () => {
  assert.throws(
    () => createInteractionId({ cryptoRef: {} }),
    error => error instanceof RuntimeIdentifierError &&
      error.status === "RUNTIME_IDENTIFIER_UNAVAILABLE"
  );
});
