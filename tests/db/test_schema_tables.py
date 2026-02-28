import unittest

from shared.models.base import Base


class TestSchemaTables(unittest.TestCase):
    def test_core_tables_registered(self) -> None:
        expected = {
            "documents",
            "document_versions",
            "chunks",
            "assets",
            "llm_call_log",
            "eval_run",
            "eval_sample",
            "eval_result",
            "entity_dictionary",
        }
        actual = set(Base.metadata.tables.keys())
        self.assertTrue(expected.issubset(actual), f"missing: {expected - actual}")


if __name__ == "__main__":
    unittest.main()
