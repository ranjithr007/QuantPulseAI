import assert from "node:assert/strict";
import test from "node:test";
import { cacheHistoryPage, cachedHistoryPage, paginationPageNumbers, validatedHistoryPage, visibleHistoryPage } from "./paperHistory.js";

const response = { records: [{ id: 1 }], page: 1, page_size: 10, total_count: 20 };
test("different page or ledger revision never reuses old page rows", () => {
  const snapshot = validatedHistoryPage(response, 1, "1:20", 1000);
  assert.equal(visibleHistoryPage(snapshot, 2, "1:20"), null);
  assert.equal(visibleHistoryPage(snapshot, 1, "2:21"), null);
  assert.equal(visibleHistoryPage(snapshot, 1, "1:20", "timeout"), null);
  assert.deepEqual(visibleHistoryPage(snapshot, 1, "1:20").records, [{ id: 1 }]);
});
test("malformed, unavailable and mismatched pages fail closed", () => {
  for (const data of [null, { status: "UNAVAILABLE", records: [] }, { ...response, page: 2 }, { ...response, page_size: 200 }, { ...response, total_count: null }, { ...response, records: Array(11).fill({}) }]) {
    assert.throws(() => validatedHistoryPage(data, 1, "1:20"));
  }
});
test("same-page cache expires, invalidates on closure revision and remains bounded", () => {
  const cache = new Map();
  const snapshot = validatedHistoryPage(response, 1, "1:20", 1000);
  cacheHistoryPage(cache, snapshot);
  assert.equal(cachedHistoryPage(cache, 1, "1:20", 2000), snapshot);
  assert.equal(cachedHistoryPage(cache, 1, "1:20", 31000), null);
  assert.equal(cachedHistoryPage(cache, 1, "2:21", 2000), null);
  for (let page = 2; page <= 6; page++) cacheHistoryPage(cache, { ...snapshot, page });
  assert.equal(cache.size, 5);
  assert.equal(cache.has(1), false);
});
test("pagination stays bounded at both edges", () => {
  assert.deepEqual(paginationPageNumbers(1, 2), [1, 2]);
  assert.deepEqual(paginationPageNumbers(100, 100), [96, 97, 98, 99, 100]);
});
