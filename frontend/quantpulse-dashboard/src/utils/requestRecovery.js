// Only retry transient reads/idempotent job submissions, never trade mutations.
export function retryDelay(error, failures = 1) {
  if (error?.name === "AbortError") return null;
  const status = Number(error?.status);
  if (status >= 400 && status < 500 && ![408, 429].includes(status)) return null;
  return [5000, 15000, 30000, 60000][Math.min(3, Math.max(0, failures - 1))];
}

export function requestFailureMessage(error, label) {
  if (error?.status === 401) return `${label}: session expired. Please sign in again.`;
  if (error?.status === 403) return `${label}: access denied.`;
  if (error?.code === "REQUEST_TIMEOUT") return `${label}: the server did not respond within ${error.timeoutSeconds} seconds.`;
  if (error?.status) return `${label}: server returned HTTP ${error.status}.`;
  return `${label}: the request could not be completed. Check connectivity or server availability.`;
}
