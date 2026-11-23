# Changelog

All notable changes to **AGYRouter** will be documented in this file.

## [2.0.0] - 2026-11-23

### Added
- **Official `agy` CLI Bridge**: OpenAI-compatible (`/v1/chat/completions`, `/v1/models`) and native REST (`/api/chat`, `/health`) gateway powered directly by the official `agy` subprocess (`stream-json`) for 100% ToS compliance.
- **9Router-Style Web Dashboard**: Flat dark-terminal developer console with Overview KPIs, 24h SVG traffic chart, model distribution, API Key management (`sk-agy-...`), custom alias routing, Integration Center, Playground, Request Logs, and Settings.
- **Persistent Admin Auth**: 30-day HMAC-signed HttpOnly cookie + `localStorage` `X-Admin-Token` header fallback with PBKDF2-HMAC-SHA256 password hashing.
- **Device-Aware `agy-router` CLI & 24/7 Services**: Interactive `setup` wizard, `doctor`, `status`, `keys`, `tunnel`, `service`, and `password` commands with automatic detection and 1-click background service installation for Windows (Task Scheduler), Linux (`systemd --user`), and macOS (`launchd`).
- **Cloudflare Free Tunnel Manager**: Built-in `cloudflared` auto-installer, Quick Tunnel (`*.trycloudflare.com` with `--protocol http2`), Named Tunnel (`--token`), live log viewer, and auto-start toggle.
- **Playground Markdown & Controls**: XSS-safe Markdown rendering with code-block Copy buttons, System Prompt support, Stop (`AbortController`), Copy/Regenerate actions, and starter prompt chips.
- **System Efficiency**: SQLite WAL persistence, delta-turn prompt trimming on `--conversation` continuations, concurrency semaphore (`MAX_CONCURRENT_REQUESTS`), and subprocess timeouts (`AGY_TIMEOUT_SECONDS`).
