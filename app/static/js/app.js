import { apiFetch, clearSessionToken, setOnUnauthorized, setSessionToken } from "./api.js";
import { renderModelBreakdown, renderTrafficChart } from "./charts.js";
import { renderMarkdown } from "./markdown.js";

const ACTIVE_VIEW_KEY = "agy_active_view";

const state = {
    authenticated: false,
    isDefaultPassword: true,
    activeView: localStorage.getItem(ACTIVE_VIEW_KEY) || "overview",
    overview: null,
    keys: [],
    routes: [],
    supportedModels: [],
    logs: [],
    settings: null,
    tunnel: null,
    serviceInfo: null,
    revealedKeys: new Set(),
    connectTab: "python",
    connectHostMode: "local",
    connectCustomUrl: "",
    connectSelectedKey: "",
    connectSelectedModel: "gemini-3.8-flash-high",
    playgroundHistory: [],
    playgroundStreaming: false,
    playgroundAbort: null,
    logsAutoRefresh: false,
    logsTimer: null,
};

// --- DOM Helpers ---
const $ = (id) => document.getElementById(id);

function escapeHtml(str) {
    return String(str ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function formatTime(ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleString("id-ID", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
    });
}

function formatNumber(n) {
    return Number(n || 0).toLocaleString("en-US");
}

function showToast(message, type = "ok") {
    const container = $("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3200);
}

async function copyText(text, label = "Disalin ke clipboard") {
    try {
        await navigator.clipboard.writeText(text);
        showToast(label, "ok");
    } catch {
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
        showToast(label, "ok");
    }
}

// --- Modal Manager ---
function openModal(title, bodyHtml, footerHtml) {
    $("modal-title").textContent = title;
    $("modal-body").innerHTML = bodyHtml;
    $("modal-footer").innerHTML = footerHtml || "";
    $("modal-backdrop").classList.remove("hidden");
}

function closeModal() {
    $("modal-backdrop").classList.add("hidden");
}

// --- Auth & Boot ---
async function checkAuthAndBoot() {
    setOnUnauthorized(() => {
        state.authenticated = false;
        stopLogsAutoRefresh();
        showLoginGate();
    });

    try {
        const status = await apiFetch("/api/auth/status");
        state.authenticated = Boolean(status.authenticated);
        state.isDefaultPassword = Boolean(status.is_default_password);
        if (state.authenticated) {
            await enterDashboard();
        } else {
            showLoginGate();
        }
    } catch {
        showLoginGate();
    } finally {
        $("boot-loader").classList.add("hidden");
    }
}

function showLoginGate() {
    $("boot-loader").classList.add("hidden");
    $("login-gate").classList.remove("hidden");
    $("app-shell").classList.add("hidden");
    $("login-password").value = "";
    $("login-error").classList.add("hidden");
    setTimeout(() => $("login-password").focus(), 50);
}

async function enterDashboard() {
    $("boot-loader").classList.add("hidden");
    $("login-gate").classList.add("hidden");
    $("app-shell").classList.remove("hidden");
    updateDefaultPasswordBanner();
    await loadAllCoreData();
    const validViews = ["overview", "keys", "models", "connect", "tunnel", "playground", "logs", "settings"];
    const targetView = validViews.includes(state.activeView) ? state.activeView : "overview";
    switchView(targetView);
}

function updateDefaultPasswordBanner() {
    const banner = $("default-pw-banner");
    if (state.isDefaultPassword) {
        banner.classList.remove("hidden");
    } else {
        banner.classList.add("hidden");
    }
}

async function loadAllCoreData() {
    const [overview, keysRes, routesRes, settingsRes, tunnelRes] = await Promise.all([
        apiFetch("/api/admin/overview"),
        apiFetch("/api/admin/keys"),
        apiFetch("/api/admin/routes"),
        apiFetch("/api/admin/settings"),
        apiFetch("/api/admin/tunnel"),
    ]);

    state.overview = overview;
    state.keys = keysRes.keys || [];
    state.routes = routesRes.routes || [];
    state.supportedModels = routesRes.supported_models || [];
    state.settings = settingsRes;
    state.tunnel = tunnelRes;

    const firstActive = state.keys.find((k) => k.is_active);
    if (!state.connectSelectedKey && firstActive) {
        state.connectSelectedKey = firstActive.key_value;
    }
    if (settingsRes.default_model) {
        state.connectSelectedModel = settingsRes.default_model;
    }

    const dot = $("sidebar-cli-dot");
    const label = $("sidebar-cli-label");
    if (overview.server?.binary_found) {
        dot.classList.remove("warn");
        label.textContent = "CLI Ready";
    } else {
        dot.classList.add("warn");
        label.textContent = "CLI Missing";
    }

    const tunBadge = $("sidebar-tunnel-status");
    if (tunnelRes?.running) {
        tunBadge.textContent = "Tunnel ON";
        tunBadge.style.color = "var(--accent)";
    } else {
        tunBadge.textContent = "Local";
        tunBadge.style.color = "var(--text-dim)";
    }
}

// --- Navigation ---
function switchView(viewName) {
    state.activeView = viewName;
    try {
        localStorage.setItem(ACTIVE_VIEW_KEY, viewName);
    } catch {}

    if (viewName !== "logs") {
        stopLogsAutoRefresh();
    }

    document.querySelectorAll(".nav-item").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.view === viewName);
    });
    document.querySelectorAll(".view-section").forEach((sec) => {
        sec.classList.toggle("hidden", sec.id !== `view-${viewName}`);
    });

    $("sidebar").classList.remove("open");

    if (viewName === "overview") renderOverviewView();
    else if (viewName === "keys") renderKeysView();
    else if (viewName === "models") renderModelsView();
    else if (viewName === "connect") renderConnectView();
    else if (viewName === "tunnel") renderTunnelView();
    else if (viewName === "playground") renderPlaygroundView();
    else if (viewName === "logs") renderLogsView();
    else if (viewName === "settings") renderSettingsView();
}

