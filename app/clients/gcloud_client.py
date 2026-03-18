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

# Machine series fallback order for ZONE_RESOURCE_POOL_EXHAUSTED.
# Key = primary series, value = ordered list of fallback series to try.
# All fallbacks are within ~50% of the baseline series price.
_SERIES_FALLBACKS = {
    'e2': ['n2d', 't2d', 'n1'],
    'n2': ['n2d', 'e2', 'n1'],
    'n2d': ['e2', 't2d', 'n1'],
    'n1': ['e2', 'n2d', 't2d'],
    'c4a': ['t2a'],  # ARM-only fallback
}

# E2 "medium"/"small"/"micro" don't exist in other series.
# Map them to the closest standard equivalent.
_MACHINE_TYPE_OVERRIDES = {
    'e2-medium': ['n1-standard-1', 't2d-standard-1', 'n2d-standard-2'],
    'e2-small': ['n1-standard-1', 't2d-standard-1'],
    'e2-micro': ['n1-standard-1', 't2d-standard-1'],
}


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

    @staticmethod
    def _get_fallback_machine_types(machine_type):
        """
        Generate fallback machine types for when the primary is unavailable.

        Args:
            machine_type (str): The original machine type (e.g. "e2-standard-2").

        Returns:
            list[str]: Ordered list of fallback machine types to try.
        """
        # Check for special overrides (e.g. e2-medium has no equivalent in other series)
        if machine_type in _MACHINE_TYPE_OVERRIDES:
            return _MACHINE_TYPE_OVERRIDES[machine_type]

        # Parse series from machine type: "e2-standard-2" → series="e2", spec="-standard-2"
        match = re.match(r'^([a-z]\w*?)(-.+)$', machine_type)
        if not match:
            return []

        series, spec = match.groups()
        fallbacks = _SERIES_FALLBACKS.get(series, [])
        return [f"{s}{spec}" for s in fallbacks]

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

        # Self-delete command: VM deletes itself using metadata to find its own zone
        self_delete = (
            "ZONE=$(curl -sH 'Metadata-Flavor: Google' "
            "metadata.google.internal/computeMetadata/v1/instance/zone | cut -d/ -f4) && "
            "gcloud compute instances delete $(hostname) --zone=$ZONE --quiet"
        )

        # Set metadata (startup script) - use shlex.quote to prevent command injection
        startup_script = (
            # Idle watchdog: if no job starts within 5 min, self-delete
            f"( sleep 300 && "
            f"if ! pgrep -f Runner.Worker > /dev/null; then {self_delete}; fi ) & "
            # Normal runner startup
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

        # Build the list of machine types to try: template default + fallbacks
        template_machine_type = instance_template_resource.properties.machine_type
        fallback_types = self._get_fallback_machine_types(template_machine_type)
        # None = use template default (no override)
        machine_types_to_try = [None] + fallback_types

        last_error = None
        for machine_type_override in machine_types_to_try:
            if machine_type_override:
                logger.info(f"Trying fallback machine type: {machine_type_override}")

            for zone in self.zones:
                # Override machine type only when using a fallback.
                # For the template default (None), don't set machine_type at all.
                if machine_type_override:
                    instance_resource.machine_type = f"zones/{zone}/machineTypes/{machine_type_override}"

                request = compute_v1.InsertInstanceRequest(
                    project=self.project_id,
                    zone=zone,
                    instance_resource=instance_resource,
                    source_instance_template=instance_template_resource.self_link
                )

                try:
                    operation = self.instance_client.insert(request=request)
                    logger.info(f"Instance creation started in {zone} "
                                f"({machine_type_override or template_machine_type}): {operation.name}")
                    operation.result()
                    logger.info(f"Instance created successfully in {zone}: {instance_name}")
                    return instance_name
                except Exception as e:
                    last_error = e
                    error_str = str(e)
                    if "ZONE_RESOURCE_POOL_EXHAUSTED" in error_str:
                        logger.warning(f"Resource exhausted in {zone} for "
                                       f"{machine_type_override or template_machine_type}")
                        continue
                    elif "QUOTA_EXCEEDED" in error_str:
                        # No quota for this machine series — skip to next fallback
                        logger.warning(f"Quota exceeded for "
                                       f"{machine_type_override or template_machine_type}: {e}")
                        break  # Skip remaining zones, try next machine type
                    elif "does not exist" in error_str:
                        # Machine type doesn't exist in this zone (e.g. n2d-medium, t2a)
                        logger.warning(f"Machine type {machine_type_override} not available in {zone}")
                        break  # Skip remaining zones for this machine type
                    else:
                        logger.error(f"Failed to create instance: {e}")
                        raise

        logger.error(f"Failed to create instance in all zones and machine types: {last_error}")
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
