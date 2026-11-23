"""Validation must reject bad configuration before contacting Nexus."""

import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_validation import SUPPORTED_REPOSITORY_TYPES, validate_config
from main import FORMAT_MODULE_MAP, load_config_from_dir, main


class ValidateConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "nexus": {
                "url": "http://nexus.example.test:8081",
                "username": "admin",
                "password": "secret",
            },
            "blobs": [{"name": "storage", "type": "file"}],
            "repositories": {
                "apt": [{
                    "name": "ubuntu",
                    "type": "proxy",
                    "blob_store": "storage",
                    "remote_url": "https://archive.ubuntu.com/ubuntu/",
                }]
            },
        }

    def errors(self):
        return validate_config(self.config, FORMAT_MODULE_MAP)

    def test_valid_configuration(self):
        self.assertEqual(self.errors(), [])

    def test_gitlfs_hosted_is_supported(self):
        self.config["repositories"] = {
            "gitlfs": [{"name": "gitlfs-hosted", "type": "hosted", "blob_store": "storage"}]
        }
        self.assertEqual(self.errors(), [])

    def test_gitlfs_proxy_and_group_are_rejected(self):
        for repo_type in ("proxy", "group"):
            with self.subTest(repo_type=repo_type):
                self.config["repositories"] = {
                    "gitlfs": [{"name": "gitlfs-bad", "type": repo_type}]
                }
                errors = " ".join(self.errors())
                self.assertIn(f"unsupported type '{repo_type}' for format 'gitlfs'", errors)
                self.assertIn("supported: hosted", errors)

    def test_apt_group_is_rejected(self):
        self.config["repositories"]["apt"] = [{
            "name": "apt-group", "type": "group", "members": ["apt-proxy"]
        }]
        self.assertIn("unsupported type 'group' for format 'apt'", " ".join(self.errors()))

    def test_conda_only_supports_proxy(self):
        for repo_type in ("hosted", "group"):
            with self.subTest(repo_type=repo_type):
                self.config["repositories"] = {
                    "conda": [{"name": "conda-bad", "type": repo_type}]
                }
                self.assertIn(f"unsupported type '{repo_type}' for format 'conda'", " ".join(self.errors()))

    def test_capability_registry_matches_module_handlers(self):
        self.assertEqual(set(SUPPORTED_REPOSITORY_TYPES), set(FORMAT_MODULE_MAP))
        for fmt, module_name in FORMAT_MODULE_MAP.items():
            with self.subTest(format=fmt):
                module = importlib.import_module(f"modules.{module_name}")
                available = {
                    repo_type for repo_type in ("hosted", "proxy", "group")
                    if callable(getattr(module, f"_create_{repo_type}", None))
                }
                self.assertEqual(SUPPORTED_REPOSITORY_TYPES[fmt], available)

    def test_rejects_duplicate_blob_stores(self):
        self.config["blobs"].append({"name": "storage"})
        self.assertIn("duplicate blob store", " ".join(self.errors()))

    def test_rejects_duplicate_repository_across_formats(self):
        self.config["repositories"]["raw"] = [{"name": "ubuntu", "type": "hosted"}]
        self.assertIn("duplicate repository", " ".join(self.errors()))

    def test_rejects_non_mapping_entries(self):
        self.config["blobs"].append("bad")
        self.config["repositories"]["apt"].append("bad")
        errors = " ".join(self.errors())
        self.assertIn("blobs[1]: expected a mapping", errors)
        self.assertIn("repositories.apt[1]: expected a mapping", errors)

    def test_rejects_invalid_sections(self):
        self.config["repositories"] = ["bad"]
        self.config["blobs"] = {}
        self.assertIn("repositories: expected a mapping", self.errors())
        self.assertIn("blobs: expected a list", self.errors())

    def test_rejects_unknown_section_and_format(self):
        self.config["settings"] = {"debug": True}
        self.config["repositories"]["appt"] = []
        errors = " ".join(self.errors())
        self.assertIn("unknown section", errors)
        self.assertIn("unknown repository format", errors)

    def test_rejects_missing_nexus_fields_and_bad_url(self):
        self.config["nexus"]["url"] = "ftp://nexus.example.test"
        self.config["nexus"]["username"] = " "
        self.config["nexus"]["password"] = None
        errors = " ".join(self.errors())
        self.assertIn("nexus.url", errors)
        self.assertIn("nexus.username", errors)
        self.assertIn("nexus.password", errors)

    def test_rejects_missing_repository_fields(self):
        repo = self.config["repositories"]["apt"][0]
        repo["name"] = " "
        repo["type"] = None
        repo["blob_store"] = ""
        errors = " ".join(self.errors())
        self.assertIn(".name", errors)
        self.assertIn(".type", errors)
        self.assertIn(".blob_store", errors)

    def test_rejects_invalid_proxy_url(self):
        self.config["repositories"]["apt"][0]["remote_url"] = "https://user:pass@example.test"
        self.assertIn("remote_url", " ".join(self.errors()))

    def test_rejects_group_without_valid_members(self):
        self.config["repositories"] = {
            "raw": [{"name": "all", "type": "group", "members": ["", "ubuntu"]}]
        }
        self.assertIn(".members", " ".join(self.errors()))

    def test_rejects_invalid_repository_type(self):
        self.config["repositories"]["apt"][0]["type"] = "federated"
        self.assertIn(".type", " ".join(self.errors()))

    def test_rejects_incomplete_s3_blob(self):
        self.config["blobs"][0] = {
            "name": "storage", "type": "s3", "s3_provider": "minio"
        }
        errors = " ".join(self.errors())
        self.assertIn(".bucket", errors)
        self.assertIn(".endpoint", errors)

    def test_validates_repository_example_configuration(self):
        config_dir = Path(__file__).resolve().parents[1] / "config.d"
        data = load_config_from_dir(str(config_dir))
        self.assertEqual(validate_config(data, FORMAT_MODULE_MAP), [])


class ValidateBeforeProvisioningTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.config_dir = Path(temp_dir.name)

    def write(self, filename, text):
        (self.config_dir / filename).write_text(text, encoding="utf-8")

    def test_rejects_invalid_root_yaml(self):
        self.write("00-nexus.yml", "- list\n- not mapping\n")
        with self.assertRaises(SystemExit) as exit_ctx:
            load_config_from_dir(str(self.config_dir))
        self.assertEqual(exit_ctx.exception.code, 1)

    def test_rejects_malformed_yaml(self):
        self.write("00-nexus.yml", "nexus: [invalid\n")
        with self.assertRaises(SystemExit) as exit_ctx:
            load_config_from_dir(str(self.config_dir))
        self.assertEqual(exit_ctx.exception.code, 1)

    def test_rejects_duplicate_yaml_mapping_keys(self):
        self.write("00-nexus.yml", "nexus:\n  url: http://a\n  url: http://b\n")
        with self.assertRaises(SystemExit) as exit_ctx:
            load_config_from_dir(str(self.config_dir))
        self.assertEqual(exit_ctx.exception.code, 1)

    def test_rejects_duplicate_repository_format_keys_in_same_file(self):
        self.write(
            "00-nexus.yml",
            "nexus: {}\nrepositories:\n  apt: []\n  apt: []\n",
        )
        with self.assertRaises(SystemExit) as exit_ctx:
            load_config_from_dir(str(self.config_dir))
        self.assertEqual(exit_ctx.exception.code, 1)

    def test_rejects_invalid_blob_section(self):
        self.write("00-nexus.yml", "nexus: {}\nblobs: invalid\n")
        with self.assertRaises(SystemExit) as exit_ctx:
            load_config_from_dir(str(self.config_dir))
        self.assertEqual(exit_ctx.exception.code, 1)

    def test_unsupported_gitlfs_stops_before_session_creation(self):
        self.write(
            "00-nexus.yml",
            "nexus:\n  url: http://localhost:8081\n  username: test\n  password: test\n",
        )
        self.write(
            "10-gitlfs.yml",
            "repositories:\n  gitlfs:\n    - name: gitlfs-proxy\n      type: proxy\n"
            "      remote_url: https://github.com\n",
        )
        for options in ([], ["--dry-run"]):
            with self.subTest(options=options), \
                    patch("sys.argv", ["main.py", "--config-dir", str(self.config_dir)] + options), \
                    patch("main.build_session") as build_session, \
                    patch("main.verify_connection") as verify_connection:
                with self.assertRaises(SystemExit) as exit_ctx:
                    main()
                self.assertEqual(exit_ctx.exception.code, 1)
                build_session.assert_not_called()
                verify_connection.assert_not_called()

    def test_invalid_config_stops_before_session_creation(self):
        self.write("00-nexus.yml", "nexus:\n  url: http://localhost:8081\n")
        self.write("10-repos.yml", "repositories:\n  apt:\n    - name: ubuntu\n      type: proxy\n")
        for options in ([], ["--dry-run"]):
            with self.subTest(options=options), \
                    patch("sys.argv", ["main.py", "--config-dir", str(self.config_dir)] + options), \
                    patch("main.build_session") as build_session, \
                    patch("main.verify_connection") as verify_connection:
                with self.assertRaises(SystemExit) as exit_ctx:
                    main()
                self.assertEqual(exit_ctx.exception.code, 1)
                build_session.assert_not_called()
                verify_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
