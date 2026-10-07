# Settings only. No variable here holds a secret value.

variable "project_id" {
  description = "Google Cloud project id."
  type        = string
}

variable "location" {
  description = "Region for Cloud Run, buckets, BigQuery and Scheduler."
  type        = string
  default     = "asia-south1"
}

variable "bucket_prefix" {
  description = "Bucket name prefix (AEROPULSE_GCS_BUCKET). Empty means \"<project_id>-aeropulse\", the app default."
  type        = string
  default     = ""
}

variable "bigquery_prefix" {
  description = "BigQuery dataset prefix (AEROPULSE_BIGQUERY_DATASET); datasets are <prefix>_raw, _predictions, ..."
  type        = string
  default     = "aeropulse"
}

variable "region_ids" {
  description = "Onboarded Region Packs. One cycle job and one schedule each."
  type        = list(string)
  default     = ["in-north", "sg-singapore", "au-nsw"]
}

variable "app_image" {
  description = "Python image (infrastructure/docker/Dockerfile built with UV_EXTRAS=\"--extra gcp\"). API, cycle and citizen analyzer share it."
  type        = string
}

variable "ml_image" {
  description = "Training image (infrastructure/docker/Dockerfile.ml with the gcp extra). Empty skips the training job."
  type        = string
  default     = ""
}

variable "web_image" {
  description = "Static web image (frontend/web/Dockerfile.prod)."
  type        = string
}

variable "cycle_schedule" {
  description = "Cron for every region's cycle. Its interval must exceed cycle_timeout_seconds so cycles never overlap."
  type        = string
  default     = "*/15 * * * *"
}

variable "cycle_timeout_seconds" {
  description = "Cloud Run Job task timeout for one region cycle."
  type        = number
  default     = 600
}

variable "scheduler_paused" {
  description = "Cost kill switch (LLD 13.2): pause every cycle schedule."
  type        = bool
  default     = false
}

variable "max_instances" {
  description = "Cloud Run max instances per service."
  type        = map(number)
  default     = { api = 3, web = 2, citizen = 2 }
}

variable "raw_retention_days" {
  description = "Delete raw provider archives after this many days."
  type        = number
  default     = 30
}

variable "incoming_photo_retention_days" {
  description = "Delete unsanitized citizen uploads (incoming/) after this many days."
  type        = number
  default     = 7
}

variable "pubsub_retention" {
  description = "Message retention on the two topics and the dead-letter topic."
  type        = string
  default     = "86400s"
}

variable "gemini_model" {
  description = "Copilot and citizen-photo model name (Vertex AI through the service account)."
  type        = string
  default     = "gemini-3.8-flash"
}
