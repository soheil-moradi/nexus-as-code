"""Regression tests for bounded HTTP, dependency ordering and APT payloads."""

import logging
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from config_secrets import resolve_environment_references
from config_validation import validate_config
from main import (
    FORMAT_MODULE_MAP,
    NexusSession,
    build_session,
    order_repository_definitions,
    provision_repositories,
    verify_connection,
)
from modules import apt


class EnvironmentValueTests(unittest.TestCase):
    def test_exact_env_references_resolve_deeply_without_mutation(self):
        config = {"nexus": {"password": "${ENV:NEXUS_SECRET}"},
                  "blobs": [{"secret_access_key": "${ENV:S3_SECRET}"}],
                  "repositories": {"apt": [{"signing_keypair": "${ENV:APT_PRIVATE_KEY}"}]}}
        with patch.dict(os.environ, {"NEXUS_SECRET": "pw1", "S3_SECRET": "s3secret",
                                     "APT_PRIVATE_KEY": "gpgsecret"}):
            result, secrets = resolve_environment_references(config)
        self.assertEqual(result["nexus"]["password"], "pw1")
        self.assertEqual(result["blobs"][0]["secret_access_key"], "s3secret")
        self.assertEqual(result["repositories"]["apt"][0]["signing_keypair"], "gpgsecret")
        self.assertEqual(config["nexus"]["password"], "${ENV:NEXUS_SECRET}")
        self.assertIn("s3secret", secrets)
        self.assertIn("gpgsecret", secrets)

    def test_missing_environment_variable_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "configuration.blobs\\[0\\]"):
                resolve_environment_references({"blobs": [{"access_key_id": "${ENV:NOT_PRESENT}"}]})

    def test_embedded_expansion_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact"):
            resolve_environment_references({"key": "prefix-${ENV:HOME}"})


class HttpSafetyTests(unittest.TestCase):
    def test_default_timeouts_apply_to_all_methods(self):
        with patch.object(requests.Session, "request", return_value=Mock()) as request:
            session = NexusSession()
            session.get("https://example.test/test")
            self.assertEqual(request.call_args.kwargs["timeout"], (5, 30))
            session.post("https://example.test/test", json={"x": 1})
            self.assertEqual(request.call_args.kwargs["timeout"], (5, 30))
            session.delete("https://example.test/test", timeout=8)
            self.assertEqual(request.call_args.kwargs["timeout"], 8)

    def test_only_safe_reads_are_retried(self):
        session = build_session({"username": "u", "password": "p"})
        try:
            adapter = session.get_adapter("https://example.test")
            self.assertIn("GET", adapter.max_retries.allowed_methods)
            self.assertNotIn("POST", adapter.max_retries.allowed_methods)
            self.assertNotIn("DELETE", adapter.max_retries.allowed_methods)
            self.assertEqual(adapter.max_retries.total, 2)
        finally:
            session.close()

    def test_timeout_produces_failed_connectivity_check(self):
        session = Mock()
        session.get.side_effect = requests.Timeout("network unavailable")
        with self.assertLogs("main", level="ERROR") as captured:
            self.assertFalse(verify_connection(session, "https://nexus.test"))
        self.assertIn("Cannot reach Nexus", " ".join(captured.output))


class RepositoryOrderTests(unittest.TestCase):
    def test_groups_are_ordered_after_local_members_and_nested_groups(self):
        repos = {"raw": [
            {"name": "top", "type": "group", "members": ["mid"]},
            {"name": "mid", "type": "group", "members": ["child"]},
            {"name": "child", "type": "hosted"},
        ]}
        self.assertEqual([r["name"] for r in order_repository_definitions(repos)["raw"]],
                         ["child", "mid", "top"])

    def test_group_failure_prevents_dependent_creation(self):
        created = Mock(side_effect=[False, True])
        handler = SimpleNamespace(create_repository=created)
        repos = {"raw": [
            {"name": "all", "type": "group", "members": ["child"]},
            {"name": "child", "type": "hosted"},
        ]}
        with patch("main.load_module", return_value=handler), \
             patch("main.blob_store_exists", return_value=True), \
             self.assertLogs("main", level="ERROR"):
            self.assertEqual(provision_repositories(Mock(), "http://nexus", repos, False), (0, 2))
        self.assertEqual(created.call_count, 1)

    def test_blob_inventory_checks_are_reused_within_provisioning(self):
        handler = SimpleNamespace(create_repository=Mock(return_value=True))
        repos = {"raw": [{"name": "a", "type": "hosted", "blob_store": "b"},
                         {"name": "b", "type": "hosted", "blob_store": "b"}]}
        with patch("main.load_module", return_value=handler), \
             patch("main.blob_store_exists", return_value=True) as lookup:
            self.assertEqual(provision_repositories(Mock(), "http://nexus", repos, False), (2, 0))
        lookup.assert_called_once()


