# Service accounts (LLD APAC 13.1). Grants are on the bucket, dataset, topic
# or secret wherever the API allows, so each identity reaches only its own.

locals {
  service_accounts = {
    cycle   = "Region cycle jobs: ingest, detect, plume, snapshot"
    citizen = "Citizen photo analyzer"
    api     = "Public API"
    train   = "Model training jobs"
    push    = "Pub/Sub push identity: may invoke the citizen analyzer only"
  }
}

resource "google_service_account" "sa" {
  for_each = local.service_accounts

  account_id   = "sa-${each.key}"
  display_name = each.value
}

locals {
  sa = { for k, v in google_service_account.sa : k => "serviceAccount:${v.email}" }

  bucket_grants = [
    { sa = "cycle", bucket = "raw", role = "roles/storage.objectAdmin" },
    { sa = "cycle", bucket = "serving", role = "roles/storage.objectAdmin" },
    { sa = "cycle", bucket = "models", role = "roles/storage.objectViewer" },
    { sa = "cycle", bucket = "citizen", role = "roles/storage.objectViewer" },
    { sa = "citizen", bucket = "citizen", role = "roles/storage.objectAdmin" },
    { sa = "citizen", bucket = "serving", role = "roles/storage.objectAdmin" },
    { sa = "api", bucket = "serving", role = "roles/storage.objectAdmin" },
    { sa = "api", bucket = "citizen", role = "roles/storage.objectAdmin" },
    { sa = "train", bucket = "models", role = "roles/storage.objectAdmin" },
  ]

  dataset_grants = [
    { sa = "cycle", dataset = "raw", role = "roles/bigquery.dataEditor" },
    { sa = "cycle", dataset = "predictions", role = "roles/bigquery.dataEditor" },
    { sa = "cycle", dataset = "graph", role = "roles/bigquery.dataEditor" },
    { sa = "cycle", dataset = "ops", role = "roles/bigquery.dataEditor" },
    { sa = "citizen", dataset = "citizen", role = "roles/bigquery.dataEditor" },
    { sa = "citizen", dataset = "ops", role = "roles/bigquery.dataEditor" },
    { sa = "api", dataset = "raw", role = "roles/bigquery.dataViewer" },
    { sa = "api", dataset = "predictions", role = "roles/bigquery.dataViewer" },
    { sa = "api", dataset = "eval", role = "roles/bigquery.dataViewer" },
    { sa = "api", dataset = "graph", role = "roles/bigquery.dataViewer" },
    { sa = "api", dataset = "ops", role = "roles/bigquery.dataViewer" },
    { sa = "train", dataset = "raw", role = "roles/bigquery.dataViewer" },
    { sa = "train", dataset = "predictions", role = "roles/bigquery.dataViewer" },
    { sa = "train", dataset = "eval", role = "roles/bigquery.dataEditor" },
  ]

  secret_grants = [
    { sa = "cycle", secret = "openaq_api_key" },
    { sa = "cycle", secret = "firms_map_key" },
    { sa = "api", secret = "jwt_secret" },
    { sa = "api", secret = "citizen_reporter_salt" },
    { sa = "citizen", secret = "jwt_secret" },
  ]

  # Project-level only where no narrower resource exists.
  project_roles = [
    { sa = "cycle", role = "roles/bigquery.jobUser" },
    { sa = "cycle", role = "roles/earthengine.viewer" },
    { sa = "cycle", role = "roles/serviceusage.serviceUsageConsumer" },
    { sa = "citizen", role = "roles/bigquery.jobUser" },
    { sa = "citizen", role = "roles/aiplatform.user" },
    { sa = "api", role = "roles/bigquery.jobUser" },
    { sa = "api", role = "roles/aiplatform.user" },
    { sa = "train", role = "roles/bigquery.jobUser" },
  ]
}

resource "google_storage_bucket_iam_member" "grant" {
  for_each = { for g in local.bucket_grants : "${g.sa}/${g.bucket}/${g.role}" => g }

  bucket = google_storage_bucket.concern[each.value.bucket].name
  role   = each.value.role
  member = local.sa[each.value.sa]
}

resource "google_bigquery_dataset_iam_member" "grant" {
  for_each = { for g in local.dataset_grants : "${g.sa}/${g.dataset}/${g.role}" => g }

  dataset_id = google_bigquery_dataset.analytics[each.value.dataset].dataset_id
  role       = each.value.role
  member     = local.sa[each.value.sa]
}

resource "google_secret_manager_secret_iam_member" "grant" {
  for_each = { for g in local.secret_grants : "${g.sa}/${g.secret}" => g }

  secret_id = google_secret_manager_secret.app[each.value.secret].id
  role      = "roles/secretmanager.secretAccessor"
  member    = local.sa[each.value.sa]
}

resource "google_project_iam_member" "grant" {
  for_each = { for g in local.project_roles : "${g.sa}/${g.role}" => g }

  project = var.project_id
  role    = each.value.role
  member  = local.sa[each.value.sa]
}

# Signed upload URLs are signed with the API's own identity (IAM signBlob),
# so no key file exists anywhere.
resource "google_service_account_iam_member" "api_sign_blob" {
  service_account_id = google_service_account.sa["api"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.sa["api"]
}
