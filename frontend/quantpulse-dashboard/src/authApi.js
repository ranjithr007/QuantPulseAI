const API_BASE = import.meta.env.PROD
  ? new URL("/api/", window.location.origin).toString()
  : import.meta.env.VITE_BACKEND_URL || "http://127.0.0.1:8000";

function apiUrl(path) {
  return new URL(String(path).replace(/^\/+/, ""), API_BASE);
}

async function authRequest(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    ...options,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "Authentication failed");
  }
  return payload;
}

export function loadSession() {
  return authRequest("/auth/session");
}

export function login(username, password) {
  return authRequest("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function logout() {
  return authRequest("/auth/logout", { method: "POST" });
}
