import unittest

from shared.configs.loader import load_all_configs


class TestConfigLoader(unittest.TestCase):
    def test_load_all_configs_has_versions(self) -> None:
        cfg = load_all_configs()
        self.assertEqual(cfg["keyword_rules"]["version"], "v1.0")
        self.assertEqual(cfg["page_type_rules"]["version"], "v1.0")
        self.assertEqual(cfg["routing_policy"]["version"], "routing_policy_v1")


if __name__ == "__main__":
    unittest.main()
