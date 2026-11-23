(function () {
  "use strict";

  const toastEl = document.getElementById("toast");
  let toastTimer = null;

  function showToast(message) {
    if (!toastEl) return;
    toastEl.textContent = message || "Copied to clipboard";
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toastEl.classList.remove("show");
    }, 1800);
  }

  async function copyText(text) {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      showToast("Copied to clipboard");
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      showToast("Copied to clipboard");
    }
  }

  // Global copy handlers
  document.addEventListener("click", (ev) => {
    const targetBtn = ev.target.closest("[data-copy-target]");
    if (targetBtn) {
      const el = document.getElementById(targetBtn.dataset.copyTarget);
      if (el) copyText(el.textContent.trim());
      return;
    }

    const secretBtn = ev.target.closest("[data-copy-secret]");
    if (secretBtn) {
      const el = document.getElementById(secretBtn.dataset.copySecret);
      if (el) copyText(el.dataset.secret || el.textContent.trim());
    }
  });

  // Hero OS quick-install switcher
  const HERO_COMMANDS = {
    windows: "git clone https://github.com/kikik27/AGYRouter.git && cd AGYRouter && .\\agy-router.bat setup",
    unix: "git clone https://github.com/kikik27/AGYRouter.git && cd AGYRouter && chmod +x agy-router deploy/linux/*.sh && ./agy-router setup"
  };

  const heroCmdEl = document.getElementById("hero-install-cmd");
  document.querySelectorAll("[data-hero-os]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-hero-os]").forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      if (heroCmdEl) {
        heroCmdEl.textContent = HERO_COMMANDS[btn.dataset.heroOs] || HERO_COMMANDS.windows;
      }
    });
  });

  // Interactive Dashboard Preview tabs
  document.querySelectorAll("[data-dash-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.dashTab;
      document.querySelectorAll("[data-dash-tab]").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll("[data-dash-panel]").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      const panel = document.querySelector(`[data-dash-panel="${tab}"]`);
      if (panel) panel.classList.add("active");
    });
  });

  // API Keys Reveal/Hide and Copy demo
  document.querySelectorAll(".toggle-key-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = btn.closest("tr");
      const codeEl = row && row.querySelector(".key-cell");
      if (!codeEl) return;
      const fullKey = codeEl.dataset.fullKey || "";
      const isShown = btn.dataset.shown === "1";
      if (isShown) {
        codeEl.textContent = `${fullKey.slice(0, 11)}••••••••`;
        btn.textContent = "Reveal";
        btn.dataset.shown = "0";
      } else {
        codeEl.textContent = fullKey;
        btn.textContent = "Hide";
        btn.dataset.shown = "1";
      }
    });
  });

  document.querySelectorAll(".copy-key-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = btn.closest("tr");
      const codeEl = row && row.querySelector(".key-cell");
      if (codeEl && codeEl.dataset.fullKey) {
        copyText(codeEl.dataset.fullKey);
      }
    });
  });

  // Tunnel Start/Stop simulated toggle
  const tunnelToggleBtn = document.getElementById("demo-tunnel-toggle");
  const tunnelPillEl = document.getElementById("demo-tunnel-pill");
  const tunnelUrlEl = document.getElementById("demo-tunnel-url");
  const tunnelStatusEl = document.getElementById("demo-tunnel-status-text");
  let tunnelActive = true;

  if (tunnelToggleBtn) {
    tunnelToggleBtn.addEventListener("click", () => {
      tunnelActive = !tunnelActive;
      if (tunnelActive) {
        tunnelToggleBtn.textContent = "Stop Tunnel (Demo)";
        if (tunnelPillEl) {
          tunnelPillEl.textContent = "Tunnel Running";
          tunnelPillEl.className = "pill-ok";
        }
        if (tunnelUrlEl) tunnelUrlEl.textContent = "https://demo-gateway.trycloudflare.com/v1";
        if (tunnelStatusEl) tunnelStatusEl.textContent = "Forwarding \u2192 127.0.0.1:8000";
      } else {
        tunnelToggleBtn.textContent = "Start Free Quick Tunnel (Demo)";
        if (tunnelPillEl) {
          tunnelPillEl.textContent = "Tunnel Stopped";
          tunnelPillEl.className = "pill-stopped";
        }
        if (tunnelUrlEl) tunnelUrlEl.textContent = "Not active — click Start to spawn HTTP/2 tunnel";
        if (tunnelStatusEl) tunnelStatusEl.textContent = "cloudflared idle";
      }
    });
  }

  // Playground prompt samples
  const PG_SAMPLES = {
    python: {
      user: "Show a minimal OpenAI Python call targeting AGYRouter.",
      intro: "Point <code>base_url</code> to your local AGYRouter instance and pass your <code>sk-agy-...</code> key:",
      lang: "python",
      code: `from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="sk-agy-...")
resp = client.chat.completions.create(
    model="gemini-3.8-flash-high",
    messages=[{"role": "user", "content": "Hello AGYRouter"}],
    user="session-demo"
)
print(resp.choices[0].message.content)`
    },
    delta: {
      user: "How does AGYRouter avoid wasting tokens on multi-turn agent loops?",
      intro: "Send a consistent <code>user</code> ID. AGYRouter reuses the CLI conversation and sends only the newest turn:",
      lang: "json",
      code: `{
  "conversation_mapping": "SQLite sessions table -> --conversation <id>",
  "delta_turn_optimization": "Sends latest turn only instead of replaying full chat history",
  "concurrency_gate": "asyncio.Semaphore prevents agy CLI process thrashing"
}`
    }
  };

  const pgUserEl = document.getElementById("pg-user-text");
  const pgBodyEl = document.getElementById("pg-assistant-body");

  document.querySelectorAll("[data-pg-sample]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sample = PG_SAMPLES[btn.dataset.pgSample];
      if (!sample || !pgUserEl || !pgBodyEl) return;

      document.querySelectorAll("[data-pg-sample]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      pgUserEl.textContent = sample.user;
      const p = pgBodyEl.querySelector("p");
      const langSpan = pgBodyEl.querySelector(".pg-code-head span");
      const codeEl = document.getElementById("pg-code-snippet");
      if (p) p.innerHTML = sample.intro;
      if (langSpan) langSpan.textContent = sample.lang;
      if (codeEl) codeEl.textContent = sample.code;
    });
  });

  // CLI output tabs
  const CLI_OUTPUTS = {
    doctor: `[AGYRouter Doctor]
  OS / Arch       : Windows 11 (AMD64)
  Service Backend : Windows Task Scheduler (user-level)
  AGY CLI Binary  : FOUND -> agy (official CLI ready)
  Cloudflare Bin  : INSTALLED -> bin/cloudflared.exe
  SQLite WAL DB   : OK -> data/agy_proxy.db
  API Keys        : 3 active keys (sk-agy-...)
  Status          : Ready to serve on http://127.0.0.1:8000/v1`,
    setup: `================================================================
  AGYRouter - Interactive CLI Setup Wizard
  Open Source by kikik27 -> https://github.com/kikik27/AGYRouter
================================================================
  Device Terdeteksi : Windows 11 (AMD64)
  Service Backend   : Task Scheduler
  AGY CLI Binary    : OK -> agy

  [1/4] Admin password updated in SQLite.
  [2/4] Default API key ready -> sk-agy-a94f...
  [3/4] Cloudflare Free Tunnel (cloudflared) verified.
  [4/4] Windows Task Scheduler background task registered.`
  };

  const cliCodeEl = document.getElementById("cli-preview-code");
  document.querySelectorAll("[data-cli-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-cli-tab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      if (cliCodeEl) cliCodeEl.textContent = CLI_OUTPUTS[btn.dataset.cliTab] || CLI_OUTPUTS.doctor;
    });
  });

  // SDK integration tabs
  const SDK_SNIPPETS = {
    openai: `from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="sk-agy-YOUR_KEY",
)

stream = client.chat.completions.create(
    model="gpt-4o",  # routed to official AGY model
    messages=[{"role": "user", "content": "Refactor this module"}],
    stream=True,
    user="agent-thread-01"
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="", flush=True)`,
    langchain: `from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="claude-3-5-sonnet",  # auto-mapped via model_routes
    base_url="http://127.0.0.1:8000/v1",
    api_key="sk-agy-YOUR_KEY",
)

print(llm.invoke("Summarize our repository architecture.").content)`,
    cursor: `// Cursor / Cline / Continue / Open WebUI Settings
Base URL : http://127.0.0.1:8000/v1
API Key  : sk-agy-YOUR_KEY
Model    : gemini-3.8-flash-high (or any mapped alias)

// Works locally or over HTTPS via Cloudflare Free Tunnel:
Base URL : https://<random-subdomain>.trycloudflare.com/v1`,
    curl: `curl http://127.0.0.1:8000/v1/chat/completions \\
  -H "Authorization: Bearer sk-agy-YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gemini-3.8-flash-high",
    "messages": [{"role": "user", "content": "Ping AGYRouter"}],
    "stream": false
  }'`
  };

  const sdkCodeEl = document.getElementById("sdk-preview-code");
  document.querySelectorAll("[data-sdk-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-sdk-tab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      if (sdkCodeEl) sdkCodeEl.textContent = SDK_SNIPPETS[btn.dataset.sdkTab] || SDK_SNIPPETS.openai;
    });
  });

  // Quick Start OS tabs
  const QS_COMMANDS = {
    windows: `git clone https://github.com/kikik27/AGYRouter.git
cd AGYRouter
.\\agy-router.bat setup
.\\agy-router.bat start --tunnel`,
    linux: `git clone https://github.com/kikik27/AGYRouter.git
cd AGYRouter
chmod +x agy-router deploy/linux/*.sh
./agy-router setup
./agy-router start --tunnel`,
    macos: `git clone https://github.com/kikik27/AGYRouter.git
cd AGYRouter
chmod +x agy-router deploy/linux/*.sh
./agy-router setup
./agy-router service install`
  };

  const qsCodeEl = document.getElementById("qs-code");
  document.querySelectorAll("[data-qs-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-qs-tab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      if (qsCodeEl) qsCodeEl.textContent = QS_COMMANDS[btn.dataset.qsTab] || QS_COMMANDS.windows;
    });
  });
})();
