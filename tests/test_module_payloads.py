"""All tracked example definitions must construct a supported REST payload.

This is a mocked contract smoke test, NOT a Nexus integration test or API
schema validation. It deliberately never opens a network connection.
"""

import unittest
from unittest.mock import Mock

from main import FORMAT_MODULE_MAP, load_config_from_dir, load_module


class ModulePayloadSmokeTests(unittest.TestCase):
    def test_every_sample_repository_can_build_a_create_request(self):
        config = load_config_from_dir("config.d")
        count = 0
        for fmt, entries in config["repositories"].items():
            module = load_module(fmt)
            self.assertIsNotNone(module, fmt)
            for entry in entries:
                with self.subTest(format=fmt, name=entry["name"], type=entry["type"]):
                    session = Mock()
                    session.get.return_value.json.return_value = []
                    session.post.return_value.status_code = 201
                    self.assertTrue(module.create_repository(session, "https://nexus.test", entry))
                    session.post.assert_called_once()
                    self.assertIn("/service/rest/v1/repositories/", session.post.call_args.args[0])
                    self.assertEqual(session.post.call_args.kwargs["json"]["name"], entry["name"])
                    count += 1
        self.assertEqual(count, 30)


if __name__ == "__main__":
    unittest.main()
