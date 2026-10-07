# Minimal Google Cloud footprint for AeroPulse APAC (LLD APAC 3, 13).
#
#   terraform init -backend-config="bucket=<state bucket>" -backend-config="prefix=aeropulse"
#   terraform apply -var-file=<env>.tfvars
#
# Secret values are never in Terraform: this creates the Secret Manager
# secrets only. Add a version to each before the Cloud Run services first
# deploy (see docs/ops/runbook.md).
terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.location
}

data "google_project" "this" {}