// --- View 1: Overview ---
async function renderOverviewView() {
    try {
        state.overview = await apiFetch("/api/admin/overview");
    } catch (e) {
        showToast(e.message, "err");
        return;
    }
    const ov = state.overview;
    const srv = ov.server || {};

    const baseUrl = `http://127.0.0.1:${srv.port || 8000}/v1`;
    const activeKey = srv.default_key_value || "Belum ada key aktif";

    $("ov-endpoint-url").textContent = baseUrl;
    $("ov-active-key").textContent = activeKey.length > 20 ? `${activeKey.slice(0, 14)}...${activeKey.slice(-4)}` : activeKey;
    $("ov-copy-url-btn").onclick = () => copyText(baseUrl, "Base URL disalin");
    $("ov-copy-key-btn").onclick = () => {
        if (srv.default_key_value) copyText(srv.default_key_value, "API Key disalin");
    };

    const tunnelPill = $("ov-tunnel-pill");
    if (srv.tunnel_running) {
        tunnelPill.classList.remove("hidden");
        tunnelPill.classList.add("ok");
        tunnelPill.textContent = srv.tunnel_url ? `Tunnel: ${srv.tunnel_url}` : "Tunnel Online";
    } else {
        tunnelPill.classList.add("hidden");
    }

    $("kpi-total-reqs").textContent = formatNumber(ov.total_requests);
    $("kpi-24h-sub").textContent = `${formatNumber(ov.requests_24h)} dalam 24 jam terakhir`;

    $("kpi-total-tokens").textContent = formatNumber(ov.total_tokens);
    $("kpi-tokens-sub").textContent = `${formatNumber(ov.prompt_tokens)} in / ${formatNumber(ov.completion_tokens)} out`;

    $("kpi-success-rate").textContent = `${ov.success_rate}%`;
    $("kpi-latency-sub").textContent = `Rata-rata ${formatNumber(ov.avg_latency_ms)} ms`;

    $("kpi-active-keys").textContent = `${srv.active_keys_count || 0}`;
    $("kpi-keys-sub").textContent = srv.require_api_key ? "Auth API Key: Wajib" : "Auth API Key: Opsional";

    renderTrafficChart($("ov-traffic-chart"), ov.hourly_activity);
    renderModelBreakdown($("ov-model-breakdown"), ov.model_breakdown);

    const tbody = $("ov-recent-logs");
    if (!ov.recent_logs || ov.recent_logs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color: var(--text-dim); padding: 24px;">Belum ada request masuk. Coba uji di Playground atau hubungkan aplikasi via menu Connect.</td></tr>`;
    } else {
        tbody.innerHTML = ov.recent_logs
            .map((log) => {
                const ok = log.status_code < 400;
                return `
                <tr class="clickable" data-log-id="${escapeHtml(log.id)}">
                    <td class="mono" style="font-size:12px; color:var(--text-muted);">${escapeHtml(formatTime(log.timestamp))}</td>
                    <td>${escapeHtml(log.api_key_name || "—")}</td>
                    <td class="mono">${escapeHtml(log.resolved_model || "—")}</td>
                    <td><span class="pill ${ok ? "ok" : "err"}">${log.status_code}</span></td>
                    <td class="num tabular mono">${formatNumber(log.total_tokens)}</td>
                    <td class="num tabular mono">${formatNumber(log.latency_ms)} ms</td>
                </tr>`;
            })
            .join("");

        tbody.querySelectorAll("tr.clickable").forEach((tr) => {
            tr.addEventListener("click", () => {
                const logObj = ov.recent_logs.find((l) => l.id === tr.dataset.logId);
                if (logObj) openLogDetailModal(logObj);
            });
        });
    }
}

// --- View 2: API Keys ---
async function renderKeysView() {
    try {
        const res = await apiFetch("/api/admin/keys");
        state.keys = res.keys || [];
        $("keys-require-toggle").checked = Boolean(res.require_api_key);
    } catch (e) {
        showToast(e.message, "err");
        return;
    }

    const tbody = $("keys-table-body");
    if (state.keys.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color: var(--text-dim); padding: 24px;">Belum ada API Key. Klik "+ Generate API Key" untuk membuat baru.</td></tr>`;
        return;
    }

    tbody.innerHTML = state.keys
        .map((k) => {
            const revealed = state.revealedKeys.has(k.id);
            const displayKey = revealed ? k.key_value : `${k.key_value.slice(0, 12)}••••••••••••••••${k.key_value.slice(-4)}`;
            return `
            <tr>
                <td>
                    <div style="font-weight: 600;">${escapeHtml(k.name)}</div>
                    <div style="font-size:11.5px; color:var(--text-dim);">Dibuat ${escapeHtml(formatTime(k.created_at))}</div>
                </td>
                <td>
                    <div style="display:flex; align-items:center; gap:6px;">
                        <code class="mono" style="font-size:12px; color:var(--text); background:var(--bg); padding:3px 7px; border-radius:4px; border:1px solid var(--border);">${escapeHtml(displayKey)}</code>
                        <button class="btn btn-icon" data-action="reveal" data-id="${escapeHtml(k.id)}">${revealed ? "Hide" : "Show"}</button>
                        <button class="btn btn-icon" data-action="copy" data-id="${escapeHtml(k.id)}">Copy</button>
                    </div>
                </td>
                <td class="mono" style="font-size:12px;">${k.allowed_model === "*" ? "Semua Model (*)" : escapeHtml(k.allowed_model)}</td>
                <td class="num tabular mono">${formatNumber(k.request_count)}</td>
                <td class="num tabular mono">${formatNumber(k.total_tokens)}</td>
                <td>
                    <label class="switch">
                        <input type="checkbox" data-action="toggle-active" data-id="${escapeHtml(k.id)}" ${k.is_active ? "checked" : ""}>
                        <span class="slider"></span>
                    </label>
                </td>
                <td class="num">
                    <button class="btn btn-sm btn-danger" data-action="delete-key" data-id="${escapeHtml(k.id)}">Hapus</button>
                </td>
            </tr>`;
        })
        .join("");

    tbody.querySelectorAll("button[data-action]").forEach((btn) => {
        const id = btn.dataset.id;
        const keyObj = state.keys.find((x) => x.id === id);
        if (!keyObj) return;

        btn.addEventListener("click", async () => {
            if (btn.dataset.action === "reveal") {
                if (state.revealedKeys.has(id)) state.revealedKeys.delete(id);
                else state.revealedKeys.add(id);
                renderKeysView();
            } else if (btn.dataset.action === "copy") {
                copyText(keyObj.key_value, `API Key '${keyObj.name}' disalin`);
            } else if (btn.dataset.action === "delete-key") {
                if (!confirm(`Hapus API Key "${keyObj.name}"? Klien yang menggunakan key ini akan ditolak.`)) return;
                await apiFetch(`/api/admin/keys/${id}`, { method: "DELETE" });
                showToast("API Key dihapus", "ok");
                await loadAllCoreData();
                renderKeysView();
            }
        });
    });

    tbody.querySelectorAll('input[data-action="toggle-active"]').forEach((chk) => {
        chk.addEventListener("change", async () => {
            await apiFetch(`/api/admin/keys/${chk.dataset.id}`, {
                method: "PATCH",
                body: { is_active: chk.checked },
            });
            showToast(chk.checked ? "API Key diaktifkan" : "API Key dinonaktifkan", "ok");
            await loadAllCoreData();
        });
    });
}

