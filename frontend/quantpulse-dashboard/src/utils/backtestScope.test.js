import test from "node:test";
import assert from "node:assert/strict";
import { savedBacktestSide } from "./backtestScope.js";

test("WAIT can select latest saved directional scope without inventing direction", () => {
  const records = [
    { scope: { symbol: "SOLUSDT", timeframe: "1h", signal: "LONG" }, saved_at: "2026-09-01" },
    { scope: { symbol: "SOLUSDT", timeframe: "1h", signal: "SHORT" }, saved_at: "2026-09-02" },
    { scope: { symbol: "ETHUSDT", timeframe: "1h", signal: "LONG" }, saved_at: "2026-09-03" },
    { scope: { symbol: "SOLUSDT", timeframe: "4h", signal: "LONG" }, saved_at: "2026-09-04" },
  ];
  assert.equal(savedBacktestSide(records, "SOLUSDT", "1h"), "SHORT");
  assert.equal(records[0].scope.signal, "LONG");
  assert.equal(savedBacktestSide(records, "BTCUSDT", "1h"), null);
  assert.equal(savedBacktestSide([], "SOLUSDT", "1h"), null);
});
