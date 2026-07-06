"""End-to-end API tests: ephemeral server + real HTTP requests."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from api import server as srv


def _request(base, method, path, body=None, key=None):
    req = urllib.request.Request(base + path, method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, data=data) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class ApiTestBase(unittest.TestCase):
    API_KEYS = ""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["REGISTRY_DB"] = os.path.join(cls.tmp.name, "api.db")
        if cls.API_KEYS:
            os.environ["REGISTRY_API_KEYS"] = cls.API_KEYS
        else:
            os.environ.pop("REGISTRY_API_KEYS", None)
        srv._init_state()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.AgentRegistryHandler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        if srv._store:
            srv._store.close()
        os.environ.pop("REGISTRY_DB", None)
        os.environ.pop("REGISTRY_API_KEYS", None)
        cls.tmp.cleanup()


class TestApiOpenMode(ApiTestBase):
    def test_health(self):
        status, body = _request(self.base, "GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["agent_count"], 3)

    def test_register_persist_delete(self):
        card = {"agent_id": "t1", "name": "T", "version": "1", "description": "data analysis",
                "provider": "x", "endpoint": "http://x", "skills": [], "trust_level": "unverified"}
        status, _ = _request(self.base, "POST", "/agents", body=card)
        self.assertEqual(status, 201)
        # persisted?
        self.assertIn("t1", srv._store.load_agents())
        status, _ = _request(self.base, "DELETE", "/agents/t1")
        self.assertEqual(status, 200)
        self.assertNotIn("t1", srv._store.load_agents())

    def test_sku_lookup_and_agent(self):
        status, skus = _request(self.base, "GET", "/sku")
        self.assertEqual(status, 200)
        code = skus[0]["sku_code"]
        self.assertEqual(len(code.split("-")), 3)  # stable format
        status, sku = _request(self.base, "GET", f"/sku/{code}")
        self.assertEqual(status, 200)
        status, agent = _request(self.base, "GET", f"/sku/{code}/agent")
        self.assertEqual(status, 200)
        self.assertEqual(agent["agent_id"], sku["agent_id"])

    def test_consolidate_dry_run(self):
        status, report = _request(self.base, "POST", "/agents/consolidate?dry_run=true")
        self.assertEqual(status, 200)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["removed_ids"], [])

    def test_unknown_route_404(self):
        status, _ = _request(self.base, "GET", "/nope")
        self.assertEqual(status, 404)


class TestApiAuthMode(ApiTestBase):
    API_KEYS = "admin:test-admin-key,read:test-read-key"

    def test_get_open_post_locked(self):
        status, _ = _request(self.base, "GET", "/health")
        self.assertEqual(status, 200)
        status, body = _request(self.base, "POST", "/agents/consolidate?dry_run=true")
        self.assertEqual(status, 401)
        status, _ = _request(self.base, "POST", "/agents/consolidate?dry_run=true", key="bad")
        self.assertEqual(status, 403)
        status, _ = _request(self.base, "POST", "/agents/consolidate?dry_run=true", key="test-read-key")
        self.assertEqual(status, 403)
        status, _ = _request(self.base, "POST", "/agents/consolidate?dry_run=true", key="test-admin-key")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
