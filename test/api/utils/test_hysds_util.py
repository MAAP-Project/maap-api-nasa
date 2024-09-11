import unittest
from unittest.mock import Mock, patch
from api.utils import hysds_util, job_queue
from api import settings
import copy
from requests import Session
import json


def mock_session_get(*args, **kwargs):
    class MockResponse:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

    return MockResponse({}, 200)


class TestHySDSUtils(unittest.TestCase):

    def setUp(self):
        pass

    @patch('requests.Session.get', side_effect=mock_session_get)
    def test_get_mozart_job_info(self, mock_session_get):
        hysds_util.get_mozart_job_info("someid")
        mock_session_get.assert_called_with("{}/job/info".format(settings.MOZART_URL), params={"id": "someid"})

    def test_remove_double_tag(self):
        mozart_response = {"result": {"tags": ["duplicate", "duplicate"]}}
        resp = hysds_util.remove_double_tag(mozart_response)
        self.assertEqual({"result": {"tags": ["duplicate"]}}, resp)
        self.assertNotEqual({"result": {"tags": ["duplicate", "duplicate"]}}, resp)
        mozart_response = {"result": {}}
        resp = hysds_util.remove_double_tag(mozart_response)
        self.assertEqual({"result": {}}, resp)

    def test_add_product_path(self):
        self.fail()

    @patch('api.utils.hysds_util.get_recommended_queue')
    @patch('api.utils.hysds_util.get_mozart_queues')
    def test_validate_queue(self, mock_get_mozart_queues, mock_get_recommended_queue):
        mock_get_recommended_queue.return_value = "maap-dps-worker-8gb"
        mock_get_mozart_queues.return_value = ["maap-dps-worker-8gb", "maap-dps-worker-16gb"]
        queue = "maap-dps-worker-16gb"
        job_type = "dummy-job"
        user_id = 1
        new_queue = job_queue.validate_or_get_queue(queue, job_type, user_id)
        self.assertEqual(queue, new_queue.queue_name)
        mock_get_mozart_queues.assert_called()
        new_queue = job_queue.validate_or_get_queue("", job_type, user_id)
        self.assertEqual("maap-dps-worker-8gb", new_queue.queue_name)
        mock_get_recommended_queue.assert_called_with("dummy-job")
        with self.assertRaises(ValueError):
            job_queue.validate_or_get_queue("invalid_queue", job_type, user_id)

    def test_set_time_limits(self):
        params = {"input": "in1", "username": "user"}
        expected_params = copy.deepcopy(params)
        expected_params.update({"soft_time_limit": "6000", "time_limit": "6000"})
        hysds_util.set_timelimit_for_dps_sandbox(params)
        self.assertEqual(expected_params, params)
