# Two topics and one dead-letter topic (LLD APAC 5.4).
#
#   citizen bucket incoming/ --OBJECT_FINALIZE--> aero.citizen.reports
#     --push (OIDC as sa-push)--> citizen-analyzer /pubsub/push
#     --after 5 failed deliveries--> aero.citizen.reports.dlq (operator inspection)

locals {
  pubsub_agent = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_topic" "citizen_reports" {
  name                       = "aero.citizen.reports"
  message_retention_duration = var.pubsub_retention
}

resource "google_pubsub_topic" "citizen_reports_dlq" {
  name                       = "aero.citizen.reports.dlq"
  message_retention_duration = var.pubsub_retention
}

resource "google_pubsub_topic" "alerts" {
  name                       = "aero.alerts"
  message_retention_duration = var.pubsub_retention
}

resource "google_pubsub_topic_iam_member" "alerts_publisher" {
  for_each = toset(["cycle", "citizen"])

  topic  = google_pubsub_topic.alerts.id
  role   = "roles/pubsub.publisher"
  member = local.sa[each.key]
}

# --- upload notification ------------------------------------------------------

data "google_storage_project_service_account" "gcs" {}

resource "google_pubsub_topic_iam_member" "gcs_publishes_uploads" {
  topic  = google_pubsub_topic.citizen_reports.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
}

resource "google_storage_notification" "citizen_uploads" {
  bucket             = google_storage_bucket.concern["citizen"].name
  payload_format     = "JSON_API_V1"
  topic              = google_pubsub_topic.citizen_reports.id
  event_types        = ["OBJECT_FINALIZE"]
  object_name_prefix = "incoming/"

  depends_on = [google_pubsub_topic_iam_member.gcs_publishes_uploads]
}

# --- push to the analyzer -----------------------------------------------------

resource "google_pubsub_subscription" "citizen_analyzer" {
  name                       = "citizen-analyzer-push"
  topic                      = google_pubsub_topic.citizen_reports.id
  ack_deadline_seconds       = 120
  message_retention_duration = var.pubsub_retention

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.citizen.uri}/pubsub/push"
    oidc_token {
      service_account_email = google_service_account.sa["push"].email
      audience              = google_cloud_run_v2_service.citizen.uri
    }
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.citizen_reports_dlq.id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

resource "google_pubsub_subscription" "citizen_dlq_inspect" {
  name                       = "citizen-reports-dlq-inspect"
  topic                      = google_pubsub_topic.citizen_reports_dlq.id
  message_retention_duration = "604800s"
}

# Dead-lettering and OIDC push both act as the Pub/Sub service agent.
resource "google_pubsub_topic_iam_member" "dlq_publisher" {
  topic  = google_pubsub_topic.citizen_reports_dlq.id
  role   = "roles/pubsub.publisher"
  member = local.pubsub_agent
}

resource "google_pubsub_subscription_iam_member" "dlq_source_subscriber" {
  subscription = google_pubsub_subscription.citizen_analyzer.id
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent
}

resource "google_service_account_iam_member" "pubsub_mints_push_tokens" {
  service_account_id = google_service_account.sa["push"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.pubsub_agent
}
