import test from "node:test";
import assert from "node:assert/strict";
import { requestFailureMessage, retryDelay } from "./requestRecovery.js";

test("transient retries are rate bounded; auth, invalid requests and aborts stop", () => {
  for (const status of [408, 429, 500, 502, 503, 504, undefined]) {
    assert.deepEqual([1, 2, 3, 4, 100].map((n) => retryDelay({status}, n)), [5000, 15000, 30000, 60000, 60000]);
  }
  for (const status of [400, 401, 403, 404, 422]) assert.equal(retryDelay({status}), null);
  assert.equal(retryDelay({name: "AbortError"}), null);
});

test("errors expose safe status/timeout details instead of HTML or credentials", () => {
  assert.match(requestFailureMessage({code: "REQUEST_TIMEOUT", timeoutSeconds: 20}, "Replay"), /20 seconds/);
  assert.match(requestFailureMessage({status: 401}, "Replay"), /sign in/);
  assert.match(requestFailureMessage({status: 403}, "Replay"), /access denied/);
  assert.equal(requestFailureMessage({status: 504, message: "<html>private upstream text</html>"}, "Replay"), "Replay: server returned HTTP 504.");
  assert.match(requestFailureMessage(new TypeError("Failed to fetch"), "Replay"), /connectivity/);
});