function openCreateKeyModal() {
    const modelOptions = [
        `<option value="*">Semua Model (*)</option>`,
        ...state.supportedModels.map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`),
    ].join("");

    openModal(
        "Generate API Key Baru",
        `
        <div class="form-group">
            <label class="form-label">Nama / Label Key</label>
            <input type="text" id="new-key-name" class="input" placeholder="contoh: Cursor Laptop / CrewAI Agent / HP">
        </div>
        <div class="form-group">
            <label class="form-label">Batasan Model (Scope)</label>
            <select id="new-key-model" class="select">${modelOptions}</select>
            <span style="font-size:12px; color:var(--text-muted);">Pilih "*" agar klien bebas memilih model apapun, atau kunci ke model tertentu.</span>
        </div>
        `,
        `
        <button class="btn" id="modal-cancel-btn">Batal</button>
        <button class="btn btn-primary" id="modal-create-key-confirm">Generate Key</button>
        `
    );

    $("modal-cancel-btn").onclick = closeModal;
    $("modal-create-key-confirm").onclick = async () => {
        const name = $("new-key-name").value.trim();
        const allowed_model = $("new-key-model").value;
        if (!name) {
            showToast("Nama key harus diisi", "err");
            return;
        }
        try {
            const res = await apiFetch("/api/admin/keys", {
                method: "POST",
                body: { name, allowed_model },
            });
            closeModal();
            state.revealedKeys.add(res.key.id);
            await copyText(res.key.key_value, "API Key baru dibuat & disalin ke clipboard");
            await loadAllCoreData();
            renderKeysView();
        } catch (e) {
            showToast(e.message, "err");
        }
    };
}

// --- View 3: Models & Routing ---
async function renderModelsView() {
    try {
        const res = await apiFetch("/api/admin/routes");
        state.routes = res.routes || [];
        state.supportedModels = res.supported_models || [];
    } catch (e) {
        showToast(e.message, "err");
        return;
    }

    const modelsTbody = $("models-native-body");
    modelsTbody.innerHTML = state.supportedModels
        .map(
            (m) => `
        <tr>
            <td class="mono">${escapeHtml(m)}</td>
            <td><span class="pill ok">Ready via agy.exe</span></td>
            <td class="num">
                <button class="btn btn-sm" data-test-model="${escapeHtml(m)}">Test Latency</button>
            </td>
        </tr>`
        )
        .join("");

    modelsTbody.querySelectorAll("button[data-test-model]").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const model = btn.dataset.testModel;
            btn.disabled = true;
            btn.textContent = "Testing...";
            try {
                const res = await apiFetch("/api/admin/models/test", {
                    method: "POST",
                    body: { model },
                });
                showToast(`${model}: ${res.latency_ms} ms (${res.reply})`, "ok");
            } catch (e) {
                showToast(`Test gagal: ${e.message}`, "err");
            } finally {
                btn.disabled = false;
                btn.textContent = "Test Latency";
            }
        });
    });

    const routesTbody = $("routes-table-body");
    if (state.routes.length === 0) {
        routesTbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:var(--text-dim); padding:20px;">Belum ada custom alias routing.</td></tr>`;
    } else {
        routesTbody.innerHTML = state.routes
            .map(
                (r) => `
            <tr>
                <td class="mono" style="color:var(--accent);">${escapeHtml(r.alias)}</td>
                <td class="mono">${escapeHtml(r.target_model)}</td>
                <td style="color:var(--text-muted);">${escapeHtml(r.description || "—")}</td>
                <td class="num">
                    <button class="btn btn-sm btn-danger" data-delete-route="${escapeHtml(r.alias)}">Hapus</button>
                </td>
            </tr>`
            )
            .join("");

        routesTbody.querySelectorAll("button[data-delete-route]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const alias = btn.dataset.deleteRoute;
                await apiFetch(`/api/admin/routes/${encodeURIComponent(alias)}`, { method: "DELETE" });
                showToast(`Alias '${alias}' dihapus`, "ok");
                renderModelsView();
            });
        });
    }
}

function openAddRouteModal() {
    const modelOptions = state.supportedModels
        .map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`)
        .join("");

    openModal(
        "Tambah / Ubah Model Alias Route",
        `
        <div class="form-group">
            <label class="form-label">Alias / Nama Model dari Klien</label>
            <input type="text" id="route-alias" class="input mono" placeholder="contoh: gpt-4o atau my-coding-agent">
        </div>
        <div class="form-group">
            <label class="form-label">Target Model AGY Resmi</label>
            <select id="route-target" class="select mono">${modelOptions}</select>
        </div>
        <div class="form-group">
            <label class="form-label">Catatan (Opsional)</label>
            <input type="text" id="route-desc" class="input" placeholder="contoh: Dipakai untuk LangGraph researcher">
        </div>
        `,
        `
        <button class="btn" id="modal-cancel-btn">Batal</button>
        <button class="btn btn-primary" id="modal-save-route">Simpan Route</button>
        `
    );

    $("modal-cancel-btn").onclick = closeModal;
    $("modal-save-route").onclick = async () => {
        const alias = $("route-alias").value.trim();
        const target_model = $("route-target").value;
        const description = $("route-desc").value.trim();
        if (!alias) {
            showToast("Alias model wajib diisi", "err");
            return;
        }
        try {
            await apiFetch("/api/admin/routes", {
                method: "POST",
                body: { alias, target_model, description },
            });
            closeModal();
            showToast(`Route '${alias}' -> '${target_model}' disimpan`, "ok");
            renderModelsView();
        } catch (e) {
            showToast(e.message, "err");
        }
    };
}

// --- View 4: Integration Center (Connect) ---
function getConnectBaseUrl() {
    const srv = state.overview?.server || {};
    const port = srv.port || 8000;
    if (state.connectHostMode === "lan") {
        return `http://${srv.lan_ip || "127.0.0.1"}:${port}/v1`;
    }
    if (state.connectHostMode === "tunnel") {
        const tunnelUrl = state.tunnel?.public_url || srv.tunnel_url || "";
        if (tunnelUrl) {
            const clean = tunnelUrl.replace(/\/+$/, "");
            return clean.endsWith("/v1") ? clean : `${clean}/v1`;
        }
        return `https://TUNNEL-BELUM-AKTIF.trycloudflare.com/v1`;
    }
    if (state.connectHostMode === "custom") {
        const raw = (state.connectCustomUrl || "").trim().replace(/\/+$/, "");
        if (!raw) return `http://127.0.0.1:${port}/v1`;
        return raw.endsWith("/v1") ? raw : `${raw}/v1`;
    }
    return `http://127.0.0.1:${port}/v1`;
}

async function renderConnectView() {
    try {
        state.tunnel = await apiFetch("/api/admin/tunnel");
    } catch {}

    const keySelect = $("connect-key-select");
    const activeKeys = state.keys.filter((k) => k.is_active);
    keySelect.innerHTML =
        activeKeys.length > 0
            ? activeKeys
                  .map(
                      (k) =>
                          `<option value="${escapeHtml(k.key_value)}" ${
                              k.key_value === state.connectSelectedKey ? "selected" : ""
                          }>${escapeHtml(k.name)} (${escapeHtml(k.key_prefix)})</option>`
                  )
                  .join("")
            : `<option value="sk-agy-your-key">Belum ada key aktif</option>`;

    const modelSelect = $("connect-model-select");
    modelSelect.innerHTML = state.supportedModels
        .map(
            (m) =>
                `<option value="${escapeHtml(m)}" ${m === state.connectSelectedModel ? "selected" : ""}>${escapeHtml(m)}</option>`
        )
        .join("");

    const srv = state.overview?.server || {};
    $("connect-lan-label").textContent = `LAN (${srv.lan_ip || "127.0.0.1"}:${srv.port || 8000})`;

    const liveUrl = state.tunnel?.public_url || srv.tunnel_url;
    $("connect-tunnel-label").textContent = liveUrl
        ? `Cloudflare Tunnel (${liveUrl})`
        : "Cloudflare Tunnel (Belum Aktif)";

    if (state.connectHostMode === "custom") {
        $("connect-custom-url-wrap").classList.remove("hidden");
    } else {
        $("connect-custom-url-wrap").classList.add("hidden");
    }

    updateConnectSnippets();
}

