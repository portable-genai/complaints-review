# iam.tf : Least-privilege service accounts for the B6 service.
#
# General Principle map:
#   P-06 (least privilege / separation of duties): a single serving identity that gets only
#         the roles it needs (extract, query A2, call models + guardrail + DLP, write audit
#         + traces). No shared "kitchen-sink" SA.
#   P-03 (residency): the identity is project-scoped; data access is to in-region services.
#   P-09 (CMEK explicit): the SA that touches CMEK-encrypted data gets its own cryptoKey
#         use binding.
#   R3 (governed RAG): policy/regulatory passages are retrieved from A2 with the actor's
#         ACL principals; ACL enforcement lives in A2, the agent SA carries only the
#         discoveryengine viewer role it needs.

resource "google_service_account" "app" {
  account_id   = "complaints-review-app"
  display_name = "B6 Complaints & Conduct File Review (serving / API)"
  project      = var.project_id

  depends_on = [google_project_service.required]
}

locals {
  # Serving path: extract complaint docs (Document AI), query the A2 governed RAG store,
  # call models + DLP, write audit + traces, run evals, read secrets. No org-wide writes.
  app_roles = [
    "roles/aiplatform.user",        # Gemini reasoning + Gen AI evals
    "roles/documentai.apiUser",     # process complaint documents
    "roles/discoveryengine.viewer", # query A2 governed RAG (read-only)
    "roles/dlp.user",               # deidentifyContent (P-04, R1)
    "roles/logging.logWriter",      # write redacted audit events to WORM sink (R2)
    "roles/cloudtrace.agent",       # OpenTelemetry spans (content OFF)
    "roles/secretmanager.secretAccessor",
    "roles/run.invoker",
  ]
}

resource "google_project_iam_member" "app" {
  for_each = toset(local.app_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.app.email}"
}

# App uses the CMEK for envelope ops it performs directly.
resource "google_kms_crypto_key_iam_member" "app" {
  crypto_key_id = google_kms_crypto_key.complaints.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.app.email}"
}

# ------------------------- Agent Runtime identity --------------------------- #
resource "google_service_account" "agent_runtime" {
  account_id   = "complaints-review-runtime"
  display_name = "B6 Agent Runtime (reasoningEngine) identity"
  project      = var.project_id

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "agent_runtime" {
  for_each = toset(["roles/aiplatform.user", "roles/logging.logWriter", "roles/cloudtrace.agent"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.agent_runtime.email}"
}
