import pytest
from unittest.mock import Mock, patch
from app.services.webhook_service import WebhookService


class TestWebhookService:
    @patch('app.services.webhook_service.CloudTasksClient')
    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_queued_job_with_matching_label(self, mock_gh_client_class, mock_gc_client_class, mock_ct_client_class):
        """Test handling queued job enqueues a Cloud Tasks task."""
        mock_ct_client = Mock()
        mock_ct_client_class.return_value = mock_ct_client

        service = WebhookService()

        payload = {
            'action': 'queued',
            'workflow_job': {
                'labels': ['gcp-ubuntu-24.04', 'linux']
            },
            'repository': {
                'html_url': 'https://github.com/owner/repo',
                'full_name': 'owner/repo'
            }
        }

        service.handle_workflow_job(payload, base_url='https://example.run.app')

        mock_ct_client.enqueue_create_runner.assert_called_once_with(
            'https://example.run.app',
            {
                'template_name': 'gcp-ubuntu-24.04',
                'repo_url': 'https://github.com/owner/repo',
                'repo_owner_url': None,
                'repo_name': 'owner/repo',
                'org_name': None,
            }
        )

    @patch('app.services.webhook_service.CloudTasksClient')
    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_queued_job_for_org(self, mock_gh_client_class, mock_gc_client_class, mock_ct_client_class):
        """Test handling queued job for organization enqueues task."""
        mock_ct_client = Mock()
        mock_ct_client_class.return_value = mock_ct_client

        service = WebhookService()

        payload = {
            'action': 'queued',
            'workflow_job': {
                'labels': ['gcp-ubuntu-24.04']
            },
            'organization': {
                'login': 'my-org'
            },
            'repository': {
                'html_url': 'https://github.com/my-org/repo',
                'full_name': 'my-org/repo',
                'owner': {
                    'html_url': 'https://github.com/my-org'
                }
            }
        }

        service.handle_workflow_job(payload, base_url='https://example.run.app')

        mock_ct_client.enqueue_create_runner.assert_called_once()
        call_args = mock_ct_client.enqueue_create_runner.call_args
        assert call_args[0][1]['org_name'] == 'my-org'

    @patch('app.services.webhook_service.CloudTasksClient')
    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_queued_job_without_matching_label(self, mock_gh_client_class, mock_gc_client_class, mock_ct_client_class):
        """Test handling queued job without matching label does nothing."""
        mock_ct_client = Mock()
        mock_ct_client_class.return_value = mock_ct_client

        service = WebhookService()

        payload = {
            'action': 'queued',
            'workflow_job': {
                'labels': ['ubuntu-latest']
            },
            'repository': {
                'html_url': 'https://github.com/owner/repo',
                'full_name': 'owner/repo'
            }
        }

        service.handle_workflow_job(payload, base_url='https://example.run.app')

        mock_ct_client.enqueue_create_runner.assert_not_called()

    @patch('app.services.webhook_service.CloudTasksClient')
    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_completed_job(self, mock_gh_client_class, mock_gc_client_class, mock_ct_client_class):
        """Test handling completed job."""
        mock_gc_client = Mock()
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            'action': 'completed',
            'workflow_job': {
                'runner_name': 'runner-12345'
            }
        }

        service.handle_workflow_job(payload)

        mock_gc_client.delete_runner_instance.assert_called_once_with('runner-12345')

    @patch('app.services.webhook_service.CloudTasksClient')
    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_completed_job_no_runner_name(self, mock_gh_client_class, mock_gc_client_class, mock_ct_client_class):
        """Test handling completed job without runner name."""
        mock_gc_client = Mock()
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            'action': 'completed',
            'workflow_job': {}
        }

        service.handle_workflow_job(payload)

        mock_gc_client.delete_runner_instance.assert_not_called()

    @patch('app.services.webhook_service.CloudTasksClient')
    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_queued_job_enqueue_raises_exception(self, mock_gh_client_class, mock_gc_client_class, mock_ct_client_class):
        """Test error handling when enqueueing task fails."""
        mock_ct_client = Mock()
        mock_ct_client.enqueue_create_runner.side_effect = Exception("Cloud Tasks Error")
        mock_ct_client_class.return_value = mock_ct_client

        service = WebhookService()

        payload = {
            'action': 'queued',
            'workflow_job': {
                'labels': ['gcp-ubuntu-24.04']
            },
            'repository': {
                'html_url': 'https://github.com/owner/repo',
                'full_name': 'owner/repo'
            }
        }

        with pytest.raises(Exception, match="Cloud Tasks Error"):
            service.handle_workflow_job(payload, base_url='https://example.run.app')

    @patch('app.services.webhook_service.CloudTasksClient')
    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_queued_job_no_repo_or_org(self, mock_gh_client_class, mock_gc_client_class, mock_ct_client_class):
        """Test handling queued job when neither repo nor org enqueues task with null values.
        The create_runner method on the task handler side will handle the missing data."""
        mock_ct_client = Mock()
        mock_ct_client_class.return_value = mock_ct_client

        service = WebhookService()

        payload = {
            'action': 'queued',
            'workflow_job': {
                'labels': ['gcp-ubuntu-24.04']
            }
        }

        service.handle_workflow_job(payload, base_url='https://example.run.app')

        # Task is enqueued; create_runner will handle missing repo/org gracefully
        mock_ct_client.enqueue_create_runner.assert_called_once()

    @patch('app.services.webhook_service.CloudTasksClient')
    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_handle_completed_job_with_error(self, mock_gh_client_class, mock_gc_client_class, mock_ct_client_class):
        """Test error handling when deleting runner fails."""
        mock_gc_client = Mock()
        mock_gc_client.delete_runner_instance.side_effect = Exception("Delete Error")
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()

        payload = {
            'action': 'completed',
            'workflow_job': {
                'runner_name': 'runner-12345'
            }
        }

        # Should not raise exception, just log error
        service.handle_workflow_job(payload)

        mock_gc_client.delete_runner_instance.assert_called_once_with('runner-12345')


