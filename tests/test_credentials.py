"""Regression tests for Nexus credential precedence and CLI log redaction."""

import io
import logging
import os
import unittest
from unittest.mock import Mock, patch

from main import (
    CredentialRedactingFormatter,
    configure_log_redaction,
    main,
    resolve_nexus_credentials,
)


class NexusCredentialTests(unittest.TestCase):
    def setUp(self):
        # Keep these tests independent of developer/CI machine credentials.
        env_patch = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def test_environment_only_credentials_are_valid_for_dry_run(self):
        config = {"nexus": {"url": "http://nexus.example.test"}}
        with patch.dict(os.environ, {
            "NEXUS_USERNAME": "ci-user", "NEXUS_PASSWORD": "ci-password",
        }), patch("sys.argv", ["main.py", "--dry-run"]), \
                patch("main.load_config_from_dir", return_value=config), \
                patch("main.build_session", return_value=Mock()) as build, \
                patch("main.verify_connection") as verify:
            main()

        sent = build.call_args.args[0]
        self.assertEqual(sent["username"], "ci-user")
        self.assertEqual(sent["password"], "ci-password")
        verify.assert_not_called()
        self.assertEqual(config, {"nexus": {"url": "http://nexus.example.test"}})

    def test_environment_credentials_are_used_for_live_connection(self):
        config = {"nexus": {"url": "http://nexus.example.test"}}
        with patch.dict(os.environ, {
            "NEXUS_USERNAME": "ci-user", "NEXUS_PASSWORD": "ci-password",
        }), patch("sys.argv", ["main.py"]), \
                patch("main.load_config_from_dir", return_value=config), \
                patch("main.build_session", return_value=Mock()) as build, \
                patch("main.verify_connection", return_value=True) as verify:
            main()

        sent = build.call_args.args[0]
        self.assertEqual(sent["username"], "ci-user")
        self.assertEqual(sent["password"], "ci-password")
        verify.assert_called_once()

    def test_environment_credentials_override_yaml(self):
        config = {"nexus": {
            "url": "http://nexus.example.test",
            "username": "yaml-user",
            "password": "yaml-password",
        }}
        with patch.dict(os.environ, {
            "NEXUS_USERNAME": "env-user", "NEXUS_PASSWORD": "env-password",
        }):
            resolved, secrets = resolve_nexus_credentials(config)
        self.assertEqual(resolved["nexus"]["username"], "env-user")
        self.assertEqual(resolved["nexus"]["password"], "env-password")
        self.assertEqual(
            set(secrets), {"yaml-user", "yaml-password", "env-user", "env-password"}
        )
        self.assertEqual(config["nexus"]["username"], "yaml-user")

    def test_partial_override_preserves_other_yaml_field(self):
        config = {"nexus": {"username": "yaml-user", "password": "yaml-password"}}
        with patch.dict(os.environ, {"NEXUS_PASSWORD": "env-password"}):
            resolved, _ = resolve_nexus_credentials(config)
        self.assertEqual(resolved["nexus"]["username"], "yaml-user")
        self.assertEqual(resolved["nexus"]["password"], "env-password")

    def test_yaml_only_credentials_remain_supported(self):
        config = {"nexus": {"username": "yaml-user", "password": "yaml-password"}}
        resolved, secrets = resolve_nexus_credentials(config)
        self.assertEqual(resolved, config)
        self.assertCountEqual(secrets, ["yaml-user", "yaml-password"])

    def test_empty_environment_password_fails_instead_of_falling_back(self):
        config = {"nexus": {
            "url": "http://nexus.example.test", "username": "user", "password": "fallback",
        }}
        with patch.dict(os.environ, {"NEXUS_PASSWORD": ""}), \
                patch("sys.argv", ["main.py", "--dry-run"]), \
                patch("main.load_config_from_dir", return_value=config), \
                patch("main.build_session") as build, \
                self.assertLogs("main", level="ERROR") as captured:
            with self.assertRaises(SystemExit) as error:
                main()
        self.assertEqual(error.exception.code, 1)
        build.assert_not_called()
        self.assertIn("nexus.password", " ".join(captured.output))
        self.assertNotIn("fallback", " ".join(captured.output))

    def test_empty_environment_username_is_rejected(self):
        config = {"nexus": {
            "url": "http://nexus.example.test", "username": "fallback", "password": "pass",
        }}
        with patch.dict(os.environ, {"NEXUS_USERNAME": ""}), \
                patch("sys.argv", ["main.py", "--dry-run"]), \
                patch("main.load_config_from_dir", return_value=config), \
                patch("main.build_session") as build, \
                self.assertLogs("main", level="ERROR") as captured:
            with self.assertRaises(SystemExit) as error:
                main()
        self.assertEqual(error.exception.code, 1)
        build.assert_not_called()
        self.assertIn("nexus.username", " ".join(captured.output))

    def test_missing_all_credentials_fails_before_session(self):
        config = {"nexus": {"url": "http://nexus.example.test"}}
        with patch("sys.argv", ["main.py", "--dry-run"]), \
                patch("main.load_config_from_dir", return_value=config), \
                patch("main.build_session") as build, \
                self.assertLogs("main", level="ERROR") as captured:
            with self.assertRaises(SystemExit) as error:
                main()
        self.assertEqual(error.exception.code, 1)
        build.assert_not_called()
        self.assertIn("nexus.username", " ".join(captured.output))
        self.assertIn("nexus.password", " ".join(captured.output))

    def test_invalid_nexus_mapping_is_unchanged(self):
        original = {"nexus": ["invalid"]}
        resolved, secrets = resolve_nexus_credentials(original)
        self.assertIs(resolved, original)
        self.assertEqual(secrets, [])


class CredentialLogRedactionTests(unittest.TestCase):
    def test_mask_yaml_and_overridden_environment_credentials_in_errors(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        previous_formatters = [(h, h.formatter) for h in root.handlers]
        try:
            config = {"nexus": {"username": "old-user-secret", "password": "old-pass-secret"}}
            with patch.dict(os.environ, {
                "NEXUS_USERNAME": "new-user-secret", "NEXUS_PASSWORD": "new-pass-secret",
            }):
                _, values = resolve_nexus_credentials(config)
            configure_log_redaction(values)
            try:
                raise RuntimeError("HTTP response: old-pass-secret new-pass-secret")
            except RuntimeError:
                logging.getLogger("main").exception(
                    "request failed for old-user-secret and new-user-secret"
                )
            output = stream.getvalue()
            for secret in values:
                self.assertNotIn(secret, output)
            self.assertIn("[REDACTED]", output)
            self.assertIn("RuntimeError", output)
            self.assertIn("ERROR", output)
        finally:
            for previous_handler, formatter in previous_formatters:
                previous_handler.setFormatter(formatter)
            root.removeHandler(handler)

    def test_log_redaction_reconfiguration_replaces_previous_values(self):
        fmt = logging.Formatter("%(message)s")
        redacted = CredentialRedactingFormatter(fmt, ["old-secret"])
        self.assertNotIn("old-secret", redacted.format(logging.makeLogRecord({"msg": "old-secret"})))
        self.assertEqual(
            CredentialRedactingFormatter(fmt, ["new-secret"]).format(
                logging.makeLogRecord({"msg": "new-secret"})
            ),
            "[REDACTED]",
        )


if __name__ == "__main__":
    unittest.main()
