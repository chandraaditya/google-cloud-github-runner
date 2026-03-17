# Cloud Tasks queue for rate-limiting concurrent runner VM creation
# https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_tasks_queue
resource "google_cloud_tasks_queue" "runner_jobs" {
  project  = module.project.project_id
  name     = "runner-jobs-${local.region_shortnames[var.region]}"
  location = var.region

  rate_limits {
    # Keep concurrent dispatches low to minimize the race window in the concurrency check.
    # The actual VM limit is enforced in the task handler via MAX_CONCURRENT_RUNNERS.
    max_concurrent_dispatches = 2
    max_dispatches_per_second = 500
  }

  retry_config {
    # Allow unlimited retries for up to 2 hours so tasks waiting for a free runner slot
    # don't fail permanently if jobs are long-running.
    max_attempts       = -1
    min_backoff        = "10s"
    max_backoff        = "60s"
    max_retry_duration = "7200s"
    max_doublings      = 3
  }

  depends_on = [
    module.project
  ]
}