class TestCreateRunner:
    @patch('app.services.webhook_service.CloudTasksClient')
    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_create_runner_for_repo(self, mock_gh_client_class, mock_gc_client_class, mock_ct_client_class):
        """Test create_runner creates instance for a repository."""
        mock_gh_client = Mock()
        mock_gh_client.get_registration_token.return_value = "fake-token"
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()
        service.create_runner('gcp-ubuntu-24.04', 'https://github.com/owner/repo', None, 'owner/repo', None)

        mock_gh_client.get_registration_token.assert_called_once_with(repo_name='owner/repo')
        mock_gc_client.create_runner_instance.assert_called_once_with(
            'fake-token', 'https://github.com/owner/repo', 'gcp-ubuntu-24.04', 'owner/repo'
        )

    @patch('app.services.webhook_service.CloudTasksClient')
    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_create_runner_for_org(self, mock_gh_client_class, mock_gc_client_class, mock_ct_client_class):
        """Test create_runner creates instance for an organization."""
        mock_gh_client = Mock()
        mock_gh_client.get_registration_token.return_value = "org-token"
        mock_gh_client_class.return_value = mock_gh_client

        mock_gc_client = Mock()
        mock_gc_client_class.return_value = mock_gc_client

        service = WebhookService()
        service.create_runner('gcp-ubuntu-24.04', None, 'https://github.com/my-org', 'my-org/repo', 'my-org')

        mock_gh_client.get_registration_token.assert_called_once_with(org_name='my-org')
        mock_gc_client.create_runner_instance.assert_called_once_with(
            'org-token', 'https://github.com/my-org', 'gcp-ubuntu-24.04', 'my-org/repo'
        )

    @patch('app.services.webhook_service.CloudTasksClient')
    @patch('app.services.webhook_service.GCloudClient')
    @patch('app.services.webhook_service.GitHubClient')
    def test_create_runner_raises_on_failure(self, mock_gh_client_class, mock_gc_client_class, mock_ct_client_class):
        """Test create_runner raises exception on failure."""
        mock_gh_client = Mock()
        mock_gh_client.get_registration_token.side_effect = Exception("API Error")
        mock_gh_client_class.return_value = mock_gh_client

        service = WebhookService()

        with pytest.raises(Exception, match="API Error"):
            service.create_runner('gcp-ubuntu-24.04', 'https://github.com/owner/repo', None, 'owner/repo', None)
