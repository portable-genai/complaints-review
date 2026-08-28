# document_ai.tf : Document AI processor for complaint-document extraction.
#
# General Principle map:
#   P-03 (residency): PARTIAL, and stated rather than absorbed. The processor is created at
#         var.docai_location, which defaults to the `us` MULTI-REGION -- so complaint document
#         bytes are extracted in the United States while the rest of the stack stays in
#         Singapore. Document AI serves asia-southeast1 only once Google grants single-region
#         access; set var.docai_location (and the runtime's COMPLAINTS_DOCAI_LOCATION) to
#         asia-southeast1 the day it lands, and in-country extraction follows.
#   P-01 (managed-first): a single managed Document AI processor replaces a bespoke
#         document-parsing service; the DocumentExtractionPort binds to it.
#
# verify: https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/document_ai_processor

resource "google_document_ai_processor" "complaint" {
  project      = var.project_id
  location     = var.docai_location # NOT var.region: Document AI serves neither every region nor, yet, ours in-country
  display_name = "complaints-review-extractor"

  # A form parser extracts the key/value fields and full text from complaint documents
  # (letters, complaint forms, statements, screenshots of app conversations).
  type = "FORM_PARSER_PROCESSOR"

  depends_on = [google_project_service.required]
}
