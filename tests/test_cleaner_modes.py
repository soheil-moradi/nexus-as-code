"""Preview and safety regression tests for selective, managed and full cleanup."""

import unittest
from unittest.mock import Mock, patch

from nexus_cleaner import CleanupError, main, plan_cleanup

BASE = "https://nexus.test"
CONFIG = {
    "nexus": {"url": BASE, "username": "demo-user", "password": "long-test-password"},
    "repositories": {"raw": [
        {"name": "managed", "type": "hosted"},
        {"name": "managed-group", "type": "group", "members": ["managed"]},
    ]},
    "blobs": [{"name": "managed-blob", "type": "file"}],
}
REPOSITORIES = [
    {"name": "managed", "type": "hosted", "format": "raw"},
    {"name": "unmanaged", "type": "hosted", "format": "raw"},
    {"name": "managed-group", "type": "group", "format": "raw"},
]
BLOBS = [{"name": "managed-blob"}, {"name": "default"}, {"name": "unmanaged-blob"}]


def reply(data):
    result = Mock()
    result.json.return_value = data
    result.raise_for_status.return_value = None
    return result


def make_session(repos=None, blobs=None, detail=None):
    session = Mock()
    session.get.side_effect = [
        reply(REPOSITORIES if repos is None else repos),
        reply(BLOBS if blobs is None else blobs),
        *[reply(item) for item in (detail or [])],
    ]
    return session


class CleanupModePlanTests(unittest.TestCase):
    def test_full_selects_unmanaged_resources_but_never_default(self):
        session = make_session(detail=[{"group": {"memberNames": ["managed"]}}])
        repositories, blobs = plan_cleanup(session, BASE, CONFIG, [], [], mode="all")
        self.assertEqual(repositories, ["managed-group", "managed", "unmanaged"])
        self.assertEqual(blobs, ["managed-blob", "unmanaged-blob"])
        session.delete.assert_not_called()

    def test_managed_selects_only_configured_and_existing_resources(self):
        session = make_session(detail=[
            {"storage": {"blobStoreName": "default"}},
        ])
        repositories, blobs = plan_cleanup(session, BASE, CONFIG, [], [], mode="managed")
        self.assertEqual(repositories, ["managed-group", "managed"])
        self.assertEqual(blobs, ["managed-blob"])
        session.delete.assert_not_called()

    def test_managed_missing_resources_are_skipped(self):
        session = make_session(
            repos=[{"name": "unmanaged", "type": "hosted", "format": "raw"}],
            blobs=[{"name": "default"}],
        )
        self.assertEqual(plan_cleanup(session, BASE, CONFIG, [], [], mode="managed"), ([], []))

    def test_managed_cannot_remove_blob_still_used_by_unmanaged_repository(self):
        session = make_session(detail=[{"storage": {"blobStoreName": "managed-blob"}}])
        with self.assertRaisesRegex(CleanupError, "still used"):
            plan_cleanup(session, BASE, CONFIG, [], [], mode="managed")
        session.delete.assert_not_called()

    def test_managed_cannot_remove_member_of_surviving_group(self):
        session = make_session(repos=[
            {"name": "managed", "type": "hosted", "format": "raw"},
            {"name": "external-group", "type": "group", "format": "raw"},
        ], blobs=[], detail=[{"group": {"memberNames": ["managed"]}}])
        with self.assertRaisesRegex(CleanupError, "surviving group"):
            plan_cleanup(session, BASE, CONFIG, [], [], mode="managed")

    def test_full_orders_nested_groups_before_their_members(self):
        repos = [
            {"name": "leaf", "type": "hosted", "format": "raw"},
            {"name": "child", "type": "group", "format": "raw"},
            {"name": "parent", "type": "group", "format": "raw"},
        ]
        session = make_session(repos=repos, blobs=[], detail=[
            {"group": {"memberNames": ["leaf"]}},  # child first in remote inventory
            {"group": {"memberNames": ["child"]}},
        ])
        selected, _ = plan_cleanup(session, BASE, CONFIG, [], [], mode="all")
        self.assertEqual(selected, ["parent", "child", "leaf"])

    def test_uninspectable_nested_group_fails_closed(self):
        repos = [
            {"name": "g1", "type": "group", "format": "raw"},
            {"name": "g2", "type": "group", "format": "raw"},
        ]
        session = make_session(repos=repos, blobs=[], detail=[{}, {}])
        with self.assertRaisesRegex(CleanupError, "Cannot inspect group"):
            plan_cleanup(session, BASE, CONFIG, [], [], mode="all")
        session.delete.assert_not_called()

    def test_cyclic_group_dependencies_fail_closed(self):
        repos = [
            {"name": "g1", "type": "group", "format": "raw"},
            {"name": "g2", "type": "group", "format": "raw"},
        ]
        session = make_session(repos=repos, blobs=[], detail=[
            {"group": {"memberNames": ["g2"]}},
            {"group": {"memberNames": ["g1"]}},
        ])
        with self.assertRaisesRegex(CleanupError, "cycle"):
            plan_cleanup(session, BASE, CONFIG, [], [], mode="all")

    def test_inventory_duplicate_names_fail_closed(self):
        session = make_session(repos=[REPOSITORIES[0], REPOSITORIES[0]])
        with self.assertRaisesRegex(CleanupError, "Duplicate names"):
            plan_cleanup(session, BASE, CONFIG, [], [], mode="all")
        session.delete.assert_not_called()

    def test_bulk_cannot_mix_named_resources(self):
        session = Mock()
        with self.assertRaisesRegex(CleanupError, "combined"):
            plan_cleanup(session, BASE, CONFIG, ["managed"], [], mode="all")
        session.get.assert_not_called()


