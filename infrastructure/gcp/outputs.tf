output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "web_url" {
  value = google_cloud_run_v2_service.web.uri
}

output "citizen_analyzer_url" {
  value = google_cloud_run_v2_service.citizen.uri
}

output "buckets" {
  value = { for k, b in google_storage_bucket.concern : k => b.name }
}

output "datasets" {
  value = { for k, d in google_bigquery_dataset.analytics : k => d.dataset_id }
}

output "service_accounts" {
  value = { for k, s in google_service_account.sa : k => s.email }
}

output "secret_ids" {
  description = "Add a version to each before first deploy; Terraform never holds the values."
  value       = { for k, s in google_secret_manager_secret.app : k => s.secret_id }
}
