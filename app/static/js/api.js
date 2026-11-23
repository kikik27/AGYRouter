/**
 * API helper with cookie credentials + persistent localStorage X-Admin-Token fallback.
 */
const TOKEN_STORAGE_KEY = "agy_admin_token";
let onUnauthorizedCallback = null;

export function setOnUnauthorized(cb) {
    onUnauthorizedCallback = cb;
}

export function getSessionToken() {
    try {
        return localStorage.getItem(TOKEN_STORAGE_KEY) || "";
    } catch {
        return "";
    }
}

export function setSessionToken(token) {
    try {
        if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
    } catch {}
}

export function clearSessionToken() {
    try {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
    } catch {}
}

export async function apiFetch(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    const savedToken = getSessionToken();
    if (savedToken && !headers["X-Admin-Token"]) {
        headers["X-Admin-Token"] = savedToken;
    }

    if (options.body && typeof options.body === "object" && !(options.body instanceof FormData)) {
        headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(options.body);
    }

    const res = await fetch(path, {
        ...options,
        headers,
        credentials: "include",
    });

    if (res.status === 401 && !path.startsWith("/api/auth/")) {
        clearSessionToken();
        if (onUnauthorizedCallback) {
            onUnauthorizedCallback();
        }
        throw new Error("Sesi berakhir. Silakan login kembali.");
    }

    const text = await res.text();
    let data = null;
    try {
        data = text ? JSON.parse(text) : {};
    } catch {
        data = { detail: text };
    }

    if (!res.ok) {
        const msg =
            data?.detail?.error?.message ||
            data?.detail ||
            data?.message ||
            `HTTP ${res.status}`;
        throw new Error(msg);
    }

    return data;
}
