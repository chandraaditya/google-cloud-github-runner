# Cloud Tasks queue for rate-limiting concurrent runner VM creation
# https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_tasks_queue
resource "google_cloud_tasks_queue" "runner_jobs" {
  project  = module.project.project_id
  name     = "runner-jobs-${local.region_shortnames[var.region]}"
  location = var.region

  rate_limits {
    max_concurrent_dispatches = var.github_runners_max_concurrent_jobs
    max_dispatches_per_second = 500
  }

  retry_config {
    max_attempts       = 3
    min_backoff        = "1s"
    max_backoff        = "10s"
    max_retry_duration = "300s"
    max_doublings      = 3
  }

  depends_on = [
    module.project
  ]
}
