# document_ai.tf : Document AI processor for complaint-document extraction.
#
# General Principle map:
#   P-03 (residency): the processor is created in the asia-southeast1 (Singapore) location
#         so complaint document bytes are processed in-country.
#   P-01 (managed-first): a single managed Document AI processor replaces a bespoke
#         document-parsing service; the DocumentExtractionPort binds to it.
#
# verify: https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/document_ai_processor

resource "google_document_ai_processor" "complaint" {
  project      = var.project_id
  location     = var.region # asia-southeast1 : in-country processing (P-03)
  display_name = "complaints-review-extractor"

  # A form parser extracts the key/value fields and full text from complaint documents
  # (letters, complaint forms, statements, screenshots of app conversations).
  type = "FORM_PARSER_PROCESSOR"

  depends_on = [google_project_service.required]
}
