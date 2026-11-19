import unittest
from unittest.mock import patch

from api import settings
from api.utils import hysds_util, output_target
from api.utils.output_target import OutputTargetError, normalize_prefix, resolve_output_target

USER = "jane"
WORKSPACE = "maap-ops-workspace"
ORG = "nasa-maap-org"


def grant(prefix=None, readonly=False, bucket=ORG):
    return {"bucket_name": bucket, "bucket_prefix": prefix, "readonly": readonly}


class TestNormalizePrefix(unittest.TestCase):

    def test_strips_and_collapses_slashes(self):
        self.assertEqual(normalize_prefix("/team//jane/"), "team/jane")

    def test_rejects_bad_values(self):
        for bad in ["", "/", "//", "a/../b", "./a", "a/.", "a\nb", "a\x7fb", " a/ b", 5, None]:
            with self.subTest(bad=bad), self.assertRaises(OutputTargetError) as ctx:
                normalize_prefix(bad)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_caps_length(self):
        normalize_prefix("a" * output_target.MAX_PREFIX_LENGTH)
        with self.assertRaises(OutputTargetError):
            normalize_prefix("a" * (output_target.MAX_PREFIX_LENGTH + 1))


@patch.object(settings, "WORKSPACE_BUCKET", WORKSPACE)
class TestResolveOutputTarget(unittest.TestCase):

    def resolve(self, grants, bucket=None, prefix=None):
        with patch.object(output_target.s3_access, "get_user_s3_access", return_value=grants) as m:
            result = resolve_output_target(1, USER, bucket, prefix)
        return result, m

    def assert_rejected(self, grants, bucket, prefix, status, match=None):
        with self.assertRaises(OutputTargetError) as ctx:
            self.resolve(grants, bucket, prefix)
        self.assertEqual(ctx.exception.status_code, status)
        if match:
            self.assertIn(match, str(ctx.exception))

    def test_no_bucket_is_default_and_skips_db(self):
        for empty in [None, "", "  "]:
            result, m = self.resolve([], empty, None)
            self.assertIsNone(result)
            m.assert_not_called()

    def test_prefix_without_bucket_rejected(self):
        self.assert_rejected([], None, "team", 400, "requires output_bucket")

    def test_invalid_bucket_rejected(self):
        for bad in ["s3://x-bucket", "UPPER", "ab", "a/b-c", 7]:
            with self.subTest(bad=bad):
                self.assert_rejected([grant()], bad, None, 400)

    def test_bucket_wide_grant_defaults_prefix_to_username(self):
        self.assertEqual(self.resolve([grant()], ORG)[0], (ORG, USER))

    def test_prefix_is_normalized(self):
        self.assertEqual(self.resolve([grant()], ORG, "/team//x/")[0], (ORG, "team/x"))

    def test_prefix_grant_exact_and_child(self):
        self.assertEqual(self.resolve([grant("team")], ORG, "team")[0], (ORG, "team"))
        self.assertEqual(self.resolve([grant("team/")], ORG, "team/jane")[0], (ORG, "team/jane"))

    def test_prefix_grant_is_segment_bounded(self):
        self.assert_rejected([grant("team")], ORG, "teammate", 403, "not permitted")

    def test_prefix_grant_without_prefix_asks_for_one(self):
        self.assert_rejected([grant("team")], ORG, None, 403, "set output_prefix")

    def test_readonly_grant_has_distinct_message(self):
        self.assert_rejected([grant(readonly=True)], ORG, None, 403, "read-only")

    def test_any_writable_covering_grant_wins(self):
        grants = [grant(readonly=True), grant("team", readonly=False)]
        self.assertEqual(self.resolve(grants, ORG, "team/a")[0], (ORG, "team/a"))

    def test_other_bucket_grant_does_not_count(self):
        self.assert_rejected([grant(bucket="other-bucket")], ORG, None, 403, "not permitted")

    def test_workspace_bucket_with_default_prefix_is_default(self):
        for prefix in [None, USER, f"/{USER}/"]:
            self.assertIsNone(self.resolve([], WORKSPACE, prefix)[0])

    def test_workspace_bucket_custom_prefix_rejected(self):
        self.assert_rejected([], WORKSPACE, "elsewhere", 403, "default bucket")


