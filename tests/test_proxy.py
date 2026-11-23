import os
import sys
import tempfile
import unittest
from pathlib import Path

# Isolate SQLite test DB and disable tunnel autostart before importing app.main
_tmp_dir = tempfile.TemporaryDirectory()
os.environ["AGY_DB_PATH"] = str(Path(_tmp_dir.name) / "test_agy_proxy.db")
os.environ["AGY_DISABLE_AUTOSTART"] = "1"

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient
from app.main import app


class TestAGYProxy(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.transport = ASGITransport(app=app)
        self.client = AsyncClient(transport=self.transport, base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def _login_admin(self, password: str = "123456"):
        res = await self.client.post("/api/auth/login", json={"password": password})
        self.assertEqual(res.status_code, 200)
        return res

    async def test_01_health_check(self):
        """Test public healthcheck endpoint."""
        response = await self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)
        self.assertTrue(data.get("binary_found"))
        self.assertEqual(data.get("proxy_version"), "2.0.0")
        print("\n[PASS] Health check verified. Binary found:", data.get("binary_found"))

    async def test_02_admin_auth_flow(self):
        """Test admin session authentication gate."""
        unauth = await self.client.get("/api/admin/overview")
        self.assertEqual(unauth.status_code, 401)

        bad_login = await self.client.post("/api/auth/login", json={"password": "wrong-password"})
        self.assertEqual(bad_login.status_code, 401)

        good_login = await self._login_admin("123456")
        self.assertIn("agy_session", good_login.cookies)
        self.assertTrue(good_login.json().get("authenticated"))

        overview = await self.client.get("/api/admin/overview")
        self.assertEqual(overview.status_code, 200)
        self.assertIn("server", overview.json())
        print("\n[PASS] Admin Auth flow verified (401 -> login -> 200).")

    async def test_03_api_key_enforcement_and_crud(self):
        """Test API key enforcement on /v1/* and CRUD lifecycle."""
        no_key_res = await self.client.get("/v1/models")
        self.assertEqual(no_key_res.status_code, 401)

        await self._login_admin()
        create_res = await self.client.post(
            "/api/admin/keys",
            json={"name": "Test Agent Key", "allowed_model": "*"},
        )
        self.assertEqual(create_res.status_code, 200)
        key_obj = create_res.json()["key"]
        key_id = key_obj["id"]
        key_val = key_obj["key_value"]
        self.assertTrue(key_val.startswith("sk-agy-"))

        ok_bearer = await self.client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {key_val}"},
        )
        self.assertEqual(ok_bearer.status_code, 200)

        ok_x = await self.client.get(
            "/v1/models",
            headers={"x-api-key": key_val},
        )
        self.assertEqual(ok_x.status_code, 200)

        disable_res = await self.client.patch(
            f"/api/admin/keys/{key_id}",
            json={"is_active": False},
        )
        self.assertEqual(disable_res.status_code, 200)
        disabled_call = await self.client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {key_val}"},
        )
        self.assertEqual(disabled_call.status_code, 401)

        enable_res = await self.client.patch(
            f"/api/admin/keys/{key_id}",
            json={"is_active": True},
        )
        self.assertEqual(enable_res.status_code, 200)
        reenabled_call = await self.client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {key_val}"},
        )
        self.assertEqual(reenabled_call.status_code, 200)
        print(f"\n[PASS] API Key enforcement & CRUD verified ({key_obj['key_prefix']}).")

    async def test_04_model_routes_crud(self):
        """Test custom 9Router-style model alias routing CRUD."""
        await self._login_admin()
        keys_res = await self.client.get("/api/admin/keys")
        active_key = next(k["key_value"] for k in keys_res.json()["keys"] if k["is_active"])

        add_res = await self.client.post(
            "/api/admin/routes",
            json={
                "alias": "my-custom-agent",
                "target_model": "gemini-3.8-flash-high",
                "description": "Test custom alias",
            },
        )
        self.assertEqual(add_res.status_code, 200)

        models_res = await self.client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {active_key}"},
        )
        self.assertEqual(models_res.status_code, 200)
        model_ids = [m["id"] for m in models_res.json()["data"]]
        self.assertIn("my-custom-agent", model_ids)

        del_res = await self.client.delete("/api/admin/routes/my-custom-agent")
        self.assertEqual(del_res.status_code, 200)
        print("\n[PASS] Custom model alias routing CRUD verified.")

    async def test_05_chat_non_stream_and_logging(self):
        """Test non-streaming chat completion with API key and verify SQLite logging."""
        await self._login_admin()
        create_res = await self.client.post(
            "/api/admin/keys",
            json={"name": "Non-Stream Tester", "allowed_model": "*"},
        )
        key_val = create_res.json()["key"]["key_value"]

        payload = {
            "model": "gemini-3.8-flash-high",
            "messages": [{"role": "user", "content": "Katakan dengan singkat: 'Koneksi Berhasil'"}],
            "stream": False,
        }
        response = await self.client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {key_val}"},
            timeout=60.0,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("object"), "chat.completion")
        reply = data["choices"][0]["message"]["content"]
        self.assertTrue(len(reply) > 0)

        logs_res = await self.client.get("/api/admin/logs?limit=10")
        self.assertEqual(logs_res.status_code, 200)
        logs = logs_res.json()["logs"]
        self.assertTrue(any(l["api_key_name"] == "Non-Stream Tester" and l["status_code"] == 200 for l in logs))
        print(f"\n[PASS] Non-streaming completion & logging verified: {reply.strip()}")

    async def test_06_chat_stream_and_logging(self):
        """Test streaming chat completion (SSE) with API key and verify SQLite logging."""
        await self._login_admin()
        create_res = await self.client.post(
            "/api/admin/keys",
            json={"name": "Stream Tester", "allowed_model": "*"},
        )
        key_val = create_res.json()["key"]["key_value"]

        payload = {
            "model": "gemini-3.8-flash-high",
            "messages": [{"role": "user", "content": "Hitung 1 sampai 3"}],
            "stream": True,
        }
        response = await self.client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {key_val}"},
            timeout=60.0,
        )
        self.assertEqual(response.status_code, 200)

        chunks_received = 0
        saw_done = False
        async for line in response.aiter_lines():
            if line.strip() == "data: [DONE]":
                saw_done = True
            elif line.startswith("data: "):
                chunks_received += 1

        self.assertGreater(chunks_received, 0)
        self.assertTrue(saw_done)

        logs_res = await self.client.get("/api/admin/logs?limit=10")
        logs = logs_res.json()["logs"]
        self.assertTrue(
            any(l["api_key_name"] == "Stream Tester" and l["stream"] and l["status_code"] == 200 for l in logs)
        )
        print(f"\n[PASS] Streaming SSE & logging verified ({chunks_received} chunks).")

    async def test_07_static_ui_served(self):
        """Test that dashboard HTML and static assets are served cleanly."""
        root_res = await self.client.get("/")
        self.assertEqual(root_res.status_code, 200)
        self.assertIn("AGYRouter", root_res.text)

        for asset in [
            "/static/favicon.svg",
            "/static/css/dashboard.css",
            "/static/js/api.js",
            "/static/js/charts.js",
            "/static/js/app.js",
        ]:
            asset_res = await self.client.get(asset)
            self.assertEqual(asset_res.status_code, 200, f"Failed serving {asset}")

        print("\n[PASS] Static Dashboard UI, favicon, and JS/CSS assets verified.")

    async def test_08_tunnel_endpoints_and_config(self):
        """Test Cloudflare tunnel status & config persistence endpoints."""
        unauth = await self.client.get("/api/admin/tunnel")
        self.assertEqual(unauth.status_code, 401)

        await self._login_admin()
        status_res = await self.client.get("/api/admin/tunnel")
        self.assertEqual(status_res.status_code, 200)
        data = status_res.json()
        for key in ("installed", "running", "mode", "autostart", "recent_logs"):
            self.assertIn(key, data)

        patch_res = await self.client.patch(
            "/api/admin/tunnel/config",
            json={"autostart": True, "mode": "token", "custom_url": "https://agy.example.com"},
        )
        self.assertEqual(patch_res.status_code, 200)
        patched = patch_res.json()
        self.assertTrue(patched["autostart"])
        self.assertEqual(patched["saved_mode"], "token")
        self.assertEqual(patched["saved_custom_url"], "https://agy.example.com")

        # Reset autostart back to false
        reset_res = await self.client.patch(
            "/api/admin/tunnel/config",
            json={"autostart": False, "mode": "quick", "custom_url": ""},
        )
        self.assertEqual(reset_res.status_code, 200)
        print("\n[PASS] Cloudflare tunnel endpoints and config persistence verified.")

    async def test_09_open_source_files_and_credits(self):
        """Verify Open Source files, service installers, and kikik27 credits."""
        root = Path(__file__).parent.parent
        license_text = (root / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", license_text)
        self.assertIn("kikik27", license_text)

        self.assertTrue((root / "CONTRIBUTING.md").exists())
        self.assertTrue((root / "deploy" / "linux" / "install-systemd.sh").exists())
        self.assertTrue((root / "deploy" / "windows" / "install-windows-service.ps1").exists())

        root_res = await self.client.get("/")
        self.assertEqual(root_res.status_code, 200)
        self.assertIn("kikik27", root_res.text)
        self.assertIn("Tunnel", root_res.text)
        print("\n[PASS] Open Source files, deploy scripts, and kikik27 credit verified.")

    async def test_10_persistent_token_auth_and_delta_prompt(self):
        """Test X-Admin-Token persistent auth without cookies and delta-turn prompt trimming."""
        from app.agy_connector import format_messages_to_prompt
        from app.schemas import ChatMessage

        login_res = await self._login_admin("123456")
        session_tok = login_res.json().get("session_token")
        self.assertTrue(bool(session_tok))

        # Fresh client without cookies, authenticating solely via X-Admin-Token
        async with AsyncClient(transport=self.transport, base_url="http://test") as fresh_client:
            status_res = await fresh_client.get(
                "/api/auth/status",
                headers={"X-Admin-Token": session_tok},
            )
            self.assertEqual(status_res.status_code, 200)
            self.assertTrue(status_res.json()["authenticated"])

            ov_res = await fresh_client.get(
                "/api/admin/overview",
                headers={"X-Admin-Token": session_tok},
            )
            self.assertEqual(ov_res.status_code, 200)

        # Verify delta-turn prompt optimization avoids duplicating prior history on continuation
        msgs = [
            ChatMessage(role="system", content="You are concise."),
            ChatMessage(role="user", content="My name is Budi."),
            ChatMessage(role="assistant", content="Nice to meet you, Budi."),
            ChatMessage(role="user", content="What is my name?"),
        ]
        delta_prompt = format_messages_to_prompt(msgs, is_continuation=True)
        self.assertEqual(delta_prompt, "What is my name?")
        print("\n[PASS] Persistent X-Admin-Token auth & delta-turn prompt optimization verified.")

    async def test_11_device_detection_and_service_api(self):
        """Test device auto-detection, native service status endpoint, and markdown.js asset."""
        await self._login_admin()

        dev_res = await self.client.get("/api/admin/device")
        self.assertEqual(dev_res.status_code, 200)
        dev = dev_res.json()
        for key in ("os_type", "arch", "hostname", "service_backend", "agy_found"):
            self.assertIn(key, dev)

        svc_res = await self.client.get("/api/admin/service")
        self.assertEqual(svc_res.status_code, 200)
        svc_data = svc_res.json()
        self.assertIn("device", svc_data)
        self.assertIn("service", svc_data)
        self.assertIn("backend", svc_data["service"])

        md_res = await self.client.get("/static/js/markdown.js")
        self.assertEqual(md_res.status_code, 200)
        print(f"\n[PASS] Device detection ({dev['os_type']}/{dev['arch']}) & service API verified.")


if __name__ == "__main__":
    unittest.main()
