import json
import unittest
from unittest.mock import patch

from api.utils import s3_access


BUCKET = "maap-ops-workspace"
USER = "jane_doe"


class TestBuildUserS3Policy(unittest.TestCase):
    """Tests for the STS session policy built for /self/awsAccess/workspaceBucket."""

    def _build(self, org_access=None):
        with patch.object(s3_access, 'get_user_s3_access', return_value=org_access or []):
            policy_json, paths = s3_access.build_user_s3_policy(BUCKET, USER, 1)
        return json.loads(policy_json), paths, policy_json

    @staticmethod
    def _statement(policy, actions, resource=None):
        """Find the single statement with the given action set (and optional resource)."""
        matches = [
            s for s in policy["Statement"]
            if sorted(s["Action"]) == sorted(actions)
            and (resource is None or s["Resource"] == resource)
        ]
        assert len(matches) == 1, f"expected one statement for {actions}, got {len(matches)}"
        return matches[0]

    RW = ["s3:*"]
    RO = ["s3:ListBucket", "s3:GetObject"]
    LIST = ["s3:ListBucket"]

    def test_workspace_entry_is_first(self):
        _, paths, _ = self._build()
        self.assertEqual(paths[0], {
            "bucket": BUCKET,
            "prefix": USER,
            "uri": f"s3://{BUCKET}/{USER}",
            "type": "workspace",
            "access": "read_write",
        })

    def test_default_workspace_paths_are_listed(self):
        _, paths, _ = self._build()
        by_prefix = {p["prefix"]: p for p in paths}
        self.assertEqual(by_prefix[f"shared/{USER}"]["access"], "read_write")
        self.assertEqual(by_prefix[f"shared/{USER}"]["type"], "shared")
        self.assertEqual(by_prefix["shared"]["access"], "read_only")
        self.assertEqual(by_prefix["shared"]["type"], "shared_root")
        self.assertEqual(by_prefix["dataset/triaged_job"]["access"], "read_only")
        self.assertEqual(by_prefix["dataset/triaged_job"]["type"], "triaged_jobs")
        self.assertEqual(len(paths), 4)

    def test_policy_grants_rw_to_private_and_shared_user_folders(self):
        policy, _, _ = self._build()
        rw = self._statement(policy, self.RW)
        self.assertCountEqual(rw["Resource"], [
            f"arn:aws:s3:::{BUCKET}/{USER}/*",
            f"arn:aws:s3:::{BUCKET}/shared/{USER}/*",
        ])

    def test_policy_grants_ro_to_shared_root_and_triaged_jobs(self):
        policy, _, _ = self._build()
        ro = self._statement(policy, self.RO)
        self.assertCountEqual(ro["Resource"], [
            f"arn:aws:s3:::{BUCKET}/shared/*",
            f"arn:aws:s3:::{BUCKET}/dataset/triaged_job/*",
        ])

    def test_policy_allows_listing_all_default_prefixes(self):
        policy, _, _ = self._build()
        listing = self._statement(policy, self.LIST, resource=f"arn:aws:s3:::{BUCKET}")
        # "shared/*" already covers "shared/{USER}/*", so no separate condition is emitted.
        self.assertCountEqual(listing["Condition"]["StringLike"]["s3:prefix"], [
            f"{USER}/*",
            "shared/*",
            "dataset/triaged_job/*",
        ])
        # Only the prefixed ListBucket statement exists; no unconditioned bucket listing.
        self.assertEqual(len([s for s in policy["Statement"] if s["Action"] == self.LIST]), 1)

    def test_org_access_is_appended_after_default_paths(self):
        policy, paths, _ = self._build(org_access=[
            {"bucket_name": "team-bucket", "bucket_prefix": "data", "readonly": True},
            {"bucket_name": "other-bucket", "bucket_prefix": "", "readonly": False},
        ])
        self.assertEqual([p["type"] for p in paths],
                         ["workspace", "shared", "shared_root", "triaged_jobs", "org", "org"])
        ro = self._statement(policy, self.RO)
        self.assertIn("arn:aws:s3:::team-bucket/data/*", ro["Resource"])
        rw = self._statement(policy, self.RW)
        self.assertIn("arn:aws:s3:::other-bucket/*", rw["Resource"])
        plain = self._statement(policy, self.LIST, resource=["arn:aws:s3:::other-bucket"])
        self.assertEqual(plain["Resource"], ["arn:aws:s3:::other-bucket"])

    def test_statements_have_no_sid(self):
        policy, _, _ = self._build(org_access=[
            {"bucket_name": "other-bucket", "bucket_prefix": "", "readonly": False},
        ])
        self.assertTrue(policy["Statement"])
        for statement in policy["Statement"]:
            self.assertNotIn("Sid", statement)

    def test_policy_stays_under_sts_size_cap(self):
        # STS rejects inline session policies over 2048 chars. Guard the headroom
        # left for org grants after the built-in workspace paths are included.
        org_access = [
            {"bucket_name": f"org-bucket-{i}", "bucket_prefix": f"prefix-{i}", "readonly": i % 2 == 0}
            for i in range(8)
        ]
        _, _, policy_json = self._build(org_access=org_access)
        self.assertLessEqual(len(policy_json), 2048)


if __name__ == '__main__':
    unittest.main()
