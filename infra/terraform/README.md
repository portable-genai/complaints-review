# Terraform: Doc6 Complaints & Conduct File Review infrastructure (asia-southeast1)

Concrete, in-region (Singapore) infrastructure for the Doc6 service. Only `project_id` and a
couple of genuinely per-tenant values (org/billing ids, the VPC-SC toggle) are variables;
every service identifier and template name is a fixed value and every location derives from
`var.region`, which is chosen at deploy time and validated against the `allowed_regions`
residency allowlist (default `["asia-southeast1"]`), so the deploy is reproducible and an
unvetted region fails fast (P-03).

> Policy and regulatory-guidance retrieval infrastructure (the governed RAG store) lives in
> **Hrz2** (`enterprise-knowledge-base`), not here. Doc6 retrieves policy via Hrz2; this stack
> provisions only what Doc6 owns: complaint-document extraction, PII redaction, the guardrail,
> the WORM audit trail, CMEK, IAM and the perimeter.

## What this provisions

| File | Resource | Principle |
|------|----------|-----------|
| `apis.tf` | Enables only the managed services Doc6 uses | P-01 |
| `document_ai.tf` | Document AI form-parser processor (complaint extraction) | P-03 |
| `dlp.tf` | DLP inspect + deidentify templates (incl. SG NRIC/FIN, passport) | P-04, R1 |
| `model_armor.tf` | Model Armor guardrail template (both directions) | R1 |
| `kms.tf` | Regional CMEK key ring + per-service-agent key bindings | P-09, P-03 |
| `logging_worm.tf` | Locked WORM audit bucket + sink + DATA_READ audit config | P-08, R2 |
| `iam.tf` | Least-privilege app + Agent Runtime service accounts | P-06 |
| `agent_runtime.tf` | CMEK-encrypted Agent Runtime staging bucket | P-01, P-03 |
| `vpc_sc.tf` | VPC Service Controls perimeter (guarded by `enable_vpc_sc`) | P-03 |
| `outputs.tf` | Values to wire into `config/settings.yaml` after apply | n/a |

## Usage

```bash
cp terraform.tfvars.example terraform.tfvars   # fill in project_id, org_id
terraform init -input=false
terraform plan                                  # review
terraform apply                                 # then export outputs into the runtime env
```

Do NOT run `terraform apply` against a shared project without review. The WORM bucket lock
(`logging_worm.tf`) is **irreversible**: confirm `retention_days` before applying.

## Deploy order with VPC-SC

The perimeter denies API calls from outside it. Apply in three steps:

1. Apply with `enable_vpc_sc = false`.
2. Add your operator / CI identity to an access level on the policy.
3. Re-apply with `enable_vpc_sc = true` to enforce the boundary.

Use VPC-SC dry-run mode before enforcing.

## After apply

Export the outputs into the runtime environment (or write them into
`config/settings.yaml`) so the `gcp` profile picks up the processor id, CMEK key, WORM
bucket, and DLP / Model Armor templates:

```bash
export COMPLAINTS_DOCAI_PROCESSOR="$(terraform output -raw documentai_processor_id)"
export COMPLAINTS_KMS_KEY="$(terraform output -raw kms_key)"
export COMPLAINTS_DLP_INSPECT_TEMPLATE="$(terraform output -raw dlp_inspect_template)"
export COMPLAINTS_DLP_DEIDENTIFY_TEMPLATE="$(terraform output -raw dlp_deidentify_template)"
```
