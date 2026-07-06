"""merge_agents: capability union, conservative trust, merged version."""
import unittest

from agents.examples import CODE_AGENT, FINANCE_AGENT, SEARCH_AGENT
from registry.merger import capability_union, merge_agents
from registry.schema import TrustLevel


class TestMerger(unittest.TestCase):
    def test_capability_union_dedup_best_rate(self):
        caps = capability_union([CODE_AGENT, SEARCH_AGENT])
        names = [c.name.lower() for c in caps]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(caps), len(CODE_AGENT.skills) + len(SEARCH_AGENT.skills)
                         - len(set(n.lower() for n in
                               [s.name for s in CODE_AGENT.skills]) &
                               set(s.name.lower() for s in SEARCH_AGENT.skills)))

    def test_merge_conservative_trust(self):
        merged = merge_agents([CODE_AGENT, FINANCE_AGENT], "m1", "Merged", "desc")
        # FINANCE is self_declared, CODE is verified -> min wins
        self.assertEqual(merged.trust_level, TrustLevel.SELF_DECLARED)
        self.assertTrue(merged.version.startswith("merged-"))
        self.assertEqual(merged.ttl_seconds,
                         min(CODE_AGENT.ttl_seconds, FINANCE_AGENT.ttl_seconds))

    def test_merge_empty_raises(self):
        with self.assertRaises(ValueError):
            merge_agents([], "m1", "Merged", "desc")


if __name__ == "__main__":
    unittest.main()
