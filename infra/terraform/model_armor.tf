# model_armor.tf : Model Armor guardrail template (rule R1).
#
# General Principle map:
#   P-04 / R1 (guardrail screening): the guardrail adapter (model_armor_guardrail) screens
#         every inbound complaint and outbound draft response through this template for
#         prompt injection, jailbreak, sensitive-data leakage and malicious URLs. Because
#         B6 handles customer complaint PII, this screen is mandatory in both directions.
#   P-03 (residency): the template is created in asia-southeast1 and called on the regional
#         Model Armor host (modelarmor.asia-southeast1.rep.googleapis.com).
#
# verify: https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/model_armor_template

resource "google_model_armor_template" "complaints_guardrail" {
  provider    = google-beta
  location    = var.region             # asia-southeast1 : regional endpoint (P-03)
  template_id = "complaints-guardrail" # matches settings.yaml model_armor.template_id

  filter_config {
    pi_and_jailbreak_filter_settings {
      filter_enforcement = "ENABLED"
      confidence_level   = "LOW_AND_ABOVE"
    }
    # Regional capability. asia-southeast1 does not serve it and refuses the template
    # outright with CAPABILITY_NOT_SUPPORTED, so a deployment there declines it EXPLICITLY
    # via the variable and discloses the narrowed guardrail. The default keeps it on, so a
    # region that does serve it gets it without having to ask.
    dynamic "malicious_uri_filter_settings" {
      for_each = var.model_armor_full_capabilities ? [1] : []
      content {
        filter_enforcement = "ENABLED"
      }
    }
    rai_settings {
      rai_filters {
        filter_type      = "DANGEROUS"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "HARASSMENT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "HATE_SPEECH"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "SEXUALLY_EXPLICIT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
    }
  }

  # Required by the API even though every field inside it is optional: creating the template
  # without this block succeeds, and the next apply then fails with "The 'template_metadata'
  # field is required" while trying to remove what the service itself populated. Neither
  # `terraform validate` nor the offline suite resolves the API's own field requirements, so
  # this is only ever found by applying twice.
  template_metadata {
    # Multi-language detection is a regional capability, refused the same way the malicious
    # URI filter is, so it follows the same variable and the same disclosure.
    dynamic "multi_language_detection" {
      for_each = var.model_armor_full_capabilities ? [1] : []
      content {
        enable_multi_language_detection = true
      }
    }

    # OFF, and this is the decision rather than the default. Sanitize-operation logs carry
    # the prompt text that was screened, and the prompt here is the complaint text a customer wrote, with whatever account and personal details they put in it.
    # Copying it into ordinary operation logs would put that material outside the
    # CMEK-encrypted, access-controlled stores this stack exists to keep it in.
    log_sanitize_operations = false
  }

  depends_on = [google_project_service.required]
}
