# outputs.tf : Values the app/operators need to wire settings.yaml after apply.
#
# These map 1:1 onto config/settings.yaml / config.py fields so a deploy is just
# "apply, then export these into the runtime environment".

output "project_id" {
  description = "The deployment project id."
  value       = var.project_id
}

output "region" {
  description = "Deployment region selected at deploy time (default asia-southeast1, Singapore)."
  value       = var.region
}

# ------------------------------ Document AI --------------------------------- #
output "documentai_processor_id" {
  description = "Document AI processor id (settings.yaml document_ai.processor_id)."
  value       = google_document_ai_processor.complaint.id
}

output "documentai_location" {
  description = "Confirms Document AI residency : must match the deployed region (fail-fast)."
  value       = google_document_ai_processor.complaint.location
}

# --------------------------------- KMS -------------------------------------- #
output "kms_key" {
  description = "Regional CMEK crypto key id (settings.yaml kms_key / COMPLAINTS_KMS_KEY)."
  value       = google_kms_crypto_key.complaints.id
}

# ------------------------------- WORM logging ------------------------------- #
output "log_bucket" {
  description = "Locked WORM audit log bucket id (settings.yaml logging.bucket)."
  value       = google_logging_project_bucket_config.worm_audit.id
}

output "audit_sink_writer_identity" {
  description = "Sink writer identity (grant it bucket access if cross-project)."
  value       = google_logging_project_sink.audit_to_worm.writer_identity
}

# ------------------------- Model Armor / DLP -------------------------------- #
output "model_armor_template" {
  description = "Model Armor template id (settings.yaml model_armor.template_id)."
  value       = google_model_armor_template.complaints_guardrail.template_id
}

output "dlp_inspect_template" {
  description = "DLP inspect template (settings.yaml dlp.inspect_template)."
  value       = google_data_loss_prevention_inspect_template.complaints.id
}

output "dlp_deidentify_template" {
  description = "DLP deidentify template (settings.yaml dlp.deidentify_template)."
  value       = google_data_loss_prevention_deidentify_template.complaints.id
}

# ----------------------------- Service accounts ----------------------------- #
output "app_service_account" {
  description = "Serving/API service account email."
  value       = google_service_account.app.email
}

output "agent_runtime_service_account" {
  description = "Agent Runtime (reasoningEngine) service account email."
  value       = google_service_account.agent_runtime.email
}

output "agent_staging_bucket" {
  description = "Agent Runtime staging bucket for the SDK-based deploy."
  value       = google_storage_bucket.agent_staging.name
}
