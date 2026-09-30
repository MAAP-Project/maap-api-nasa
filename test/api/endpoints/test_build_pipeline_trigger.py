import unittest
from unittest.mock import patch, MagicMock

from api import settings
from api.maapapp import app
from api.endpoints.build import _trigger_build_pipeline


class TestTriggerBuildPipelineRepositoryUrl(unittest.TestCase):
    """Tests that the build pipeline receives a credentialed REPOSITORY_URL for MAAP GitLab repos."""

    def setUp(self):
        patches = [
            patch.object(settings, 'GITLAB_URL', 'https://repo.maap-project.org'),
            patch.object(settings, 'GITLAB_CLONE_USER', 'maap-api-svc'),
            patch.object(settings, 'GITLAB_CLONE_TOKEN_VAR', 'GITLAB_CLONE_TOKEN'),
            patch.object(settings, 'GITLAB_BUILD_APP_PACK_PROJECT_ID', '42'),
            patch.object(settings, 'GITLAB_OGC_APP_PACK_PROJECT_ID', '43'),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _trigger(self, code_repository):
        payload = {
            "code_repository": code_repository,
            "algorithm_name": "algo",
            "algorithm_version": "1.0",
        }
        with patch('api.endpoints.build.gitlab.Gitlab') as mock_gitlab:
            project = mock_gitlab.return_value.projects.get.return_value
            project.pipelines.create.return_value = MagicMock(id=1, web_url='u', status='pending', ref='main')
            with app.app_context():
                _trigger_build_pipeline(payload, "user")
            variables = project.pipelines.create.call_args[0][0]["variables"]
        return {v["key"]: v["value"] for v in variables}

    def test_maap_gitlab_repo_gets_credential_placeholder(self):
        variables = self._trigger('https://repo.maap-project.org/soil-moisture/soil-moisture-dps.git')
        self.assertEqual(
            'https://maap-api-svc:${GITLAB_CLONE_TOKEN}@repo.maap-project.org/soil-moisture/soil-moisture-dps.git',
            variables["REPOSITORY_URL"])

    def test_external_repo_is_passed_through(self):
        url = 'https://github.com/MAAP-Project/sardem-sarsen.git'
        variables = self._trigger(url)
        self.assertEqual(url, variables["REPOSITORY_URL"])

    def test_real_token_is_not_sent_to_pipeline(self):
        with patch.object(settings, 'GITLAB_TOKEN', 'real-secret'):
            variables = self._trigger('https://repo.maap-project.org/root/algo.git')
        self.assertNotIn('real-secret', variables["REPOSITORY_URL"])


if __name__ == '__main__':
    unittest.main()
