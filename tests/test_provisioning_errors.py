"""Regression tests for orchestration failures and exit status."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from main import main, provision_blobs, provision_repositories


class RepositoryErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        self.repos = {
            "raw": [
                {"name": "first", "type": "hosted"},
                {"name": "second", "type": "hosted"},
            ]
        }

    def test_missing_handler_counts_every_repository_in_both_modes(self):
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run), \
                    patch("main.load_module", return_value=None), \
                    self.assertLogs("main", level="ERROR") as logs:
                self.assertEqual(
                    provision_repositories(Mock(), "http://nexus", self.repos, dry_run),
                    (0, 2),
                )
                self.assertIn("No handler", " ".join(logs.output))

    def test_non_callable_handler_counts_failure(self):
        for module in (SimpleNamespace(), SimpleNamespace(create_repository=None)):
            with self.subTest(module=module), \
                    patch("main.load_module", return_value=module), \
                    self.assertLogs("main", level="ERROR"):
                self.assertEqual(
                    provision_repositories(Mock(), "http://nexus", self.repos, True),
                    (0, 2),
                )

    def test_handler_import_failure_counts_failure(self):
        with patch("main.load_module", side_effect=RuntimeError("broken import")), \
                self.assertLogs("main", level="ERROR"):
            self.assertEqual(
                provision_repositories(Mock(), "http://nexus", self.repos, True),
                (0, 2),
            )

    def test_import_error_is_logged_and_not_silently_skipped(self):
        with patch("main.importlib.import_module", side_effect=ImportError("dependency missing")), \
                self.assertLogs("main", level="ERROR") as logs:
            from main import load_module
            self.assertIsNone(load_module("raw"))
            self.assertIn("dependency missing", " ".join(logs.output))

    def test_handler_returning_false_is_a_counted_failure(self):
        handler = Mock(side_effect=[False, True])
        module = SimpleNamespace(create_repository=handler)
        with patch("main.load_module", return_value=module), \
                patch("main.blob_store_exists", return_value=True), \
                self.assertLogs("main", level="ERROR"):
            self.assertEqual(
                provision_repositories(Mock(), "http://nexus", self.repos, False),
                (1, 1),
            )
        self.assertEqual(handler.call_count, 2)

    def test_handler_exception_is_counted_and_next_repository_runs(self):
        handler = Mock(side_effect=[ValueError("api failure"), True])
        with patch("main.load_module", return_value=SimpleNamespace(create_repository=handler)), \
                patch("main.blob_store_exists", return_value=True), \
                self.assertLogs("main", level="ERROR"):
            self.assertEqual(
                provision_repositories(Mock(), "http://nexus", self.repos, False),
                (1, 1),
            )
        self.assertEqual(handler.call_count, 2)

    def test_blob_lookup_exception_is_counted_without_creation(self):
        handler = Mock(return_value=True)
        with patch("main.load_module", return_value=SimpleNamespace(create_repository=handler)), \
                patch("main.blob_store_exists", side_effect=OSError("unavailable")), \
                self.assertLogs("main", level="ERROR"):
            self.assertEqual(
                provision_repositories(Mock(), "http://nexus", self.repos, False),
                (0, 2),
            )
        handler.assert_not_called()

    def test_dry_run_does_not_contact_nexus_for_valid_handler(self):
        handler = Mock(return_value=True)
        with patch("main.load_module", return_value=SimpleNamespace(create_repository=handler)), \
                patch("main.blob_store_exists") as blob_lookup:
            self.assertEqual(
                provision_repositories(Mock(), "http://nexus", self.repos, True),
                (2, 0),
            )
        handler.assert_not_called()
        blob_lookup.assert_not_called()


class BlobErrorHandlingTests(unittest.TestCase):
    def test_creation_exception_counts_as_failure_and_continues(self):
        blob_list = [{"name": "first"}, {"name": "second"}]
        with patch("blobs.create_blob_store", side_effect=[RuntimeError("failed"), True]) as create, \
                self.assertLogs("main", level="ERROR"):
            self.assertEqual(
                provision_blobs(Mock(), "http://nexus", blob_list, False),
                (1, 1),
            )
        self.assertEqual(create.call_count, 2)


class MainExitStatusTests(unittest.TestCase):
    def test_creation_failure_returns_nonzero(self):
        valid_config = {
            "nexus": {
                "url": "http://localhost:8081",
                "username": "user",
                "password": "pass",
            },
            "repositories": {"raw": [{"name": "first", "type": "hosted"}]},
        }
        handler = Mock(return_value=False)
        with patch("sys.argv", ["main.py", "--repos-only"]), \
                patch("main.load_config_from_dir", return_value=valid_config), \
                patch("main.build_session", return_value=Mock()), \
                patch("main.verify_connection", return_value=True), \
                patch("main.load_module", return_value=SimpleNamespace(create_repository=handler)), \
                patch("main.blob_store_exists", return_value=True), \
                self.assertLogs("main", level="ERROR") as logs:
            with self.assertRaises(SystemExit) as context:
                main()
            self.assertEqual(context.exception.code, 1)
            self.assertIn("Failed to provision raw repository", " ".join(logs.output))
        handler.assert_called_once()

    def test_missing_repository_handler_returns_nonzero_in_both_modes(self):
        valid_config = {
            "nexus": {
                "url": "http://localhost:8081",
                "username": "user",
                "password": "pass",
            },
            "repositories": {"raw": [{"name": "first", "type": "hosted"}]},
        }
        for dry_run in (False, True):
            cli_args = ["main.py", "--repos-only"] + (["--dry-run"] if dry_run else [])
            with self.subTest(dry_run=dry_run), \
                    patch("sys.argv", cli_args), \
                    patch("main.load_config_from_dir", return_value=valid_config), \
                    patch("main.build_session", return_value=Mock()), \
                    patch("main.verify_connection", return_value=True) as verify, \
                    patch("main.load_module", return_value=None), \
                    self.assertLogs("main", level="ERROR") as logs:
                with self.assertRaises(SystemExit) as context:
                    main()
                self.assertEqual(context.exception.code, 1)
                self.assertIn("1 repository/ies failed", " ".join(logs.output))
            if dry_run:
                verify.assert_not_called()
            else:
                verify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