function updateConnectSnippets() {
    const baseUrl = getConnectBaseUrl();
    const apiKey = state.connectSelectedKey || "sk-agy-YOUR_API_KEY";
    const model = state.connectSelectedModel || "gemini-3.8-flash-high";

    $("connect-resolved-url").textContent = baseUrl;

    const snippets = {
        python: `from openai import OpenAI

client = OpenAI(
    base_url="${baseUrl}",
    api_key="${apiKey}",
)

response = client.chat.completions.create(
    model="${model}",
    messages=[
        {"role": "system", "content": "Kamu adalah asisten AI yang membantu."},
        {"role": "user", "content": "Halo, apakah kamu terhubung?"}
    ],
    stream=True,
    user="agent-session-1"  # Opsional: mempertahankan memori multi-turn AGY
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="", flush=True)`,

        langchain: `# 1. LangChain / LangGraph
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="${baseUrl}",
    api_key="${apiKey}",
    model="${model}",
)
print(llm.invoke("Ringkas arsitektur proxy ini.").content)

# 2. CrewAI / AutoGen (via environment variables)
# export OPENAI_API_BASE="${baseUrl}"
# export OPENAI_API_KEY="${apiKey}"
# export OPENAI_MODEL_NAME="${model}"`,

        cursor: `// Konfigurasi untuk Cursor, Cline, Continue, atau Open WebUI
{
  "provider": "openai",
  "apiBase": "${baseUrl}",
  "apiKey": "${apiKey}",
  "model": "${model}"
}

// Untuk Continue (~/.continue/config.json):
{
  "models": [
    {
      "title": "AGY (${model})",
      "provider": "openai",
      "model": "${model}",
      "apiBase": "${baseUrl}",
      "apiKey": "${apiKey}"
    }
  ]
}`,

        nodejs: `import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "${baseUrl}",
  apiKey: "${apiKey}",
});

const stream = await client.chat.completions.create({
  model: "${model}",
  messages: [{ role: "user", content: "Halo dari Node.js!" }],
  stream: true,
});

for await (const chunk of stream) {
  process.stdout.write(chunk.choices[0]?.delta?.content || "");
}`,

        curl: `curl -X POST "${baseUrl}/chat/completions" \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${apiKey}" \\
  -d '{
    "model": "${model}",
    "messages": [
      {"role": "user", "content": "Tes koneksi AGY Router via cURL"}
    ],
    "stream": false
  }'`,
    };

    const code = snippets[state.connectTab] || snippets.python;
    $("connect-code-pre").textContent = code;
    $("connect-copy-code-btn").onclick = () => copyText(code, "Snippet kode disalin");
    $("connect-copy-url-btn").onclick = () => copyText(baseUrl, "Base URL disalin");
}

// --- View 4B: Tunnel & Service ---
async function renderTunnelView() {
    try {
        const [tun, svcRes] = await Promise.all([
            apiFetch("/api/admin/tunnel"),
            apiFetch("/api/admin/service"),
        ]);
        state.tunnel = tun;
        state.serviceInfo = svcRes;
    } catch (e) {
        showToast(e.message, "err");
        return;
    }

    const t = state.tunnel;
    const srv = state.overview?.server || {};

    if (!srv.require_api_key || state.isDefaultPassword) {
        $("tunnel-security-warn").classList.remove("hidden");
    } else {
        $("tunnel-security-warn").classList.add("hidden");
    }

    const errBox = $("tunnel-error-box");
    if (t.error) {
        errBox.textContent = `Tunnel Error: ${t.error}`;
        errBox.classList.remove("hidden");
    } else {
        errBox.classList.add("hidden");
    }

    const pill = $("tunnel-status-pill");
    const sideBadge = $("sidebar-tunnel-status");
    if (t.running) {
        pill.textContent = `Online (${t.mode === "token" ? "Named" : "Quick"} · ${t.protocol})`;
        pill.className = "pill ok";
        sideBadge.textContent = "Tunnel ON";
        sideBadge.style.color = "var(--accent)";
    } else {
        pill.textContent = "Offline";
        pill.className = "pill";
        sideBadge.textContent = "Local";
        sideBadge.style.color = "var(--text-dim)";
    }

    $("tunnel-binary-info").textContent = t.installed
        ? `Terpasang: ${t.binary_path}`
        : "Belum terpasang — klik 'Start Tunnel' untuk auto-install dan langsung menyala.";

    const installBtn = $("tunnel-install-btn");
    installBtn.classList.toggle("hidden", Boolean(t.installed));

    $("tunnel-public-url").textContent = t.public_url || "—";
    $("tunnel-openai-url").textContent = t.openai_base_url || "—";

    $("tunnel-copy-public-btn").onclick = () => {
        if (t.public_url) copyText(t.public_url, "Public URL disalin");
    };
    $("tunnel-copy-v1-btn").onclick = () => {
        if (t.openai_base_url) copyText(t.openai_base_url, "OpenAI Base URL disalin");
    };

    const activeMode = t.running ? t.mode : (t.saved_mode || "quick");
    $("tunnel-mode-select").value = activeMode;
    updateTunnelModeFields(activeMode);

    $("tunnel-protocol-select").value = t.running ? (t.protocol || "http2") : (t.saved_protocol || "http2");

    if (t.saved_custom_url && !$("tunnel-custom-url-input").value) {
        $("tunnel-custom-url-input").value = t.saved_custom_url;
    }
    if (t.has_token && !$("tunnel-token-input").value) {
        $("tunnel-token-input").placeholder = "Token tersimpan (kosongkan jika tidak diubah)";
    }

    $("tunnel-autostart-toggle").checked = Boolean(t.autostart);
    $("tunnel-start-btn").disabled = false;
    $("tunnel-start-btn").textContent = t.running ? "Restart Tunnel" : "Start Tunnel";
    $("tunnel-stop-btn").disabled = !t.running;

    const logsText = (t.recent_logs && t.recent_logs.length > 0)
        ? t.recent_logs.join("\n")
        : "Tunnel belum dijalankan.";
    $("tunnel-logs-pre").textContent = logsText;

    renderDeviceAndServiceSection();
}

