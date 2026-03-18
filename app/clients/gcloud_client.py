"""
Google Cloud Client for managing GCE instances.
"""
import logging
import os
import re
import uuid
import shlex
import google.api_core.exceptions
import google.cloud.compute_v1 as compute_v1

logger = logging.getLogger(__name__)


class GCloudClient:
    """Client for interacting with Google Cloud Compute Engine API."""

    def __init__(self):
        """Initialize GCloudClient with project and zone configuration."""
        self.project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
        self.zone = os.environ.get('GOOGLE_CLOUD_ZONE', 'us-central1-a')
        self.region = '-'.join(self.zone.split('-')[:-1])

        if not self.project_id:
            logger.warning("GOOGLE_CLOUD_PROJECT not set. GCloudClient will not work correctly.")

        # All zones in the region, primary zone first, for fallback on ZONE_RESOURCE_POOL_EXHAUSTED
        self.zones = [f"{self.region}-{s}" for s in ['a', 'b', 'c']]
        if self.zone in self.zones:
            self.zones.remove(self.zone)
        self.zones.insert(0, self.zone)

        # https://docs.cloud.google.com/python/docs/reference/compute/latest/google.cloud.compute_v1.services.instances.InstancesClient
        self.instance_client = compute_v1.InstancesClient()
        # Create a RegionInstanceTemplatesClient for retrieving templates in a specific region
        # https://docs.cloud.google.com/python/docs/reference/compute/latest/google.cloud.compute_v1.services.region_instance_templates
        self.instance_templates_client = compute_v1.RegionInstanceTemplatesClient()

    def _get_template_name(self, template_name):
        """
        Find a matching instance template by name prefix.

        Args:
            template_name (str): The name prefix to search for.

        Returns:
            google.cloud.compute_v1.InstanceTemplate or None: The matching template resource.
        """
        # Replace dots with dashes for template name, so gcp-ubuntu-24.04 matches gcp-ubuntu-24-04
        prefix = template_name.replace('.', '-')
        # logger.info(f"Prefix: {prefix}")
        # Create regex pattern: prefix followed by dash, at least 12 digits, and optional alphanumeric characters
        pattern = re.compile(f"^{re.escape(prefix)}-\\d{{14,}}[a-z0-9]*$")
        try:
            # List all templates to find one that matches the pattern
            for template in self.instance_templates_client.list(project=self.project_id, region=self.region):
                # logger.info(f"Template: {template.name}")
                if pattern.match(template.name):
                    return template
            return None
        except Exception:
            return None

    def create_runner_instance(self, registration_token, repo_url, template_name, instance_label=None):
        """
        Create a new GCE instance for a GitHub Actions runner.

        Args:
            registration_token (str): The GitHub Actions runner registration token.
            repo_url (str): The URL of the repository or organization.
            template_name (str): The name of the instance template to use.
            instance_label (str): Label to add to the Instance for Cost Tracking.

        Returns:
            str: The name of the created instance.
        """
        instance_template_resource = self._get_template_name(template_name)
        if instance_template_resource:
            logger.info(f"Found matching instance template: {instance_template_resource.name}")
        else:
            logger.warning(f"No matching instance template found for label '{template_name}' in region {self.region}. "
                           "Skipping instance creation.")
            return None

        instance_uuid = uuid.uuid4().hex[:16]
        if instance_template_resource.name.startswith("dependabot"):
            instance_name = f"dependabot-{instance_uuid}"
        else:
            instance_name = f"runner-{instance_uuid}"

        logger.info(f"Creating GCE instance {instance_name} with template {instance_template_resource.self_link}")

        # Set instance name
        instance_resource = compute_v1.Instance()  # google.cloud.compute_v1.types.Instance
        instance_resource.name = instance_name

        if instance_label is not None:
            owner, repo = instance_label.split("/")
            instance_resource.labels = {
                "gha-owner": owner.lower(),
                "gha-repo": repo.lower(),
                "gha-runner": template_name
            }

        # Set metadata (startup script) - use shlex.quote to prevent command injection
        startup_script = (
            f"sudo -u runner /actions-runner/config.sh --url {shlex.quote(repo_url)} "
            f"--token {shlex.quote(registration_token)} "
            f"--name {shlex.quote(instance_name)} --labels {shlex.quote(template_name)} "
            "--ephemeral --unattended --no-default-labels --disableupdate && "
            "sudo -u runner /actions-runner/run.sh"
        )
        metadata = compute_v1.Metadata()
        metadata.items = [
            compute_v1.Items(key="startup-script", value=startup_script),
            compute_v1.Items(key="vmDnsSetting", value="ZonalOnly"),
            compute_v1.Items(key="block-project-ssh-keys", value="true"),
        ]
        instance_resource.metadata = metadata

        # Try each zone in the region until one succeeds
        last_error = None
        for zone in self.zones:
            request = compute_v1.InsertInstanceRequest(
                project=self.project_id,
                zone=zone,
                instance_resource=instance_resource,
                source_instance_template=instance_template_resource.self_link
            )

            try:
                operation = self.instance_client.insert(request=request)
                logger.info(f"Instance creation operation started in {zone}: {operation.name}")
                operation.result()
                logger.info(f"Instance created successfully in {zone}: {instance_name}")
                return instance_name
            except Exception as e:
                last_error = e
                logger.warning(f"Failed to create instance in {zone}: {e}")
                if len(self.zones) > 1:
                    logger.info(f"Trying next zone...")
                continue

        logger.error(f"Failed to create instance in all zones: {last_error}")
        raise last_error

    def count_runner_instances(self):
        """
        Count the number of currently running or provisioning runner GCE instances
        across all zones in the region.

        Returns:
            int: The number of active runner instances.
        """
        try:
            count = 0
            for zone in self.zones:
                request = compute_v1.ListInstancesRequest(
                    project=self.project_id,
                    zone=zone,
                )
                for instance in self.instance_client.list(request=request):
                    if (instance.name.startswith("runner-") or instance.name.startswith("dependabot-")) and \
                            instance.status in ("RUNNING", "STAGING", "PROVISIONING"):
                        count += 1
            logger.info(f"Active runner instance count (across {len(self.zones)} zones): {count}")
            return count
        except Exception as e:
            logger.error(f"Failed to count runner instances: {e}")
            return 0

    def delete_runner_instance(self, instance_name):
        """
        Delete a GCE instance, searching across all zones in the region.

        Args:
            instance_name (str): The name of the instance to delete.
        """
        logger.info(f"Deleting GCE instance {instance_name}")
        for zone in self.zones:
            try:
                operation = self.instance_client.delete(
                    project=self.project_id,
                    zone=zone,
                    instance=instance_name
                )
                logger.info(f"Instance deletion operation started in {zone}: {operation.name}")
                return
            except google.api_core.exceptions.NotFound:
                continue
            except Exception as e:
                logger.error(f"Failed to delete instance {instance_name} in {zone}: {e}")
                raise
        logger.error(f"Instance {instance_name} not found in any zone")