@patch.object(settings, "WORKSPACE_BUCKET", WORKSPACE)
class TestApplyOutputTarget(unittest.TestCase):

    def test_strips_unvalidated_values_for_default_target(self):
        params = {"username": USER, "x": 1, "output_bucket": ORG, "output_prefix": "p"}
        output_target.apply_output_target(params, 1, USER, None, None)
        self.assertEqual(params, {"username": USER, "x": 1})

    def test_sets_resolved_values(self):
        params = {"output_bucket": "sneaky-bucket"}
        with patch.object(output_target.s3_access, "get_user_s3_access", return_value=[grant()]):
            output_target.apply_output_target(params, 1, USER, ORG, None)
        self.assertEqual(params, {"output_bucket": ORG, "output_prefix": USER})

    def test_rejection_propagates(self):
        with patch.object(output_target.s3_access, "get_user_s3_access", return_value=[]), \
                self.assertRaises(OutputTargetError):
            output_target.apply_output_target({}, 1, USER, ORG, None)


class TestSpecBuilders(unittest.TestCase):
    INPUTS = {"config": [{"name": "alpha", "data_type": "text"}], "positional": [], "file": []}

    def test_hysds_io_declares_optional_output_target(self):
        io = hysds_util.create_hysds_io("desc", self.INPUTS)
        by_name = {p["name"]: p for p in io["params"]}
        for name in ("output_bucket", "output_prefix"):
            self.assertEqual(by_name[name], {"name": name, "from": "submitter", "type": "text", "optional": True})
        self.assertIn("alpha", by_name)

    def test_job_spec_routes_output_target_to_context(self):
        spec = hysds_util.create_job_spec("run.sh", self.INPUTS, "10GB", "q")
        by_name = {p["name"]: p for p in spec["params"]}
        for name in ("output_bucket", "output_prefix"):
            self.assertEqual(by_name[name], {"name": name, "destination": "context"})

    def test_algorithm_input_with_same_name_is_not_duplicated(self):
        inputs = {"config": [{"name": "output_bucket", "data_type": "text"}]}
        names = [p["name"] for p in hysds_util.create_job_spec("run.sh", inputs, "10GB", "q")["params"]]
        self.assertEqual(names.count("output_bucket"), 1)


@patch.object(settings, "WORKSPACE_BUCKET", WORKSPACE)
class TestAddProductPath(unittest.TestCase):

    @staticmethod
    def response(urls):
        return {"result": {"job": {"job_info": {"metrics": {"products_staged": [{"urls": urls}]}}}}}

    @staticmethod
    def path(resp):
        return resp["result"]["job"]["job_info"]["metrics"]["products_staged"][0]["product_folder_path"]

    def test_workspace_bucket_keeps_private_mount(self):
        url = f"s3://s3-us-west-2.amazonaws.com:80/{WORKSPACE}/{USER}/dps_output/algo/main/2026/11/19"
        self.assertEqual(self.path(hysds_util.add_product_path(self.response([url]))),
                         f"{settings.WORKSPACE_MOUNT_PRIVATE}/dps_output/algo/main/2026/11/19")

    def test_org_bucket_maps_to_org_mount(self):
        url = f"s3://s3-us-west-2.amazonaws.com:80/{ORG}/team/x/dps_output/algo/main/2026/11/19"
        self.assertEqual(self.path(hysds_util.add_product_path(self.response([url]))),
                         f"{settings.WORKSPACE_MOUNT_ORG_BUCKETS}/{ORG}/team/x/dps_output/algo/main/2026/11/19")


if __name__ == "__main__":
    unittest.main()
