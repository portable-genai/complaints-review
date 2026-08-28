# COMPLIANCE · Doc6 Complaints & Conduct File Review

How Doc6 maps to the catalog's General Principles (P-01..P-12) and rules (R1..R6, R8), with the
concrete control in **this** repo. Principles that do not apply are marked **n/a** with the
reason.

## General Principles

| ID | Principle | How Doc6 satisfies it (concrete control) |
|----|-----------|-----------------------------------------|
| P-01 | Managed-first, minimal surface | Document AI, Agent Search, Gemini, Model Armor, DLP, Cloud Logging, Cloud Trace, Gen AI evals: only the services used are enabled (`infra/terraform/apis.tf`). |
| P-02 | No vendor lock-in (ports + adapters) | 10 `Protocol` ports; four adapter families (`gcp`, `local`, `platform`, `onprem`); one-line `profile` switch. The `local` family proves the domain runs entirely off-cloud (SQLite FTS5, deterministic LLM, regex DLP, no Google Cloud SDK); the `onprem` family proves reversibility; the contract test enforces parity across `local` and `onprem`. |
| P-03 | Data residency / in-country | **PARTIAL, and the gaps are Document AI and Agent Search.** Every managed resource except those two takes its location from `region`, chosen at deploy time and validated in Terraform against the `allowed_regions` residency allowlist (default `asia-southeast1`; extending that list is the review point), with a VPC-SC perimeter (`vpc_sc.tf`) blocking exfiltration and a `gcp.resourceLocations` Org Policy (`org_policy.tf`, generated from the same allowlist) REFUSING the creation of a resource outside it. Until 2026-08-28 that policy was absent here, so residency rested on per-resource pins alone: every resource named the right location and nothing refused one that did not. Where a deviation below widens the policy, `resource_location_values` states the width, and the width is the residency claim. **Document AI reaches `asia-southeast1` only once Google grants single-region access**, so processor and adapter both default to the `us` MULTI-REGION and complaint document bytes are extracted in the United States (`docai_location`, `COMPLAINTS_DOCAI_LOCATION`; move both together when access lands, and both halves refuse a location that is neither the deploy region nor a named multi-region, `global` by name). **Agent Search serves no Cloud region at all** (`global`, `us`, `eu` only), so the policy corpus defaults to `global` and is unlocated; `us` or `eu` confines it to one jurisdiction where an obligation bites. Both are stated deviations to a named location, never to a global endpoint standing in for a region. |
| P-04 | Minimise PII to the model | **Emphasis.** Customer PII (NRIC, email, name, card, etc.) is redacted at the boundary by the DLP / Hrz1 redaction adapter before any model, KB, span or audit write. Each attached document extract is redacted too. |
| P-05 | Defence in depth | Redaction + guardrail in the domain pipeline **and** again at the ADK model boundary (`agent/callbacks.py`). |
| P-06 | Maker-checker (human in the loop) | **Emphasis.** `ComplaintReviewPolicy`: a review always `requires_human_review=True`; the **draft response is never sent by the system** (`draft_is_sendable()` is always false); high-stakes flags escalate to a senior checker. The escalation is ROUTED to the Hrz7 maker-checker console (rule R8), not left as a boolean (`ports/review_router.py`, `adapters/*/review_router.py`). |
| P-07 | Everything audited (provenance) | **Emphasis.** Every interaction writes an already-redacted `AuditEvent` to a locked WORM bucket; every artifact carries page-level `Citation`s mapped from retrieved passages. |
| P-08 | Quality / model-risk gate | `eval/run_eval.py` (offline) + `GenAiEvalAdapter` (production) enforce categorisation accuracy, groundedness, citation accuracy and PII safety thresholds; CI fails below threshold. |
| P-09 | CMEK does not cascade | One regional CMEK key ring; explicit per-service-agent key bindings for Document AI, Vertex/Agent Runtime and Logging (`infra/terraform/kms.tf`). |
| P-10 | Least privilege | Dedicated app + Agent Runtime service accounts with only the roles they need (`infra/terraform/iam.tf`). |
| P-11 | Reproducible, declarative infra | All infra is Terraform; only `project_id` and a couple of per-tenant values are variables; everything else is concrete and in-region. |
| P-12 | Reversible / exit strategy | The `onprem` adapter family is the documented Google Distributed Cloud migration target; switching `profile` to `onprem` rebinds every port with no domain change and fails fast (CLI exits 2) until each placeholder is implemented. The `local` profile is the proof the whole pipeline runs off-cloud today: a complaint review completes offline with a real cited artifact, no Google Cloud, no API key and no emulators. |

## Rules

| ID | Rule | How Doc6 satisfies it |
|----|------|----------------------|
| R1 | Hrz1 guardrail + redaction (PII workloads) | **Applies.** Complaint files carry customer PII, so the full pipeline runs: redact then guardrail-screen on INPUT and OUTPUT, both in the domain service and at the model boundary. |
| R2 | Hrz5 audit | Every interaction is recorded to the WORM audit sink (Cloud Logging locked bucket or Hrz5 `/v1/audit`). |
| R3 | Hrz2 governed RAG | Policy and regulatory guidance is retrieved from the Hrz2 Enterprise KB with the actor's ACL principals; Doc6 builds no bespoke retrieval backend. |
| R4 | Hrz3 registry | Doc6 publishes an A2A AgentCard (`/.well-known/agent-card.json`) and can register with Hrz3 (`AgentRegistryPort`). |
| R5 | Hrz4 eval gate at promotion | The Hrz4 eval gate (offline + `GenAiEvalAdapter`) gates promotion to Agent Runtime. |
| R6 | Rsk3 at intake | A complaint file is taken in at intake and screened per the catalog's intake control (Rsk3) before review; Doc6 consumes the screened file. |
| R8 | Route `requires_human_review` to Hrz7 | **Applies.** Every escalated complaint review is submitted to the Hrz7 Human-Review & Maker-Checker Console via the shared `review-kit` client (redact-before-wire); `local` enqueues to a transactional outbox so the routing path runs offline, `gcp`/`platform` submit over S2S to Hrz7's service intake (`HRZ_HUMAN_REVIEW_URL`). `ports/review_router.py`, `adapters/{local,platform,onprem}/review_router.py`, `adapters/_review_payload.py`. |

## Synthetic data

All complaint files, customer references, NRIC/FIN ids and email addresses in this repo
(fixtures, eval golden set, UI samples) are invented and obviously fictional. None of them
correspond to a real customer.

## Adopter-owned regulator crosswalk

This appendix is intentionally adopter-owned. The adopting bank's compliance function
must determine complaint-regime applicability, nominate owners, and link approved evidence.

| Reference topic | Candidate control evidence | Applicability | Adopter owner | Approved evidence |
|---|---|---|---|---|
| MAS fair dealing and complaint handling | configured deterministic deadline and escalation policy | To assess | To assign | To link |
| MAS TRM model and change controls | P-06, P-08; maker-checker and eval gate | To assess | To assign | To link |
| MAS data protection and residency | P-04, P-05; redaction, CMEK, perimeter | To assess | To assign | To link |
