"""SQLiteStore round-trips and simulated restart."""
import copy
import os
import tempfile
import unittest

from agents.examples import CODE_AGENT, SEARCH_AGENT
from registry.sku import SKURegistry
from registry.store import SQLiteStore


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "test.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_agent_roundtrip_and_restart(self):
        store = SQLiteStore(self.db)
        self.assertTrue(store.is_empty())
        store.save_agent(CODE_AGENT)
        store.save_agent(SEARCH_AGENT)
        store.close()
        # "Restart": new store on the same file
        store2 = SQLiteStore(self.db)
        agents = store2.load_agents()
        self.assertEqual(set(agents), {CODE_AGENT.agent_id, SEARCH_AGENT.agent_id})
        self.assertEqual(agents[CODE_AGENT.agent_id].name, CODE_AGENT.name)
        store2.close()

    def test_delete_agent(self):
        store = SQLiteStore(self.db)
        store.save_agent(CODE_AGENT)
        store.delete_agent(CODE_AGENT.agent_id)
        self.assertEqual(store.load_agents(), {})
        store.close()

    def test_sku_and_alias_roundtrip(self):
        reg = SKURegistry()
        sku = reg.register(copy.deepcopy(CODE_AGENT))
        store = SQLiteStore(self.db)
        store.save_sku(sku)
        store.save_alias("OLD-CODE-VRF-1234", sku.sku_code)
        store.close()
        store2 = SQLiteStore(self.db)
        skus = store2.load_skus()
        self.assertEqual(len(skus), 1)
        self.assertEqual(skus[0].sku_code, sku.sku_code)
        self.assertEqual(store2.load_aliases(), {"OLD-CODE-VRF-1234": sku.sku_code})
        store2.close()

    def test_verification_history(self):
        store = SQLiteStore(self.db)
        store.add_verification("a1", {"agent_id": "a1", "timestamp": "2026-01-01T00:00:00", "passed": 2})
        store.add_verification("a2", {"agent_id": "a2", "timestamp": "2026-01-02T00:00:00", "passed": 1})
        self.assertEqual(len(store.load_history()), 2)
        self.assertEqual(len(store.load_history("a1")), 1)
        store.close()


if __name__ == "__main__":
    unittest.main()
