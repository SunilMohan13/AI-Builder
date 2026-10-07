# Buckets "<prefix>-raw|citizen|models|serving", the names
# aeropulse_storage.factory derives from AEROPULSE_GCS_BUCKET.

locals {
  bucket_prefix = var.bucket_prefix != "" ? var.bucket_prefix : "${var.project_id}-aeropulse"
  concerns      = toset(["raw", "citizen", "models", "serving"])
}

resource "google_storage_bucket" "concern" {
  for_each = local.concerns

  name                        = "${local.bucket_prefix}-${each.key}"
  location                    = var.location
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  # Model artifacts are content-addressed, but keep history for rollback.
  versioning {
    enabled = each.key == "models"
  }

  dynamic "lifecycle_rule" {
    for_each = each.key == "raw" ? [var.raw_retention_days] : []
    content {
      condition {
        age = lifecycle_rule.value
      }
      action {
        type = "Delete"
      }
    }
  }

  # Unsanitized uploads only; sanitized copies and analyses stay.
  dynamic "lifecycle_rule" {
    for_each = each.key == "citizen" ? [var.incoming_photo_retention_days] : []
    content {
      condition {
        age            = lifecycle_rule.value
        matches_prefix = ["incoming/"]
      }
      action {
        type = "Delete"
      }
    }
  }

  # Browsers PUT photos straight to signed URLs.
  dynamic "cors" {
    for_each = each.key == "citizen" ? [1] : []
    content {
      origin          = [google_cloud_run_v2_service.web.uri]
      method          = ["PUT"]
      response_header = ["Content-Type"]
      max_age_seconds = 3600
    }
  }
}
