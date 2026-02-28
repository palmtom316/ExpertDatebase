from pathlib import Path
import unittest


class TestProjectLayout(unittest.TestCase):
    def test_required_dirs_exist(self) -> None:
        required = [
            "services/api-server/app",
            "services/worker/worker",
            "shared/models",
            "shared/configs",
            "docker",
        ]
        root = Path(__file__).resolve().parents[2]
        for rel in required:
            self.assertTrue((root / rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()