class AptSafetyTests(unittest.TestCase):
    def test_proxy_without_distribution_does_not_fall_back_to_bionic(self):
        session = Mock()
        session.get.return_value.json.return_value = []
        session.post.return_value.status_code = 201
        repo = {"name": "ubuntu", "type": "proxy", "remote_url": "https://archive.ubuntu.com/ubuntu"}
        self.assertTrue(apt.create_repository(session, "https://nexus.test", repo))
        self.assertEqual(session.post.call_args.kwargs["json"]["apt"]["distribution"], "")
        self.assertFalse(session.post.call_args.kwargs["json"]["apt"]["enforceDistribution"])

    def test_proxy_with_explicit_distribution_keeps_it(self):
        session = Mock()
        session.get.return_value.json.return_value = []
        session.post.return_value.status_code = 201
        repo = {"name": "ubuntu", "type": "proxy", "remote_url": "https://archive.ubuntu.com/ubuntu",
                "distribution": "noble"}
        self.assertTrue(apt.create_repository(session, "https://nexus.test", repo))
        self.assertEqual(session.post.call_args.kwargs["json"]["apt"]["distribution"], "noble")

    def test_enforce_distribution_requires_configured_suite(self):
        config = {"nexus": {"url": "https://nexus.test", "username": "u", "password": "p"},
                  "repositories": {"apt": [{"name": "remote", "type": "proxy",
                                           "remote_url": "https://example.test/repo",
                                           "enforce_distribution": True}]}}
        errors = " ".join(validate_config(config, FORMAT_MODULE_MAP))
        self.assertIn("enforce_distribution", errors)

    def test_apt_hosted_requires_explicit_distribution_and_signing_key(self):
        config = {"nexus": {"url": "https://nexus.test", "username": "u", "password": "p"},
                  "repositories": {"apt": [{"name": "local", "type": "hosted"}]}}
        errors = " ".join(validate_config(config, FORMAT_MODULE_MAP))
        self.assertIn(".distribution", errors)
        self.assertIn(".signing_keypair", errors)

    def test_http_error_does_not_log_untrusted_response_text(self):
        session = Mock()
        session.get.return_value.json.return_value = []
        session.post.return_value.status_code = 400
        session.post.return_value.text = "secret reflected by server"
        repo = {"name": "ubuntu", "type": "proxy", "remote_url": "https://example.test"}
        with self.assertLogs("modules.apt", level="ERROR") as logs:
            self.assertFalse(apt.create_repository(session, "https://nexus.test", repo))
        self.assertNotIn("secret reflected by server", " ".join(logs.output))


class ConfigurationGraphTests(unittest.TestCase):
    def setUp(self):
        self.config = {"nexus": {"url": "https://nexus.test", "username": "u", "password": "p"}}

    def test_group_self_reference_rejected(self):
        self.config["repositories"] = {"raw": [{"name": "all", "type": "group", "members": ["all"]}]}
        self.assertIn("self-reference", " ".join(validate_config(self.config, FORMAT_MODULE_MAP)))

    def test_group_cycle_rejected(self):
        self.config["repositories"] = {"raw": [
            {"name": "a", "type": "group", "members": ["b"]},
            {"name": "b", "type": "group", "members": ["a"]},
        ]}
        self.assertIn("cyclic", " ".join(validate_config(self.config, FORMAT_MODULE_MAP)))

    def test_group_cross_format_member_rejected(self):
        self.config["repositories"] = {"raw": [{"name": "all", "type": "group", "members": ["other"]}],
                                       "npm": [{"name": "other", "type": "hosted"}]}
        self.assertIn("another format", " ".join(validate_config(self.config, FORMAT_MODULE_MAP)))

    def test_boolean_fields_reject_strings(self):
        self.config["repositories"] = {"raw": [{"name": "one", "type": "hosted", "online": "yes"}]}
        self.assertIn("boolean", " ".join(validate_config(self.config, FORMAT_MODULE_MAP)))


if __name__ == "__main__":
    unittest.main()