class CleanupModeCLITests(unittest.TestCase):
    def test_no_bulk_apply_without_exact_confirmation(self):
        for mode in ("--managed", "--all"):
            for args in ([], ["--confirm-target", BASE], ["--confirm-phrase", "DELETE-ALL"]):
                with self.subTest(mode=mode, args=args), \
                     patch("nexus_cleaner.load_config_from_dir", return_value=CONFIG), \
                     patch("nexus_cleaner.build_session") as build:
                    self.assertEqual(main([mode, "--apply", *args]), 1)
                    build.assert_not_called()

    def test_wrong_bulk_phrase_fails_before_network(self):
        for mode, wrong in (("--all", "DELETE-MANAGED"), ("--managed", "DELETE-ALL")):
            with self.subTest(mode=mode), \
                 patch("nexus_cleaner.load_config_from_dir", return_value=CONFIG), \
                 patch("nexus_cleaner.build_session") as build:
                self.assertEqual(main([mode, "--apply", "--confirm-target", BASE,
                                       "--confirm-phrase", wrong]), 1)
                build.assert_not_called()

    def test_preview_has_no_deletes(self):
        session = make_session(repos=[REPOSITORIES[0]], blobs=[BLOBS[0], BLOBS[1]])
        with patch("nexus_cleaner.load_config_from_dir", return_value=CONFIG), \
             patch("nexus_cleaner.build_session", return_value=session), \
             patch("nexus_cleaner.verify_connection", return_value=True):
            self.assertEqual(main(["--all"]), 0)
        session.delete.assert_not_called()

    def test_full_apply_requires_all_confirmations_and_never_deletes_default(self):
        session = make_session(repos=[REPOSITORIES[0]], blobs=[BLOBS[0], BLOBS[1]])
        session.delete.return_value = reply({})
        with patch("nexus_cleaner.load_config_from_dir", return_value=CONFIG), \
             patch("nexus_cleaner.build_session", return_value=session), \
             patch("nexus_cleaner.verify_connection", return_value=True):
            result = main(["--all", "--apply", "--confirm-target", BASE,
                           "--confirm-phrase", "DELETE-ALL"])
        self.assertEqual(result, 0)
        self.assertEqual([call.args[0] for call in session.delete.call_args_list], [
            f"{BASE}/service/rest/v1/repositories/managed",
            f"{BASE}/service/rest/v1/blobstores/managed-blob",
        ])

    def test_managed_apply_never_deletes_unconfigured_resources(self):
        session = make_session(repos=[REPOSITORIES[0], REPOSITORIES[1]],
                               blobs=[BLOBS[0], BLOBS[1]], detail=[
                                   {"storage": {"blobStoreName": "default"}},
                               ])
        session.delete.return_value = reply({})
        with patch("nexus_cleaner.load_config_from_dir", return_value=CONFIG), \
             patch("nexus_cleaner.build_session", return_value=session), \
             patch("nexus_cleaner.verify_connection", return_value=True):
            result = main(["--managed", "--apply", "--confirm-target", BASE,
                           "--confirm-phrase", "DELETE-MANAGED"])
        self.assertEqual(result, 0)
        self.assertEqual([call.args[0] for call in session.delete.call_args_list], [
            f"{BASE}/service/rest/v1/repositories/managed",
            f"{BASE}/service/rest/v1/blobstores/managed-blob",
        ])

    def test_full_can_ignore_unrelated_invalid_repository_settings(self):
        config = {**CONFIG, "repositories": {"apt": "bad value"},
                  "blobs": [{"name": "x", "secret": "${ENV:UNSET_TEST_BLOB_SECRET}"}]}
        session = make_session(repos=[], blobs=[{"name": "default"}])
        with patch("nexus_cleaner.load_config_from_dir", return_value=config), \
             patch("nexus_cleaner.build_session", return_value=session), \
             patch("nexus_cleaner.verify_connection", return_value=True):
            self.assertEqual(main(["--all"]), 0)
        session.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