function updateTunnelModeFields(mode) {
    $("tunnel-token-wrap").classList.toggle("hidden", mode !== "token");
}

function renderDeviceAndServiceSection() {
    const info = state.serviceInfo;
    if (!info) return;
    const d = info.device || {};
    const svc = info.service || {};

    $("dev-os").textContent = `${d.os_display || d.os_type}${d.is_wsl ? " (WSL)" : ""}`;
    $("dev-arch").textContent = `${d.arch || "—"} · ${d.hostname || "—"}`;
    $("dev-backend").textContent = d.service_backend || "—";
    $("dev-lan").textContent = `${d.lan_ip || "127.0.0.1"}:${d.port || 8000}`;

    const svcPill = $("svc-state-pill");
    if (svc.installed && svc.running) {
        svcPill.textContent = `Aktif (${svc.state})`;
        svcPill.className = "pill ok";
    } else if (svc.installed) {
        svcPill.textContent = `Terpasang (${svc.state})`;
        svcPill.className = "pill warn";
    } else {
        svcPill.textContent = "Belum Terpasang";
        svcPill.className = "pill";
    }

    $("svc-uninstall-btn").disabled = !svc.installed;

    const cliPrefix = d.os_type === "windows" ? ".\\agy-router.bat" : "./agy-router";
    const cliText = `# Setup interaktif otomatis sesuai perangkat (${d.os_type}):
${cliPrefix} setup

# Diagnostik perangkat & cek status gateway:
${cliPrefix} doctor
${cliPrefix} status

# Install / hapus background service 24/7 + tunnel:
${cliPrefix} service install --tunnel
${cliPrefix} service uninstall

# Jalankan Cloudflare Free Tunnel langsung dari CLI:
${cliPrefix} tunnel start`;

    $("cli-commands-pre").textContent = cliText;
    $("cli-copy-btn").onclick = () => copyText(cliText, "Perintah CLI disalin");
}

// --- View 5: Playground ---
function renderPlaygroundView() {
    const keySel = $("pg-key-select");
    const activeKeys = state.keys.filter((k) => k.is_active);
    keySel.innerHTML =
        activeKeys.length > 0
            ? activeKeys
                  .map(
                      (k) =>
                          `<option value="${escapeHtml(k.key_value)}">${escapeHtml(k.name)} (${escapeHtml(k.key_prefix)})</option>`
                  )
                  .join("")
            : `<option value="">Tidak ada key aktif</option>`;

    const modelSel = $("pg-model-select");
    modelSel.innerHTML = state.supportedModels
        .map(
            (m) =>
                `<option value="${escapeHtml(m)}" ${
                    m === (state.settings?.default_model || "gemini-3.8-flash-high") ? "selected" : ""
                }>${escapeHtml(m)}</option>`
        )
        .join("");

    if (!$("pg-session-id").value) {
        $("pg-session-id").value = "pg-" + Math.random().toString(36).slice(2, 8);
    }

    updatePlaygroundTopbar();
}

function updatePlaygroundTopbar() {
    const model = $("pg-model-select")?.value || "gemini-3.8-flash-high";
    $("pg-active-info").textContent = `Model: ${model}`;
    $("pg-turn-count").textContent = `${state.playgroundHistory.length} pesan`;
}

function createChatRow(role, initialText = "", meta = "") {
    const emptyState = $("pg-empty-state");
    if (emptyState) emptyState.classList.add("hidden");

    const container = $("pg-messages");
    const row = document.createElement("div");
    row.className = `chat-row ${role}`;

    const avatar = document.createElement("div");
    avatar.className = "chat-avatar";
    avatar.textContent = role === "user" ? "YOU" : "AGY";

    const bubble = document.createElement("div");
    bubble.className = "chat-msg";

    const metaDiv = document.createElement("div");
    metaDiv.className = "chat-msg-meta";
    metaDiv.innerHTML = `<span>${role === "user" ? "Anda" : "Antigravity"}</span><span class="mono">${escapeHtml(meta)}</span>`;

    const bodyDiv = document.createElement("div");
    if (role === "user") {
        bodyDiv.textContent = initialText;
    } else {
        bodyDiv.innerHTML = initialText ? renderMarkdown(initialText) : "";
    }

    bubble.appendChild(metaDiv);
    bubble.appendChild(bodyDiv);
    row.appendChild(avatar);
    row.appendChild(bubble);
    container.appendChild(row);
    container.scrollTop = container.scrollHeight;

    return { row, bubble, bodyDiv, metaDiv };
}

function attachAssistantActions(bubble, rawText, canRegenerate = true) {
    const existing = bubble.querySelector(".msg-actions");
    if (existing) existing.remove();

    const actions = document.createElement("div");
    actions.className = "msg-actions";

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "btn btn-icon";
    copyBtn.textContent = "Copy";
    copyBtn.onclick = () => copyText(rawText, "Jawaban disalin");
    actions.appendChild(copyBtn);

    if (canRegenerate) {
        const regenBtn = document.createElement("button");
        regenBtn.type = "button";
        regenBtn.className = "btn btn-icon";
        regenBtn.textContent = "Regenerate";
        regenBtn.onclick = () => regenerateLastAssistant();
        actions.appendChild(regenBtn);
    }

    bubble.appendChild(actions);
}

async function regenerateLastAssistant() {
    if (state.playgroundStreaming || state.playgroundHistory.length === 0) return;
    if (state.playgroundHistory[state.playgroundHistory.length - 1].role === "assistant") {
        state.playgroundHistory.pop();
    }
    const lastUser = [...state.playgroundHistory].reverse().find((m) => m.role === "user");
    if (!lastUser) return;

    const container = $("pg-messages");
    if (container.lastElementChild?.classList.contains("assistant")) {
        container.lastElementChild.remove();
    }
    await runPlaygroundRequest(lastUser.content, false);
}

async function sendPlaygroundMessage(overridePrompt = null) {
    if (state.playgroundStreaming) return;
    const input = $("pg-input");
    const prompt = (overridePrompt !== null ? overridePrompt : input.value).trim();
    if (!prompt) return;

    if (overridePrompt === null) {
        input.value = "";
        input.style.height = "42px";
    }

    const model = $("pg-model-select").value;
    createChatRow("user", prompt, model);
    state.playgroundHistory.push({ role: "user", content: prompt });
    await runPlaygroundRequest(prompt, true);
}

