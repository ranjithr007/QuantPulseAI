import assert from "node:assert/strict";
import test from "node:test";
import { notificationHref } from "./notificationLinks.js";

const view = { symbol: "ETHUSDT", timeframe: "2h", mode: "intraday" };
const getPageHref = (page, selectedView) => ({ page, view: selectedView });

test("learning notifications open Strategies with the current view", () => {
  assert.deepEqual(notificationHref({ category: "STRATEGY" }, getPageHref, view), {
    page: "strategies", view,
  });
});

test("strategy destination takes precedence over a coin symbol", () => {
  assert.equal(notificationHref({ category: "STRATEGY", symbol: "BTCUSDT" }, getPageHref, view).page, "strategies");
});

test("paper trade notifications retain coin detail navigation", () => {
  assert.deepEqual(notificationHref({ category: "PAPER_TRADE", symbol: "BTCUSDT" }, getPageHref, view), {
    page: "coin-details", view: { ...view, symbol: "BTCUSDT" },
  });
  assert.equal(view.symbol, "ETHUSDT");
});

test("system and missing notifications do not fabricate a destination", () => {
  assert.equal(notificationHref({ category: "SYSTEM" }, getPageHref, view), null);
  assert.equal(notificationHref(null, getPageHref, view), null);
});
