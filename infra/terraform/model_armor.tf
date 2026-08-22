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
    malicious_uri_filter_settings {
      filter_enforcement = "ENABLED"
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

  depends_on = [google_project_service.required]
}
