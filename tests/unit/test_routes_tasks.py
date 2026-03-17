import json
from unittest.mock import patch, Mock


class TestTaskRoutes:
    @patch('app.routes.tasks.WebhookService')
    def test_create_runner_success(self, mock_webhook_service, client):
        """Test successful runner creation from Cloud Tasks."""
        mock_service_instance = mock_webhook_service.return_value

        payload = {
            'template_name': 'gcp-ubuntu-24.04',
            'repo_url': 'https://github.com/owner/repo',
            'repo_owner_url': None,
            'repo_name': 'owner/repo',
            'org_name': None,
        }

        response = client.post(
            '/tasks/create-runner',
            data=json.dumps(payload),
            content_type='application/json',
            headers={'X-CloudTasks-QueueName': 'runner-jobs-as1'}
        )

        assert response.status_code == 200
        assert response.json['status'] == 'success'
        mock_service_instance.create_runner.assert_called_once_with(
            'gcp-ubuntu-24.04',
            'https://github.com/owner/repo',
            None,
            'owner/repo',
            None,
        )

    def test_create_runner_missing_cloud_tasks_header(self, client):
        """Test rejection when X-CloudTasks-QueueName header is missing."""
        payload = {'template_name': 'gcp-ubuntu-24.04'}

        response = client.post(
            '/tasks/create-runner',
            data=json.dumps(payload),
            content_type='application/json',
        )

        assert response.status_code == 403

    @patch('app.routes.tasks.WebhookService')
    def test_create_runner_missing_template_name(self, mock_webhook_service, client):
        """Test rejection when template_name is missing."""
        payload = {
            'repo_url': 'https://github.com/owner/repo',
            'repo_name': 'owner/repo',
        }

        response = client.post(
            '/tasks/create-runner',
            data=json.dumps(payload),
            content_type='application/json',
            headers={'X-CloudTasks-QueueName': 'runner-jobs-as1'}
        )

        assert response.status_code == 400

    @patch('app.routes.tasks.WebhookService')
    def test_create_runner_failure_returns_500(self, mock_webhook_service, client):
        """Test that runner creation failure returns 500 for Cloud Tasks retry."""
        mock_service_instance = mock_webhook_service.return_value
        mock_service_instance.create_runner.side_effect = Exception("GCE quota exceeded")

        payload = {
            'template_name': 'gcp-ubuntu-24.04',
            'repo_url': 'https://github.com/owner/repo',
            'repo_name': 'owner/repo',
        }

        response = client.post(
            '/tasks/create-runner',
            data=json.dumps(payload),
            content_type='application/json',
            headers={'X-CloudTasks-QueueName': 'runner-jobs-as1'}
        )

        assert response.status_code == 500
