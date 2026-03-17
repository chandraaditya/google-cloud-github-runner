"""
Routes for handling Cloud Tasks callbacks.
"""
import logging
from flask import Blueprint, request, jsonify
from app.services import WebhookService
from app import limiter

logger = logging.getLogger(__name__)

tasks_bp = Blueprint('tasks', __name__)


@tasks_bp.route('/tasks/create-runner', methods=['POST'])
@limiter.limit("1000 per hour")
def create_runner():
    """
    Handle runner creation task dispatched by Cloud Tasks.

    Cloud Tasks sends this request with an OIDC token and
    sets X-CloudTasks-QueueName to identify the source queue.
    """
    queue_name = request.headers.get('X-CloudTasks-QueueName')
    if not queue_name:
        logger.error("Missing X-CloudTasks-QueueName header. Rejecting request.")
        return jsonify({'status': 'error', 'message': 'Not a Cloud Tasks request'}), 403

    try:
        payload = request.json
        if not payload:
            logger.error("Empty or invalid JSON payload in task")
            return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400
    except Exception as e:
        logger.error("Failed to parse task JSON payload: %s", str(e))
        return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400

    template_name = payload.get('template_name')
    repo_url = payload.get('repo_url')
    repo_owner_url = payload.get('repo_owner_url')
    repo_name = payload.get('repo_name')
    org_name = payload.get('org_name')

    if not template_name:
        logger.error("Missing template_name in task payload")
        return jsonify({'status': 'error', 'message': 'Missing template_name'}), 400

    try:
        webhook_service = WebhookService()
        webhook_service.create_runner(template_name, repo_url, repo_owner_url, repo_name, org_name)
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        logger.error("Failed to create runner from task: %s", str(e))
        # Return 500 so Cloud Tasks will retry
        return jsonify({'status': 'error', 'message': 'Runner creation failed'}), 500
