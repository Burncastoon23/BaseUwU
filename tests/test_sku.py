"""SKU code stability, alias resolution, search."""
import unittest

from agents.examples import CODE_AGENT, FINANCE_AGENT
from registry.schema import TrustLevel
from registry.sku import SKURegistry, generate_sku


class TestSkuStability(unittest.TestCase):
    def test_code_has_no_tier(self):
        sku = generate_sku(CODE_AGENT)
        self.assertNotIn(sku.tier.value, sku.sku_code.split("-"))
        self.assertEqual(len(sku.sku_code.split("-")), 3)

    def test_code_stable_across_trust_change(self):
        reg = SKURegistry()
        import copy
        card = copy.deepcopy(FINANCE_AGENT)
        first = reg.register(card)
        card.trust_level = TrustLevel.UNVERIFIED
        second = reg.register(card)
        self.assertEqual(first.sku_code, second.sku_code)
        self.assertNotEqual(first.tier, second.tier)

    def test_legacy_code_becomes_alias(self):
        reg = SKURegistry()
        import copy
        card = copy.deepcopy(CODE_AGENT)
        sku = reg.register(card)
        # Simulate a legacy 4-part code already registered
        legacy_code = f"CODE-WRITE_CO-VRF-{sku.short_hash}"
        reg._skus[legacy_code] = reg._skus.pop(sku.sku_code)
        reg._skus[legacy_code].sku_code = legacy_code
        reg._by_agent[card.agent_id] = legacy_code
        # Re-register: code migrates to stable format, legacy becomes alias
        new = reg.register(card)
        self.assertEqual(len(new.sku_code.split("-")), 3)
        resolved, resolved_from = reg.resolve(legacy_code)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.sku_code, new.sku_code)
        self.assertEqual(resolved_from, legacy_code)

    def test_deactivate_and_search(self):
        reg = SKURegistry()
        reg.register(CODE_AGENT)
        reg.register(FINANCE_AGENT)
        self.assertEqual(len(reg.list_active()), 2)
        reg.deactivate(CODE_AGENT.agent_id)
        self.assertEqual(len(reg.list_active()), 1)
        results = reg.search(query="portfoli")  # subcategory is truncated to 8 chars
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].agent_id, FINANCE_AGENT.agent_id)


if __name__ == "__main__":
    unittest.main()
