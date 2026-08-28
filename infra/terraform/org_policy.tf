# org_policy.tf -- Org Policy constraints enforcing residency and a private data plane.
#
# General Principle map:
#   P-03 (data residency, defence in depth): even if someone hand-edits a resource, these
#         org policies REJECT the creation of resources outside the approved locations.
#         gcp.resourceLocations is the master residency control; the rest harden the project
#         (no public VM IPs, uniform bucket access, CMEK required) so data and compute stay
#         in-country and private (P-05).
#
# This file was missing until 2026-08-28, which made this the one stack in the catalog whose
# residency rested entirely on per-resource pins: every resource named the right location, and
# nothing refused a resource that did not. The per-resource pins are the intent; this is the
# control. It matters most here because var.docai_location routes document extraction to the
# `us` multi-region, so the policy width IS the residency claim rather than a restatement of
# var.region.
#
# Scoped to the project via google_org_policy_policy on parent = projects/<id>. To enforce
# org-wide, move these to parent = "organizations/${var.org_id}".
# verify: https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/org_policy_policy

# Master residency policy: GENERATED from var.allowed_regions, so the allowlist that gates
# var.region at plan time is the same list the Org Policy enforces at create time.
resource "google_org_policy_policy" "resource_locations" {
  count = var.enable_org_policies ? 1 : 0

  name   = "projects/${var.project_id}/policies/gcp.resourceLocations"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      values {
        # e.g. in:asia-southeast1-locations confines resources to the Singapore region.
        # var.resource_location_values overrides this only where a required service has no
        # single-region presence (Agent Search has none at all; Document AI has none here
        # until in-region access is granted). See that variable: widening is a jurisdiction
        # statement, not an exception list.
        allowed_values = length(var.resource_location_values) > 0 ? var.resource_location_values : [for r in var.allowed_regions : "in:${r}-locations"]
      }
    }
  }

  depends_on = [google_project_service.required]
}

# Disable VM external IPs -- keep the data plane private (P-05).
resource "google_org_policy_policy" "no_external_ip" {
  count = var.enable_org_policies ? 1 : 0

  name   = "projects/${var.project_id}/policies/compute.vmExternalIpAccess"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      deny_all = "TRUE"
    }
  }

  depends_on = [google_project_service.required]
}

# Require uniform bucket-level access (no per-object ACL exfiltration paths).
resource "google_org_policy_policy" "uniform_bucket_access" {
  count = var.enable_org_policies ? 1 : 0

  name   = "projects/${var.project_id}/policies/storage.uniformBucketLevelAccess"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      enforce = "TRUE"
    }
  }

  depends_on = [google_project_service.required]
}

# Require CMEK for the data-bearing services (no Google-managed-key fallback).
resource "google_org_policy_policy" "restrict_cmek_projects" {
  count = var.enable_org_policies ? 1 : 0

  name   = "projects/${var.project_id}/policies/gcp.restrictNonCmekServices"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      values {
        denied_values = [
          "discoveryengine.googleapis.com",
          "logging.googleapis.com",
        ]
      }
    }
  }

  depends_on = [google_project_service.required]
}
