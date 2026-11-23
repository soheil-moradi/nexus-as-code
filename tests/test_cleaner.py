"""Cleanup must be explicit, scoped and non-destructive by default."""

import unittest
from unittest.mock import Mock, patch

from nexus_cleaner import CleanupError, execute_cleanup, main, plan_cleanup

BASE = "https://nexus.test"
CONFIG = {
    "nexus": {"url": BASE, "username": "u", "password": "p"},
    "repositories": {"raw": [{"name": "owned", "type": "hosted"}]},
    "blobs": [{"name": "storage", "type": "file"}],
}


def response(items):
    result = Mock()
    result.json.return_value = items
    result.status_code = 200
    return result


class CleanerTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.repos = [{"name": "owned", "type": "hosted", "format": "raw"},
                      {"name": "not-ours", "type": "hosted", "format": "raw"}]

    def inventory(self, blob_users=None):
        self.session.get.side_effect = [
            response(self.repos),
            response([{"name": "storage"}, {"name": "default"}]),
            response({"storage": {"blobStoreName": blob_users or "default"}}),
        ]

    def test_unselected_resources_are_never_targeted(self):
        self.inventory()
        selected_repos, selected_blobs = plan_cleanup(
            self.session, BASE, CONFIG, ["owned"], ["storage"]
        )
        self.assertEqual(selected_repos, ["owned"])
        self.assertEqual(selected_blobs, ["storage"])
        self.session.delete.assert_not_called()

    def test_unmanaged_repository_cannot_be_deleted(self):
        with self.assertRaisesRegex(CleanupError, "defined in local"):
            plan_cleanup(self.session, BASE, CONFIG, ["not-ours"], [])
        self.session.get.assert_not_called()

    def test_default_blob_store_is_protected(self):
        with self.assertRaisesRegex(CleanupError, "default"):
            plan_cleanup(self.session, BASE, CONFIG, [], ["default"])

    def test_referenced_blob_store_is_protected(self):
        self.inventory(blob_users="storage")
        with self.assertRaisesRegex(CleanupError, "still used"):
            plan_cleanup(self.session, BASE, CONFIG, ["owned"], ["storage"])
        self.session.delete.assert_not_called()

    def test_uninspectable_surviving_repository_fails_closed(self):
        self.session.get.side_effect = [
            response(self.repos), response([{"name": "storage"}]), response({})]
        with self.assertRaisesRegex(CleanupError, "Cannot verify"):
            plan_cleanup(self.session, BASE, CONFIG, ["owned"], ["storage"])

    def test_deletion_only_targets_selected_names_in_order(self):
        self.session.delete.return_value = response({})
        execute_cleanup(self.session, BASE, ["owned"], ["storage"])
        urls = [call.args[0] for call in self.session.delete.call_args_list]
        self.assertEqual(urls, [f"{BASE}/service/rest/v1/repositories/owned",
                                f"{BASE}/service/rest/v1/blobstores/storage"])

    def test_plan_is_non_destructive_even_with_valid_inventory(self):
        self.session.get.side_effect = [response(self.repos), response([{"name": "storage"}])]
        with patch("nexus_cleaner.load_config_from_dir", return_value=CONFIG), \
             patch("nexus_cleaner.build_session", return_value=self.session), \
             patch("nexus_cleaner.verify_connection", return_value=True):
            self.assertEqual(main(["--repository", "owned"]), 0)
        self.session.delete.assert_not_called()

    def test_apply_without_exact_target_fails_before_network_calls(self):
        with patch("nexus_cleaner.load_config_from_dir", return_value=CONFIG), \
             patch("nexus_cleaner.build_session") as build:
            self.assertEqual(main(["--repository", "owned", "--apply"]), 1)
        build.assert_not_called()

    def test_apply_with_wrong_target_fails_before_network_calls(self):
        with patch("nexus_cleaner.load_config_from_dir", return_value=CONFIG), \
             patch("nexus_cleaner.build_session") as build:
            self.assertEqual(main(["--repository", "owned", "--apply",
                                   "--confirm-target", "https://other.test"]), 1)
        build.assert_not_called()


if __name__ == "__main__":
    unittest.main()

class GroupCleanupTests(unittest.TestCase):
    def test_cannot_delete_member_of_surviving_group(self):
        session = Mock()
        session.get.side_effect = [
            response([{"name": "owned", "type": "hosted", "format": "raw"},
                      {"name": "survivor", "type": "group", "format": "raw"}]),
            response([]),
            response({"group": {"memberNames": ["owned"]}}),
        ]
        with self.assertRaisesRegex(CleanupError, "surviving group"):
            plan_cleanup(session, BASE, CONFIG, ["owned"], [])
        session.delete.assert_not_called()

    def test_deleting_group_before_selected_member(self):
        session = Mock()
        config = {"repositories": {"raw": [
            {"name": "owned", "type": "hosted"},
            {"name": "owned-group", "type": "group"}]}}
        session.get.side_effect = [
            response([{"name": "owned", "type": "hosted", "format": "raw"},
                      {"name": "owned-group", "type": "group", "format": "raw"}]),
            response([]),
        ]
        ordered, _ = plan_cleanup(session, BASE, config, ["owned", "owned-group"], [])
        self.assertEqual(ordered, ["owned-group", "owned"])
