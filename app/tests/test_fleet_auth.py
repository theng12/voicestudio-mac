import stat
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import fleet_auth
from backend import main
from backend.main import FLEET_TOKEN, app


class FleetAuthTests(unittest.TestCase):
    def test_public_and_protected_routes(self):
        client = TestClient(app)
        self.assertEqual(client.get("/api/health").status_code, 200)
        self.assertEqual(client.get("/api/capabilities").status_code, 200)
        self.assertEqual(client.get("/api/catalog").status_code, 401)
        authed = TestClient(app, headers={"X-Studio-Token": FLEET_TOKEN})
        self.assertEqual(authed.get("/api/catalog").status_code, 200)

    def test_cross_origin_write_rejected_even_with_token(self):
        client = TestClient(app, headers={"X-Studio-Token": FLEET_TOKEN})
        response = client.delete("/api/downloads", headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)

    def test_loopback_and_private_shared_token(self):
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
        self.assertTrue(fleet_auth.is_loopback(request))
        source = fleet_auth.HUB_TOKEN_FILE if fleet_auth.HUB_TOKEN_FILE.exists() else fleet_auth.SHARED_TOKEN_FILE
        self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o600)

    def test_saved_fleet_token_takes_effect_without_restart(self):
        with patch.object(fleet_auth, "load_token", return_value="rotated-token"):
            accepted = TestClient(app, headers={"X-Studio-Token": "rotated-token"})
            stale = TestClient(app, headers={"X-Studio-Token": FLEET_TOKEN})
            self.assertEqual(accepted.get("/api/catalog").status_code, 200)
            self.assertEqual(stale.get("/api/catalog").status_code, 401)

    def test_supported_header_bearer_and_cookie_credentials(self):
        header = TestClient(app, headers={"X-Studio-Token": FLEET_TOKEN})
        bearer = TestClient(app, headers={"Authorization": f"Bearer {FLEET_TOKEN}"})
        cookie = TestClient(app, cookies={fleet_auth.COOKIE_NAME: FLEET_TOKEN})

        self.assertEqual(header.get("/api/catalog").status_code, 200)
        self.assertEqual(bearer.get("/api/catalog").status_code, 200)
        self.assertEqual(cookie.get("/api/catalog").status_code, 200)

    def test_query_string_token_is_rejected(self):
        client = TestClient(app)

        response = client.get("/api/catalog", params={"token": FLEET_TOKEN})

        self.assertEqual(response.status_code, 401)

    def test_capability_manifest_documents_header_only_urls(self):
        auth = TestClient(app).get("/api/capabilities").json()["auth"]

        self.assertEqual(auth["header"], "X-Studio-Token")
        self.assertTrue(auth["bearer_supported"])
        self.assertTrue(auth["cookie_supported"])
        self.assertFalse(auth["query_token_supported"])

    def test_completed_cache_does_not_create_duplicate_download_history(self):
        repo = "mlx-community/VibeVoice-Realtime-0.5B-4bit"
        cached = {
            "repo": repo,
            "state": "cached",
            "snapshot_revision": "a" * 40,
            "bytes_complete": 123,
            "bytes_incomplete": 0,
        }

        with patch.object(main.manager, "active_for_repo", return_value=None), \
             patch.object(main.manager, "start", side_effect=AssertionError("download not expected")), \
             patch.object(main, "_cache_with_companions", return_value=cached):
            response = TestClient(
                app, headers={"X-Studio-Token": FLEET_TOKEN}
            ).post("/api/downloads", json={"repo": repo})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "job": None,
            "already_cached": True,
            "cache": cached,
        })

    def test_completed_cache_is_not_reused_for_a_different_revision(self):
        repo = "mlx-community/VibeVoice-Realtime-0.5B-4bit"
        cached = {
            "repo": repo,
            "state": "cached",
            "snapshot_revision": "a" * 40,
        }
        job = SimpleNamespace(serialize=lambda: {"id": "fresh", "state": "queued"})

        with patch.object(main.manager, "active_for_repo", return_value=None), \
             patch.object(main.manager, "start", return_value=job) as start, \
             patch.object(main, "_cache_with_companions", return_value=cached):
            response = TestClient(
                app, headers={"X-Studio-Token": FLEET_TOKEN}
            ).post("/api/downloads", json={
                "repo": repo,
                "revision": "b" * 40,
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["job"], {"id": "fresh", "state": "queued"})
        start.assert_called_once_with(repo, token=None, revision="b" * 40)


if __name__ == "__main__":
    unittest.main()