async function runPlaygroundRequest(_prompt, _isNew) {
    const apiKey = $("pg-key-select").value;
    const model = $("pg-model-select").value;
    const effort = $("pg-effort-select").value;
    const stream = $("pg-stream-toggle").checked;
    const userSession = $("pg-session-id").value.trim();
    const sysPrompt = $("pg-system-prompt").value.trim();

    updatePlaygroundTopbar();

    state.playgroundStreaming = true;
    state.playgroundAbort = new AbortController();
    $("pg-send-btn").classList.add("hidden");
    $("pg-stop-btn").classList.remove("hidden");

    const assistantNode = createChatRow("assistant", "", "Menghubungkan ke agy.exe...");
    assistantNode.bodyDiv.classList.add("streaming-cursor");
    const startTs = performance.now();

    const outboundMessages = sysPrompt
        ? [{ role: "system", content: sysPrompt }, ...state.playgroundHistory]
        : [...state.playgroundHistory];

    try {
        const headers = { "Content-Type": "application/json" };
        if (apiKey) {
            headers["Authorization"] = `Bearer ${apiKey}`;
        }

        const res = await fetch("/v1/chat/completions", {
            method: "POST",
            headers,
            signal: state.playgroundAbort.signal,
            body: JSON.stringify({
                model,
                messages: outboundMessages,
                stream,
                user: userSession || undefined,
                effort: effort || undefined,
            }),
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData?.detail?.error?.message || errData?.detail || `HTTP ${res.status}`);
        }

        if (stream) {
            const reader = res.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let accumulated = "";
            let buffer = "";
            let usageTokens = 0;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop() || "";

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    const dataStr = line.slice(6).trim();
                    if (dataStr === "[DONE]") continue;
                    let parsed;
                    try {
                        parsed = JSON.parse(dataStr);
                    } catch {
                        continue;
                    }
                    if (parsed.error) {
                        throw new Error(parsed.error.message || "Stream error dari AGY CLI");
                    }
                    if (parsed.usage?.total_tokens) {
                        usageTokens = parsed.usage.total_tokens;
                    }
                    const delta = parsed.choices?.[0]?.delta?.content || "";
                    if (delta) {
                        accumulated += delta;
                        assistantNode.bodyDiv.innerHTML = renderMarkdown(accumulated);
                        $("pg-messages").scrollTop = $("pg-messages").scrollHeight;
                    }
                }
            }

            assistantNode.bodyDiv.classList.remove("streaming-cursor");
            assistantNode.bodyDiv.innerHTML = renderMarkdown(accumulated || "(Respon kosong)");
            const elapsed = Math.round(performance.now() - startTs);
            const tokLabel = usageTokens ? ` · ${formatNumber(usageTokens)} tok` : "";
            assistantNode.metaDiv.lastElementChild.textContent = `${model}${tokLabel} · ${elapsed} ms`;
            state.playgroundHistory.push({ role: "assistant", content: accumulated });
            attachAssistantActions(assistantNode.bubble, accumulated, true);
        } else {
            const data = await res.json();
            const reply = data.choices?.[0]?.message?.content || "";
            const elapsed = Math.round(performance.now() - startTs);
            const tokens = data.usage?.total_tokens || 0;
            assistantNode.bodyDiv.classList.remove("streaming-cursor");
            assistantNode.bodyDiv.innerHTML = renderMarkdown(reply);
            assistantNode.metaDiv.lastElementChild.textContent = `${model} · ${formatNumber(tokens)} tok · ${elapsed} ms`;
            state.playgroundHistory.push({ role: "assistant", content: reply });
            attachAssistantActions(assistantNode.bubble, reply, true);
        }
    } catch (e) {
        assistantNode.bodyDiv.classList.remove("streaming-cursor");
        if (e.name === "AbortError") {
            assistantNode.metaDiv.lastElementChild.textContent = "Dihentikan oleh user";
            if (!assistantNode.bodyDiv.textContent.trim()) {
                assistantNode.bodyDiv.textContent = "(Generasi dihentikan)";
            }
        } else {
            assistantNode.bodyDiv.innerHTML = `<div class="alert-danger" style="margin:0;">Error: ${escapeHtml(e.message)}</div>`;
            assistantNode.metaDiv.lastElementChild.textContent = "Failed";
        }
    } finally {
        state.playgroundStreaming = false;
        state.playgroundAbort = null;
        $("pg-send-btn").classList.remove("hidden");
        $("pg-stop-btn").classList.add("hidden");
        updatePlaygroundTopbar();
        $("pg-messages").scrollTop = $("pg-messages").scrollHeight;
    }
}

// --- View 6: Logs ---
async function renderLogsView() {
    const keyFilter = $("logs-filter-key").value;
    const statusFilter = $("logs-filter-status").value;

    const filterSel = $("logs-filter-key");
    const prevVal = filterSel.value;
    filterSel.innerHTML =
        `<option value="">Semua API Key</option>` +
        state.keys.map((k) => `<option value="${escapeHtml(k.id)}">${escapeHtml(k.name)}</option>`).join("");
    filterSel.value = prevVal;

    const params = new URLSearchParams({ limit: "100" });
    if (keyFilter) params.set("api_key_id", keyFilter);
    if (statusFilter) params.set("status", statusFilter);

    try {
        const res = await apiFetch(`/api/admin/logs?${params.toString()}`);
        state.logs = res.logs || [];
    } catch (e) {
        showToast(e.message, "err");
        return;
    }

    const tbody = $("logs-table-body");
    if (state.logs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--text-dim); padding:24px;">Tidak ada log request yang sesuai filter.</td></tr>`;
        return;
    }

    tbody.innerHTML = state.logs
        .map((log) => {
            const ok = log.status_code < 400;
            return `
            <tr class="clickable" data-log-id="${escapeHtml(log.id)}">
                <td class="mono" style="font-size:12px; color:var(--text-muted);">${escapeHtml(formatTime(log.timestamp))}</td>
                <td>${escapeHtml(log.api_key_name || "—")}</td>
                <td class="mono" style="font-size:12px;">${escapeHtml(log.resolved_model || "—")}</td>
                <td><span class="pill">${log.stream ? "SSE" : "JSON"}</span></td>
                <td><span class="pill ${ok ? "ok" : "err"}">${log.status_code}</span></td>
                <td class="num tabular mono">${formatNumber(log.total_tokens)}</td>
                <td class="num tabular mono">${formatNumber(log.latency_ms)} ms</td>
            </tr>`;
        })
        .join("");

    tbody.querySelectorAll("tr.clickable").forEach((tr) => {
        tr.addEventListener("click", () => {
            const logObj = state.logs.find((l) => l.id === tr.dataset.logId);
            if (logObj) openLogDetailModal(logObj);
        });
    });
}

