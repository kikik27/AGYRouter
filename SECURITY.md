# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in **AGYRouter**, please report it responsibly:

1. **Do NOT** post sensitive credentials, active `sk-agy-...` keys, Cloudflare Tunnel tokens, or database dumps publicly.
2. Open a private **Security Advisory** or open a GitHub Issue with minimal reproduction steps at [https://github.com/kikik27/AGYRouter/issues](https://github.com/kikik27/AGYRouter/issues).

---

## Deployment Security Checklist

Before exposing **AGYRouter** over LAN (`HOST=0.0.0.0`) or via a public **Cloudflare Tunnel**:

- [x] **Change the default admin password (`123456`)** immediately via Dashboard **Settings** or `agy-router password`.
- [x] **Keep `Require API Key` enabled** so `/v1/*` and `/api/chat` endpoints reject unauthenticated traffic.
- [x] **Keep `ALLOW_TOOL_EXECUTION=false`** unless you explicitly trust all API clients, as enabling tool execution passes `--dangerously-skip-permissions` to `agy`.
- [x] **Never commit `.env`, `data/`, or `bin/`** to version control (already excluded in `.gitignore`).
