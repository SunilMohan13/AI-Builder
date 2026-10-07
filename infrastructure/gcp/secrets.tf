# Secret containers only. Values are added out of band, never in Terraform
# state:  printf '%s' "$VALUE" | gcloud secrets versions add <id> --data-file=-
# Each Cloud Run service mounts only the secrets it reads.

locals {
  secrets = {
    openaq_api_key        = { id = "aeropulse-openaq-api-key", env = "AEROPULSE_OPENAQ_API_KEY" }
    firms_map_key         = { id = "aeropulse-firms-map-key", env = "AEROPULSE_FIRMS_MAP_KEY" }
    jwt_secret            = { id = "aeropulse-jwt-secret", env = "AEROPULSE_JWT_SECRET" }
    citizen_reporter_salt = { id = "aeropulse-citizen-reporter-salt", env = "AEROPULSE_CITIZEN_REPORTER_SALT" }
  }
}

resource "google_secret_manager_secret" "app" {
  for_each = local.secrets

  secret_id = each.value.id
  replication {
    auto {}
  }
}
