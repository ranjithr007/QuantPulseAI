export const PAPER_HISTORY_PAGE_SIZE = 10;
export const PAPER_HISTORY_CACHE_MS = 30000;

export function validatedHistoryPage(response, page, revision, now = Date.now()) {
  if (!response || response.status === "UNAVAILABLE" || !Array.isArray(response.records)) {
    throw new Error(response?.detail || "Trade history is unavailable; no page was loaded.");
  }
  if (Number(response.page) !== page || Number(response.page_size) !== PAPER_HISTORY_PAGE_SIZE
    || !Number.isInteger(response.total_count) || response.total_count < 0
    || response.records.length > PAPER_HISTORY_PAGE_SIZE) {
    throw new Error("Trade history returned an unverified page. Please retry.");
  }
  return { page, revision, records: response.records, total: response.total_count, loadedAt: now };
}

export function visibleHistoryPage(snapshot, page, revision, error = "") {
  return !error && snapshot?.page === page && snapshot.revision === revision ? snapshot : null;
}

export function cachedHistoryPage(cache, page, revision, now = Date.now()) {
  const snapshot = visibleHistoryPage(cache.get(page), page, revision);
  return snapshot && now - snapshot.loadedAt < PAPER_HISTORY_CACHE_MS ? snapshot : null;
}

export function cacheHistoryPage(cache, snapshot) {
  cache.delete(snapshot.page);
  cache.set(snapshot.page, snapshot);
  while (cache.size > 5) cache.delete(cache.keys().next().value);
}

export function paginationPageNumbers(currentPage, totalPages) {
  const firstPage = Math.max(1, Math.min(currentPage - 2, totalPages - 4));
  const lastPage = Math.min(totalPages, firstPage + 4);
  return Array.from({ length: lastPage - firstPage + 1 }, (_, index) => firstPage + index);
}
