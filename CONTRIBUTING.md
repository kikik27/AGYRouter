# Contributing to AGYRouter

Thank you for your interest in **AGYRouter**! This project is **Open Source** under the **MIT License**, created by **[@kikik27](https://github.com/kikik27)**.

If you encounter a bug, need support for a new workflow, or want to add features, please **Open an Issue** or submit a **Pull Request (PR)** at [https://github.com/kikik27/AGYRouter](https://github.com/kikik27/AGYRouter).

---

## 🐛 Reporting Issues

1. Open an issue at [https://github.com/kikik27/AGYRouter/issues](https://github.com/kikik27/AGYRouter/issues) using the **Bug Report** or **Feature Request** template.
2. Include your OS/architecture, Python version, `agy-router doctor` output, and relevant logs.
3. **Never share `.env`, `sk-agy-...` keys, or Cloudflare Tunnel tokens.**

---

## 🔧 Submitting a Pull Request

1. Fork [kikik27/AGYRouter](https://github.com/kikik27/AGYRouter) and create a feature branch:
   ```bash
   git checkout -b feat/my-improvement
   ```
2. Set up the local virtual environment and run the test suite:
   ```bash
   python -m venv .venv
   # Windows: .\.venv\Scripts\python -m pip install -r requirements.txt
   # Linux/macOS: ./.venv/bin/python -m pip install -r requirements.txt
   python -m unittest tests.test_proxy -v
   ```
3. If modifying frontend JavaScript, verify syntax with Node:
   ```bash
   node --check app/static/js/api.js
   node --check app/static/js/charts.js
   node --check app/static/js/markdown.js
   node --check app/static/js/app.js
   ```
4. Ensure all changes preserve **100% ToS compliance** (interacting strictly through the official `agy` CLI binary without token scraping or auth bypasses).
5. Open a Pull Request describing what changed and how you tested it!
