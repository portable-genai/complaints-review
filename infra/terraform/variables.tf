# variables.tf : The only knobs. Everything else is a concrete in-region value.
#
# General Principle map:
#   P-03 (residency): `region` is SELECTED AT DEPLOY TIME and validated against the
#         residency allowlist (var.allowed_regions) so a caller fails fast rather than
#         deploying to an unvetted, out-of-jurisdiction region. The default is
#         asia-southeast1 (Singapore).
#   P-08 (auditability/retention): `retention_days` is a Terraform variable (the WORM
#         bucket lock is irreversible, so retention must be deliberate).
#
# Per the build contract, ONLY project_id and a couple of genuinely per-tenant values
# (org/billing ids, the VPC-SC toggle) are variables. All service identifiers, locations
# and template names are concrete. Policy/regulatory retrieval infra lives in A2, not here.

variable "project_id" {
  description = "Target GCP project id (required). Single-tenant, Singapore-resident."
  type        = string
}

variable "allowed_regions" {
  description = <<-EOT
    Residency allowlist: the regions this regulated stack may be deployed to. The region is
    chosen at deploy time (var.region) and validated against this list to FAIL FAST (P-03),
    so an operator cannot accidentally deploy to an unvetted region. Extending this list is
    the deliberate residency review point: do it only after confirming the full managed stack
    (Document AI, DLP, Model Armor, Vertex/Agent Platform, CMEK, Logging) and your residency
    obligations are satisfied in that region.
  EOT
  type        = list(string)
  default     = ["asia-southeast1"]

  validation {
    condition     = length(var.allowed_regions) > 0
    error_message = "allowed_regions must list at least one residency-approved region."
  }
}

variable "region" {
  description = <<-EOT
    Deployment region, SELECTED AT DEPLOY TIME. Defaults to asia-southeast1 (Singapore) but
    is overridable. Validated against var.allowed_regions so an unapproved region fails fast
    at `terraform plan` rather than deploying data out of jurisdiction (P-03).
  EOT
  type        = string
  default     = "asia-southeast1"

  validation {
    # Cross-variable validation (Terraform >= 1.9). Fails at plan time = setup time.
    condition     = contains(var.allowed_regions, var.region)
    error_message = "region must be one of var.allowed_regions (residency allowlist). Add it there first if that region is approved for this workload (P-03)."
  }
}

variable "zone" {
  description = "Default zone for zonal resources. Must sit inside var.region."
  type        = string
  default     = "asia-southeast1-a"
}

variable "retention_days" {
  description = "WORM audit-log retention in days. Default ~7 years. Lock is irreversible."
  type        = number
  default     = 2557 # ~7 years; mirrors config/settings.yaml logging.retention_days

  validation {
    condition     = var.retention_days >= 2557
    error_message = "Compliance retention must be at least 2557 days (~7 years) (P-08)."
  }
}

variable "org_id" {
  description = "Organization id : required for Org Policy and Access Context Manager."
  type        = string
}

variable "billing_account" {
  description = "Billing account id (used by Assured Workloads / FinOps tagging)."
  type        = string
  default     = ""
}

variable "access_policy_id" {
  description = <<-EOT
    Existing Access Context Manager policy id (numeric, no prefix) for the org.
    Required when enable_vpc_sc = true; the service perimeter is created under it.
    Create once per org with:
      gcloud access-context-manager policies create \
        --organization=ORG_ID --title="sg-residency"
  EOT
  type        = string
  default     = ""
}

variable "vpc_network_name" {
  description = "Name of the VPC that hosts the private service endpoints for the agent."
  type        = string
  default     = "complaints-review-vpc"
}

variable "enable_vpc_sc" {
  description = "Create the VPC Service Controls perimeter around the AI/data APIs (P-03)."
  type        = bool
  default     = true
}

variable "enable_org_policies" {
  description = <<-EOT
    Create the project-level Org Policy constraints (gcp.resourceLocations and the hardening
    set). Requires org-level permission the deploying principal may not hold, which is why it
    is a toggle rather than unconditional: a deploy without it still gets every per-resource
    location pin, and does NOT get the control that refuses an unpinned one. Leave it true
    wherever the residency claim is load-bearing.
  EOT
  type        = bool
  default     = true
}

variable "resource_location_values" {
  description = <<-EOT
    Value groups for the gcp.resourceLocations Org Policy. Empty (the default) derives the
    strictest form from var.allowed_regions: those regions and their sub-locations, nothing
    else.

    Widen it ONLY where a service this stack genuinely needs has no presence at single-region
    granularity, and treat the width as the residency claim rather than as plumbing. Two
    services here force the question:

      * Agent Search serves `global`, `us` and `eu` and NO Cloud region at all.
      * Document AI serves the deploy region only once Google grants single-region access,
        and routes to the `us` multi-region until then (var.docai_location).

    Move to the smallest value group that still describes ONE JURISDICTION -- `in:us-locations`
    keeps every resource inside the United States -- and state the residency claim at that
    granularity rather than pretending it is still single-region. NEVER list an individual
    foreign region to unblock one service: that turns a jurisdiction boundary into a list of
    exceptions nobody can reason about.

    NOT YET VERIFIED BY EXECUTION here: whether a `global` Agent Search data store is subject
    to this constraint at all, or is exempt as a global resource. Confirm at first apply and
    record the answer rather than guessing; the failure mode if it IS subject is an apply
    error naming discoveryengine, which is the good kind of failure. cdd-sow-research already has the
    Document AI half of this answer by execution: an `in:<region>-locations` policy BLOCKED
    processor creation at `us` with "violates constraint constraints/gcp.resourceLocations".
  EOT
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for v in var.resource_location_values : startswith(v, "in:") || startswith(v, "is:")])
    error_message = "Each value must be an Org Policy location value group (in:...) or a literal location (is:...)."
  }
}

variable "docai_location" {
  description = <<-EOT
    Where the Document AI processor is CREATED. Deliberately NOT var.region.

    Document AI does not serve every Cloud region, and creating a processor in one it does not
    serve 404s at apply. It DOES serve asia-southeast1 -- and serves no us-central1 endpoint at
    all -- but Singapore is "limited support": a subset of processors, several in Preview, and
    access is gated behind Google's Document AI Single Region Request Form. Until that request
    is granted this routes to the `us` MULTI-REGION, which is a stated residency deviation:
    document bytes are extracted in the United States while the rest of the stack stays in
    region. Set this to asia-southeast1 the day access lands.

    Keep it equal to the runtime's COMPLAINTS_DOCAI_LOCATION, which selects the same location for
    the adapter. If the two disagree, Terraform creates the processor in one location and the
    adapter looks for it in another, and the failure surfaces as a confusing 404 at request
    time rather than at apply.

    `us` and `eu` are multi-regions, not `global`: each names ONE jurisdiction. Never widen
    this to a location the service does not serve just to make an apply succeed. Whichever is
    chosen, gcp.resourceLocations must be wide enough to permit it, and the
    residency claim must be stated at that width rather than at var.region's.
  EOT
  type        = string
  default     = "us"

  validation {
    # Mirrors the runtime rule: the deploy region, or a NAMED multi-region. `global` is refused
    # by name because it names no jurisdiction, and so is any other single region -- an
    # out-of-region single region would be a silent jurisdiction change dressed as a fix.
    condition     = contains(["us", "eu"], var.docai_location) || var.docai_location == var.region
    error_message = "docai_location must be the deploy region (var.region) or a named Document AI multi-region (us, eu). `global` names no jurisdiction and is refused."
  }
}