function openLogDetailModal(log) {
    openModal(
        `Detail Request ${log.id}`,
        `
        <div class="form-group">
            <label class="form-label">Waktu &amp; Status</label>
            <div class="mono" style="font-size:12.5px;">${escapeHtml(formatTime(log.timestamp))} · HTTP ${log.status_code} · ${log.latency_ms} ms</div>
        </div>
        <div class="form-group">
            <label class="form-label">API Key &amp; Endpoint</label>
            <div class="mono" style="font-size:12.5px;">${escapeHtml(log.api_key_name || "—")} → ${escapeHtml(log.endpoint)} (${log.stream ? "Stream" : "Non-Stream"})</div>
        </div>
        <div class="form-group">
            <label class="form-label">Model Resolution</label>
            <div class="mono" style="font-size:12.5px;">Requested: ${escapeHtml(log.requested_model || "—")} → Resolved: ${escapeHtml(log.resolved_model || "—")}</div>
        </div>
        <div class="form-group">
            <label class="form-label">Token Usage</label>
            <div class="mono" style="font-size:12.5px;">Prompt: ${formatNumber(log.prompt_tokens)} | Completion: ${formatNumber(log.completion_tokens)} | Total: ${formatNumber(log.total_tokens)}</div>
        </div>
        <div class="form-group">
            <label class="form-label">Conversation ID</label>
            <div class="mono" style="font-size:12.5px;">${escapeHtml(log.conversation_id || "—")}</div>
        </div>
        <div class="form-group">
            <label class="form-label">Prompt Preview</label>
            <pre class="mono" style="background:var(--bg); border:1px solid var(--border); padding:10px; border-radius:6px; font-size:12px; white-space:pre-wrap;">${escapeHtml(log.prompt_preview || "—")}</pre>
        </div>
        ${
            log.error_message
                ? `<div class="form-group"><label class="form-label" style="color:var(--danger);">Error Message</label><pre class="mono" style="background:var(--danger-tint); border:1px solid rgba(239,68,68,0.3); padding:10px; border-radius:6px; font-size:12px; color:#fca5a5; white-space:pre-wrap;">${escapeHtml(log.error_message)}</pre></div>`
                : ""
        }
        `,
        `<button class="btn" id="modal-close-ok">Tutup</button>`
    );
    $("modal-close-ok").onclick = closeModal;
}

function stopLogsAutoRefresh() {
    state.logsAutoRefresh = false;
    if ($("logs-autorefresh-toggle")) {
        $("logs-autorefresh-toggle").checked = false;
    }
    if (state.logsTimer) {
        clearInterval(state.logsTimer);
        state.logsTimer = null;
    }
}

// --- View 7: Settings ---
async function renderSettingsView() {
    try {
        const s = await apiFetch("/api/admin/settings");
        state.settings = s;

        const modelSel = $("settings-default-model");
        modelSel.innerHTML = (s.supported_models || state.supportedModels)
            .map((m) => `<option value="${escapeHtml(m)}" ${m === s.default_model ? "selected" : ""}>${escapeHtml(m)}</option>`)
            .join("");

        $("settings-require-key").checked = Boolean(s.require_api_key);
        $("settings-allow-tools").checked = Boolean(s.allow_tool_execution);

        $("diag-binary").textContent = s.agy_binary || "—";
        $("diag-host").textContent = `${s.host}:${s.port} (LAN: ${s.lan_ip})`;
    } catch (e) {
        showToast(e.message, "err");
    }
}

