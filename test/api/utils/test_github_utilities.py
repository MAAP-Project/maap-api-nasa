import unittest
from unittest.mock import patch

from api import settings
from api.utils import github_util


class TestAddGitlabCloneCredentials(unittest.TestCase):
    """Tests for the credential placeholder injected into algorithm repo URLs for the HySDS build."""

    def setUp(self):
        patches = [
            patch.object(settings, 'GITLAB_URL', 'https://repo.maap-project.org'),
            patch.object(settings, 'GITLAB_CLONE_USER', 'maap-api-svc'),
            patch.object(settings, 'GITLAB_CLONE_TOKEN_VAR', 'GITLAB_CLONE_TOKEN'),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_maap_gitlab_url_gets_placeholder(self):
        result = github_util.add_gitlab_clone_credentials(
            'https://repo.maap-project.org/soil-moisture/soil-moisture-dps.git')
        self.assertEqual(
            'https://maap-api-svc:${GITLAB_CLONE_TOKEN}@repo.maap-project.org/soil-moisture/soil-moisture-dps.git',
            result)

    def test_placeholder_never_contains_real_token(self):
        with patch.object(settings, 'GITLAB_TOKEN', 'real-secret'), \
             patch.object(settings, 'GITLAB_API_TOKEN', 'real-api-secret'):
            result = github_util.add_gitlab_clone_credentials('https://repo.maap-project.org/root/algo.git')
        self.assertNotIn('real-secret', result)
        self.assertIn('${GITLAB_CLONE_TOKEN}', result)

    def test_host_match_is_case_insensitive(self):
        result = github_util.add_gitlab_clone_credentials('https://Repo.MAAP-Project.org/root/algo.git')
        self.assertTrue(result.startswith('https://maap-api-svc:${GITLAB_CLONE_TOKEN}@'))

    def test_port_is_preserved(self):
        with patch.object(settings, 'GITLAB_URL', 'https://repo.maap-project.org:8443'):
            result = github_util.add_gitlab_clone_credentials('https://repo.maap-project.org:8443/root/algo.git')
        self.assertEqual('https://maap-api-svc:${GITLAB_CLONE_TOKEN}@repo.maap-project.org:8443/root/algo.git',
                         result)

    def test_external_repo_is_unchanged(self):
        for url in ('https://gitlab.com/geospec/hytools.git',
                    'https://github.com/MAAP-Project/dps-unit-test.git',
                    'https://repo.dit.maap-project.org/root/algo.git'):
            self.assertEqual(url, github_util.add_gitlab_clone_credentials(url))

    def test_url_with_existing_credentials_is_unchanged(self):
        url = 'https://someone:abc123@repo.maap-project.org/root/algo.git'
        self.assertEqual(url, github_util.add_gitlab_clone_credentials(url))

    def test_non_http_and_empty_urls_are_unchanged(self):
        for url in ('git@repo.maap-project.org:root/algo.git', 'ssh://git@repo.maap-project.org/root/algo.git', '', None):
            self.assertEqual(url, github_util.add_gitlab_clone_credentials(url))

    def test_configurable_user_and_var_name(self):
        with patch.object(settings, 'GITLAB_CLONE_USER', 'dps-bot'), \
             patch.object(settings, 'GITLAB_CLONE_TOKEN_VAR', 'DPS_BOT_TOKEN'):
            result = github_util.add_gitlab_clone_credentials('https://repo.maap-project.org/root/algo.git')
        self.assertEqual('https://dps-bot:${DPS_BOT_TOKEN}@repo.maap-project.org/root/algo.git', result)


if __name__ == '__main__':
    unittest.main()
