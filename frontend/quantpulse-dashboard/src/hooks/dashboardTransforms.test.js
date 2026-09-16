import assert from "node:assert/strict";
import test from "node:test";

import { buildEquityCurve, calculateMaxDrawdown } from "./dashboardTransforms.js";

test("fallback equity curve is chronological and includes the zero baseline", () => {
  const curve = buildEquityCurve([
    { status: "CLOSED", pnl_percent: -2, closed_at: "2026-01-02T00:00:00Z" },
    { status: "CLOSED", pnl_percent: 1, closed_at: "2026-01-01T00:00:00Z" },
  ]);

  assert.deepEqual(curve.map((point) => point.equity), [0, 1, -1]);
  assert.equal(calculateMaxDrawdown(curve), 2);
});