// --- Event Bindings ---
function bindEvents() {
    // Login form
    $("login-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const password = $("login-password").value;
        $("login-error").classList.add("hidden");
        try {
            const res = await apiFetch("/api/auth/login", {
                method: "POST",
                body: { password },
            });
            if (res.session_token) {
                setSessionToken(res.session_token);
            }
            state.authenticated = true;
            state.isDefaultPassword = Boolean(res.is_default_password);
            await enterDashboard();
        } catch (err) {
            $("login-error").textContent = err.message;
            $("login-error").classList.remove("hidden");
        }
    });

    // Logout
    $("logout-btn").addEventListener("click", async () => {
        await apiFetch("/api/auth/logout", { method: "POST" }).catch(() => {});
        clearSessionToken();
        state.authenticated = false;
        stopLogsAutoRefresh();
        showLoginGate();
    });

    // Mobile drawer
    $("mobile-menu-btn").addEventListener("click", () => {
        $("sidebar").classList.toggle("open");
    });

    // Sidebar nav
    document.querySelectorAll(".nav-item[data-view]").forEach((btn) => {
        btn.addEventListener("click", () => switchView(btn.dataset.view));
    });

    // Default password banner buttons
    $("banner-go-settings").addEventListener("click", () => switchView("settings"));
    $("banner-dismiss").addEventListener("click", () => $("default-pw-banner").classList.add("hidden"));

    // Modal close
    $("modal-close-x").addEventListener("click", closeModal);
    $("modal-backdrop").addEventListener("click", (e) => {
        if (e.target === $("modal-backdrop")) closeModal();
    });

    // Overview buttons
    $("ov-refresh-btn").addEventListener("click", renderOverviewView);
    $("ov-view-all-logs").addEventListener("click", () => switchView("logs"));

    // Keys view
    $("create-key-btn").addEventListener("click", openCreateKeyModal);
    $("keys-require-toggle").addEventListener("change", async () => {
        const val = $("keys-require-toggle").checked;
        await apiFetch("/api/admin/settings", {
            method: "PATCH",
            body: { require_api_key: val },
        });
        showToast(val ? "Wajib API Key diaktifkan" : "Akses API tanpa key diizinkan", "ok");
    });

    // Models & Routing
    $("add-route-btn").addEventListener("click", openAddRouteModal);
    $("refresh-models-btn").addEventListener("click", async () => {
        const btn = $("refresh-models-btn");
        btn.disabled = true;
        btn.textContent = "Memuat...";
        try {
            const res = await apiFetch("/api/admin/models/refresh", { method: "POST" });
            if (res.models && res.models.length > 0) {
                state.supportedModels = res.models.map((m) => m.id);
                renderModelsView();
                showToast(`${state.supportedModels.length} model disinkronkan dari agy.exe`, "ok");
            }
        } catch (e) {
            showToast(e.message, "err");
        } finally {
            btn.disabled = false;
            btn.textContent = "Sync dari AGY CLI";
        }
    });

    // Connect view controls
    $("connect-key-select").addEventListener("change", (e) => {
        state.connectSelectedKey = e.target.value;
        updateConnectSnippets();
    });
    $("connect-model-select").addEventListener("change", (e) => {
        state.connectSelectedModel = e.target.value;
        updateConnectSnippets();
    });
    document.querySelectorAll('input[name="connect-host-mode"]').forEach((radio) => {
        radio.addEventListener("change", () => {
            state.connectHostMode = radio.value;
            renderConnectView();
        });
    });
    $("connect-custom-url").addEventListener("input", (e) => {
        state.connectCustomUrl = e.target.value;
        updateConnectSnippets();
    });
    document.querySelectorAll("#connect-tabs .tab-btn").forEach((tab) => {
        tab.addEventListener("click", () => {
            document.querySelectorAll("#connect-tabs .tab-btn").forEach((t) => t.classList.remove("active"));
            tab.classList.add("active");
            state.connectTab = tab.dataset.tab;
            updateConnectSnippets();
        });
    });

    // Tunnel & Service controls
    $("tunnel-refresh-btn").addEventListener("click", renderTunnelView);
    $("tunnel-install-btn").addEventListener("click", async () => {
        const btn = $("tunnel-install-btn");
        btn.disabled = true;
        btn.textContent = "Mengunduh cloudflared...";
        try {
            await apiFetch("/api/admin/tunnel/install", { method: "POST" });
            showToast("cloudflared berhasil dipasang!", "ok");
            await renderTunnelView();
        } catch (e) {
            showToast(e.message, "err");
        } finally {
            btn.disabled = false;
            btn.textContent = "Install cloudflared";
        }
    });
    $("tunnel-mode-select").addEventListener("change", (e) => {
        updateTunnelModeFields(e.target.value);
    });
    $("tunnel-autostart-toggle").addEventListener("change", async () => {
        try {
            await apiFetch("/api/admin/tunnel/config", {
                method: "PATCH",
                body: { autostart: $("tunnel-autostart-toggle").checked },
            });
            showToast("Pengaturan auto-start tunnel disimpan", "ok");
        } catch (e) {
            showToast(e.message, "err");
        }
    });
    $("tunnel-start-btn").addEventListener("click", async () => {
        const btn = $("tunnel-start-btn");
        const mode = $("tunnel-mode-select").value || "quick";
        const protocol = $("tunnel-protocol-select").value || "http2";
        const token = $("tunnel-token-input").value.trim();
        const custom_url = $("tunnel-custom-url-input").value.trim();
        const autostart = $("tunnel-autostart-toggle").checked;

        btn.disabled = true;
        btn.textContent = "Menghubungkan...";
        try {
            const res = await apiFetch("/api/admin/tunnel/start", {
                method: "POST",
                body: {
                    mode,
                    protocol,
                    token: token || undefined,
                    custom_url,
                    autostart,
                    auto_install: true,
                },
            });
            state.tunnel = res;
            showToast(res.public_url ? `Tunnel aktif: ${res.public_url}` : "Tunnel aktif!", "ok");
            await renderTunnelView();
        } catch (e) {
            showToast(e.message, "err");
            await renderTunnelView();
        } finally {
            btn.disabled = false;
        }
    });
    $("tunnel-stop-btn").addEventListener("click", async () => {
        try {
            await apiFetch("/api/admin/tunnel/stop", { method: "POST" });
            showToast("Tunnel dihentikan", "ok");
            await renderTunnelView();
        } catch (e) {
            showToast(e.message, "err");
        }
    });

    // 1-Click Native 24/7 Service buttons
    $("svc-install-btn").addEventListener("click", async () => {
        const btn = $("svc-install-btn");
        btn.disabled = true;
        btn.textContent = "Memasang service...";
        try {
            const enable_tunnel = $("tunnel-autostart-toggle").checked;
            const res = await apiFetch("/api/admin/service/install", {
                method: "POST",
                body: { enable_tunnel },
            });
            state.serviceInfo = res;
            showToast("Service 24/7 terpasang & aktif!", "ok");
            renderDeviceAndServiceSection();
        } catch (e) {
            showToast(e.message, "err");
        } finally {
            btn.disabled = false;
            btn.textContent = "Install & Aktifkan Service 24/7";
        }
    });

    $("svc-uninstall-btn").addEventListener("click", async () => {
        if (!confirm("Hentikan dan hapus background service 24/7 di perangkat ini?")) return;
        const btn = $("svc-uninstall-btn");
        btn.disabled = true;
        try {
            const res = await apiFetch("/api/admin/service/uninstall", { method: "POST" });
            state.serviceInfo = res;
            showToast("Service 24/7 dihapus", "ok");
            renderDeviceAndServiceSection();
        } catch (e) {
            showToast(e.message, "err");
        } finally {
            btn.disabled = false;
        }
    });

    // Playground
    $("pg-model-select").addEventListener("change", updatePlaygroundTopbar);
    $("pg-send-btn").addEventListener("click", () => sendPlaygroundMessage());
    $("pg-stop-btn").addEventListener("click", () => {
        if (state.playgroundAbort) {
            state.playgroundAbort.abort();
        }
    });
    $("pg-input").addEventListener("input", () => {
        const el = $("pg-input");
        el.style.height = "42px";
        el.style.height = Math.min(150, el.scrollHeight) + "px";
    });
    $("pg-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendPlaygroundMessage();
        }
    });
    $("pg-clear-btn").addEventListener("click", () => {
        if (state.playgroundAbort) state.playgroundAbort.abort();
        state.playgroundHistory = [];
        $("pg-session-id").value = "pg-" + Math.random().toString(36).slice(2, 8);
        const container = $("pg-messages");
        container.querySelectorAll(".chat-row").forEach((r) => r.remove());
        const emptyState = $("pg-empty-state");
        if (emptyState) emptyState.classList.remove("hidden");
        updatePlaygroundTopbar();
    });
    $("pg-messages").addEventListener("click", (e) => {
        const copyCodeBtn = e.target.closest(".md-copy-code");
        if (copyCodeBtn) {
            const codeEl = copyCodeBtn.closest(".md-code-wrap")?.querySelector("pre code");
            if (codeEl) copyText(codeEl.textContent, "Kode disalin");
            return;
        }
        const chip = e.target.closest(".starter-chip");
        if (chip && chip.dataset.prompt) {
            sendPlaygroundMessage(chip.dataset.prompt);
        }
    });

    // Logs
    $("logs-filter-key").addEventListener("change", renderLogsView);
    $("logs-filter-status").addEventListener("change", renderLogsView);
    $("logs-refresh-btn").addEventListener("click", renderLogsView);
    $("logs-clear-btn").addEventListener("click", async () => {
        if (!confirm("Hapus seluruh riwayat log request?")) return;
        await apiFetch("/api/admin/logs", { method: "DELETE" });
        showToast("Log dibersihkan", "ok");
        renderLogsView();
    });
    $("logs-autorefresh-toggle").addEventListener("change", () => {
        state.logsAutoRefresh = $("logs-autorefresh-toggle").checked;
        if (state.logsAutoRefresh) {
            state.logsTimer = setInterval(renderLogsView, 5000);
        } else {
            stopLogsAutoRefresh();
        }
    });

    // Settings
    $("settings-save-btn").addEventListener("click", async () => {
        try {
            await apiFetch("/api/admin/settings", {
                method: "PATCH",
                body: {
                    default_model: $("settings-default-model").value,
                    require_api_key: $("settings-require-key").checked,
                    allow_tool_execution: $("settings-allow-tools").checked,
                },
            });
            showToast("Pengaturan gateway disimpan", "ok");
            await loadAllCoreData();
        } catch (e) {
            showToast(e.message, "err");
        }
    });

    $("settings-pw-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const current_password = $("pw-current").value;
        const new_password = $("pw-new").value;
        const confirm_pw = $("pw-confirm").value;
        if (new_password !== confirm_pw) {
            showToast("Konfirmasi password baru tidak cocok", "err");
            return;
        }
        try {
            await apiFetch("/api/auth/change-password", {
                method: "POST",
                body: { current_password, new_password },
            });
            state.isDefaultPassword = false;
            updateDefaultPasswordBanner();
            $("settings-pw-form").reset();
            showToast("Password admin berhasil diperbarui", "ok");
        } catch (err) {
            showToast(err.message, "err");
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    checkAuthAndBoot();
});
