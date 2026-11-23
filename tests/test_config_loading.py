"""Regression tests for loading configuration from multiple YAML files."""

import tempfile
import unittest
from pathlib import Path

from main import load_config_from_dir


class LoadConfigFromDirTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config_dir = Path(self.temp_dir.name)
        self.write_config("00-nexus.yml", "nexus:\n  url: http://localhost:8081\n")

    def write_config(self, filename, content):
        (self.config_dir / filename).write_text(content, encoding="utf-8")

    def test_merges_same_repository_format_across_files(self):
        self.write_config(
            "20-apt.yml",
            "repositories:\n  apt:\n    - name: ubuntu\n      type: proxy\n",
        )
        self.write_config(
            "21-apt-extra.yaml",
            "repositories:\n  apt:\n    - name: debian\n      type: proxy\n",
        )

        result = load_config_from_dir(str(self.config_dir))

        self.assertEqual(
            [repo["name"] for repo in result["repositories"]["apt"]],
            ["ubuntu", "debian"],
        )

    def test_merges_different_repository_formats(self):
        self.write_config(
            "20-apt.yml", "repositories:\n  apt:\n    - name: ubuntu\n"
        )
        self.write_config(
            "21-docker.yml", "repositories:\n  docker:\n    - name: images\n"
        )

        result = load_config_from_dir(str(self.config_dir))

        self.assertEqual(result["repositories"]["apt"][0]["name"], "ubuntu")
        self.assertEqual(result["repositories"]["docker"][0]["name"], "images")

    def test_existing_blob_list_merge_is_unchanged(self):
        self.write_config("10-blobs.yml", "blobs:\n  - name: primary\n")
        self.write_config("11-blobs.yml", "blobs:\n  - name: secondary\n")

        result = load_config_from_dir(str(self.config_dir))

        self.assertEqual(
            [blob["name"] for blob in result["blobs"]],
            ["primary", "secondary"],
        )

    def test_yaml_extensions_share_one_lexicographic_order(self):
        self.write_config("01-second.yaml", "blobs:\n  - name: first\n")
        self.write_config("02-third.yml", "blobs:\n  - name: second\n")
        result = load_config_from_dir(str(self.config_dir))
        self.assertEqual([item["name"] for item in result["blobs"]], ["first", "second"])

    def test_rejects_non_list_repository_definitions(self):
        self.write_config("20-apt.yml", "repositories:\n  apt: invalid\n")

        with self.assertRaises(SystemExit) as context:
            load_config_from_dir(str(self.config_dir))

        self.assertEqual(context.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
