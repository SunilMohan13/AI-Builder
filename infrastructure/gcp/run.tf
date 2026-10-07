# Cloud Run services (api, web, citizen-analyzer; min instances 0), one cycle
# job per region with parallelism 1, and one schedule per region (LLD 3, 13.2).

locals {
  platform_env = {
    AEROPULSE_PLATFORM         = "gcp"
    AEROPULSE_GCP_PROJECT      = var.project_id
    AEROPULSE_GCS_BUCKET       = local.bucket_prefix
    AEROPULSE_BIGQUERY_DATASET = var.bigquery_prefix
  }
  # Only processes that verify tokens run as "production": that setting makes
  # the JWT secret mandatory, and the cycle never sees that secret.
  token_service_env = merge(local.platform_env, { AEROPULSE_ENVIRONMENT = "production" })
}

# --- api ----------------------------------------------------------------------

resource "google_cloud_run_v2_service" "api" {
  name                = "aeropulse-api"
  location            = var.location
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.sa["api"].email
    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances["api"]
    }
    containers {
      image   = var.app_image
      command = ["aeropulse-api"]
      ports {
        container_port = 8000
      }
      dynamic "env" {
        for_each = merge(local.token_service_env, {
          AEROPULSE_SERVICE_NAME         = "aeropulse-api"
          AEROPULSE_CITIZEN_ANALYZER_URL = google_cloud_run_v2_service.citizen.uri
          AEROPULSE_CORS_ORIGINS         = google_cloud_run_v2_service.web.uri
          AEROPULSE_GEMINI_MODEL         = var.gemini_model
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = toset(["jwt_secret", "citizen_reporter_salt"])
        content {
          name = local.secrets[env.key].env
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.app[env.key].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.grant]
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- web ----------------------------------------------------------------------

resource "google_cloud_run_v2_service" "web" {
  name                = "aeropulse-web"
  location            = var.location
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances["web"]
    }
    containers {
      image = var.web_image
      ports {
        container_port = 8080
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "web_public" {
  name     = google_cloud_run_v2_service.web.name
  location = var.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- citizen analyzer ---------------------------------------------------------
# No public invoker: /pubsub/push relies on Cloud Run IAM. Only the push
# identity and the API (moderation, via X-Serverless-Authorization) may call
# it. Internal-only ingress would also need VPC egress on the API (deferred).

resource "google_cloud_run_v2_service" "citizen" {
  name                = "aeropulse-citizen-analyzer"
  location            = var.location
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.sa["citizen"].email
    timeout         = "120s"
    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances["citizen"]
    }
    containers {
      image   = var.app_image
      command = ["aeropulse-citizen", "serve", "--port", "8080"]
      ports {
        container_port = 8080
      }
      dynamic "env" {
        for_each = merge(local.token_service_env, {
          AEROPULSE_SERVICE_NAME         = "aeropulse-citizen-analyzer"
          AEROPULSE_CITIZEN_VISION_MODEL = var.gemini_model
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = local.secrets["jwt_secret"].env
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.app["jwt_secret"].secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.grant]
}

resource "google_cloud_run_v2_service_iam_member" "citizen_invokers" {
  for_each = toset(["push", "api"])

  name     = google_cloud_run_v2_service.citizen.name
  location = var.location
  role     = "roles/run.invoker"
  member   = local.sa[each.key]
}

# --- cycle: one job and one schedule per region -------------------------------

resource "google_cloud_run_v2_job" "cycle" {
  for_each = toset(var.region_ids)

  name                = "aeropulse-cycle-${each.key}"
  location            = var.location
  deletion_protection = false

  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.sa["cycle"].email
      timeout         = "${var.cycle_timeout_seconds}s"
      max_retries     = 0
      containers {
        image   = var.app_image
        command = ["aeropulse-cycle"]
        args    = ["--region", each.key, "--mode", "live"]
        resources {
          limits = { cpu = "1", memory = "1Gi" }
        }
        dynamic "env" {
          for_each = merge(local.platform_env, {
            AEROPULSE_SERVICE_NAME        = "aeropulse-cycle"
            AEROPULSE_EARTHENGINE_PROJECT = var.project_id
          })
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = toset(["openaq_api_key", "firms_map_key"])
          content {
            name = local.secrets[env.key].env
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.app[env.key].secret_id
                version = "latest"
              }
            }
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.grant]
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_runs_cycle" {
  for_each = google_cloud_run_v2_job.cycle

  name     = each.value.name
  location = var.location
  role     = "roles/run.invoker"
  member   = local.sa["cycle"]
}

resource "google_cloud_scheduler_job" "cycle" {
  for_each = google_cloud_run_v2_job.cycle

  name             = "aeropulse-cycle-${each.key}"
  region           = var.location
  schedule         = var.cycle_schedule
  time_zone        = "Etc/UTC"
  paused           = var.scheduler_paused
  attempt_deadline = "60s"

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.location}/jobs/${each.value.name}:run"
    oauth_token {
      service_account_email = google_service_account.sa["cycle"].email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.scheduler_runs_cycle]
}

# --- training (on demand; never promotes) -------------------------------------

resource "google_cloud_run_v2_job" "train" {
  count = var.ml_image == "" ? 0 : 1

  name                = "aeropulse-train"
  location            = var.location
  deletion_protection = false

  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account       = google_service_account.sa["train"].email
      timeout               = "3600s"
      max_retries           = 0
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
      volumes {
        name = "models"
        gcs {
          bucket    = google_storage_bucket.concern["models"].name
          read_only = false
        }
      }
      containers {
        image = var.ml_image
        args = [
          "--family", "all",
          "--dataset", "bq://${var.project_id}/${var.bigquery_prefix}",
          "--out", "/app/models/runs",
        ]
        resources {
          limits = { cpu = "2", memory = "4Gi" }
        }
        volume_mounts {
          name       = "models"
          mount_path = "/app/models"
        }
        dynamic "env" {
          for_each = merge(local.platform_env, { AEROPULSE_SERVICE_NAME = "aeropulse-train" })
          content {
            name  = env.key
            value = env.value
          }
        }
      }
    }
  }
}
