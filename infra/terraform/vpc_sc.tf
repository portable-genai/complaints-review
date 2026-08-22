# vpc_sc.tf : VPC Service Controls perimeter around the AI/data plane.
#
# General Principle map:
#   P-03 (residency + exfiltration control): a service perimeter draws a logical boundary
#         around the sovereignty-critical APIs (Vertex/Agent Platform, Document AI, Agent
#         Search backing A2, DLP, Model Armor, Logging, KMS, Secret Manager, Storage).
#         Complaint data cannot be read across the boundary to a non-Singapore project,
#         which is what stops the complaint PII and audit log from leaving the country.
#   P-01 (least surface): only the services B6 uses are inside the perimeter.
#
# Guarded by var.enable_vpc_sc so non-prod/dev applies can skip it (count = 0).
#
# DEPLOY-ORDER CAVEAT:
#   The perimeter blocks API calls from outside it. If you enable this BEFORE the resources
#   in the other files are created (or before your Terraform runner / CI identity is added
#   to the perimeter's access levels), those API calls will be denied and the apply will
#   fail. Recommended order:
#     1. Apply everything with enable_vpc_sc = false.
#     2. Add your operator/CI identity to an access level.
#     3. Re-apply with enable_vpc_sc = true to enforce the boundary.
#   # verify: VPC-SC dry-run mode before enforcing.

locals {
  perimeter_restricted_services = [
    "aiplatform.googleapis.com",
    "documentai.googleapis.com",
    "discoveryengine.googleapis.com",
    "dlp.googleapis.com",
    "modelarmor.googleapis.com",
    "logging.googleapis.com",
    "cloudtrace.googleapis.com",
    "cloudkms.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ]
}

resource "google_access_context_manager_service_perimeter" "complaints" {
  count = var.enable_vpc_sc ? 1 : 0

  parent = "accessPolicies/${var.access_policy_id}"
  name   = "accessPolicies/${var.access_policy_id}/servicePerimeters/complaints_review_sg"
  title  = "complaints_review_sg"

  perimeter_type = "PERIMETER_TYPE_REGULAR"

  status {
    resources           = ["projects/${data.google_project.this.number}"]
    restricted_services = local.perimeter_restricted_services

    vpc_accessible_services {
      enable_restriction = true
      allowed_services   = local.perimeter_restricted_services
    }
  }

  depends_on = [google_project_service.required]
}
