"""
Google Cloud Tasks Client for enqueueing runner creation jobs.
"""
import json
import logging
import os
from google.cloud import tasks_v2

logger = logging.getLogger(__name__)


class CloudTasksClient:
    """Client for interacting with Google Cloud Tasks."""

    def __init__(self):
        """Initialize CloudTasksClient with project and queue configuration."""
        self.project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
        self.location = os.environ.get('CLOUD_TASKS_LOCATION')
        self.queue_name = os.environ.get('CLOUD_TASKS_QUEUE')
        self.service_account_email = os.environ.get('CLOUD_TASKS_SERVICE_ACCOUNT')

        if not all([self.project_id, self.location, self.queue_name]):
            logger.warning("Cloud Tasks configuration incomplete. CloudTasksClient will not work correctly.")

        self.client = tasks_v2.CloudTasksClient()

    def enqueue_create_runner(self, base_url, task_payload):
        """
        Enqueue a runner creation task.

        Args:
            base_url (str): The base URL of the Cloud Run service.
            task_payload (dict): The payload to send to the task handler.

        Returns:
            str: The name of the created task.
        """
        parent = self.client.queue_path(self.project_id, self.location, self.queue_name)
        url = f"{base_url}/tasks/create-runner"

        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": url,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(task_payload).encode(),
                "oidc_token": {
                    "service_account_email": self.service_account_email,
                    "audience": base_url,
                },
            },
        }

        response = self.client.create_task(parent=parent, task=task)
        logger.info("Created Cloud Tasks task: %s", response.name)
        return response.name
