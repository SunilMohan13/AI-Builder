# Datasets "<prefix>_<suffix>" (aeropulse_storage.analytics.TABLES). Tables
# are created by the first batch load, partitioned and clustered there.

locals {
  dataset_suffixes = toset(["raw", "predictions", "eval", "graph", "citizen", "ops"])
}

resource "google_bigquery_dataset" "analytics" {
  for_each = local.dataset_suffixes

  dataset_id                 = "${var.bigquery_prefix}_${each.key}"
  location                   = var.location
  delete_contents_on_destroy = false
}
