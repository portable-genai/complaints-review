# Compliance FAQ

For compliance, MLRO, and model-risk teams assessing the repo's regulatory posture.
Cross-references: [`COMPLIANCE.md`](../../COMPLIANCE.md) (the full principle to control map),
[`SPEC.md`](../../SPEC.md).

### Is this making regulatory or complaint-handling decisions autonomously?

No. It is a **decision-support** agent: every consequential output requires human review
(maker-checker), and the draft response is never sent by the system. The deterministic engines
produce a documented, replayable assessment (summary, categorization, conduct flags, deadline
breach); a qualified human (complaint handler / conduct / MLRO) disposes. Escalation signals
(a regulatory-breach flag, a vulnerable-customer flag, a systemic-issue flag, a breached
handling deadline, a high severity) raise the review bar, never lower it, and are routed to the
sibling **Hrz7** Human-Review and Maker-Checker Console (rule R8), not auto-executed.

### How is customer PII handled?

Redact-before-everything (R1): `review_service._prepare` redacts the case inputs (each document
extract too) before any model, index, registry or audit call. National-identifier detection is
**jurisdiction-driven** via the shared `pii-kit`: `adapters/local/redaction.py`
builds its rows from `pii_kit.national_patterns_for(settings.pii.jurisdictions)` plus universal
email / phone (SG / HK / JP / AU by default via `PiiSettings`), and the DLP adapter builds its
custom info types from the same rows, so a non-Singapore deployment scrubs, and gates on, its
own identifiers rather than just the SG NRIC / FIN. The runtime guardrail / DLP itself is the
sibling **Hrz1** gateway; this repo consumes it rather than re-implementing it.

### How is the work auditable / reproducible?

Every review writes an immutable, already-redacted WORM `AuditEvent` (fields
`redacted_prompt` / `redacted_response`) with the decision and the citation set. Every claim in
the four artifacts carries a source-and-page `Citation`. The consequential decisions are
deterministic, so an auditor can recompute every conduct flag and the deadline breach from the
same inputs. The enterprise WORM audit system is **Hrz5**; the in-repo hash-chained store
(`hex_service_kit.audit.HashChainedAuditLog`) is the offline/local stand-in, with its exact
tamper-evidence limits stated in [security-faq.md](security-faq.md).

### What is the model-risk story?

An offline eval gate (`eval/run_eval.py`, `--mode smoke|gate`) scores categorization accuracy,
groundedness, citation accuracy, and PII safety against a golden set and fails the build below
threshold; the strictest metric is `pii_safety >= 0.99`, scored off the same shared `pii-kit`
rows the runtime redactor uses plus a pack-independent literal check (disabling redaction drops
it to 0.6, so the gate cannot be falsely green). The enterprise promotion gate and red-team
harness are the sibling **Hrz4** system; this repo's gate mirrors its thresholds (registered
bundle `doc6-complaints-review`) and gate mode refuses to run outside
`COMPLAINTS_PROFILE=platform|gcp`. A fork must rebuild the golden set for its own vertical.

### Are the compliance-tunable numbers owned as configuration?

Partly, and this is stated honestly. The deadline window, the vulnerability keywords, and the
escalating-flag / high-severity sets are currently **module constants** in
`domain/categorization_service.py` and `domain/review_policy.py`, not a `policy:` section of
`config/settings.yaml`. Externalizing them into settings with a defaults-equal-reference
override test is a **known open item** (check B4 in
[`docs/practices-audit.md`](../practices-audit.md)). Own those numbers with your compliance
function by editing the constants (and pinning them in a test) until the settings section lands.

### Which regulators does this map to?

[`COMPLIANCE.md`](../../COMPLIANCE.md) maps the internal P-01..P-12 / R1..R6 controls to
concrete code with file pointers. A per-regulator crosswalk appendix marked
adopter-owned (the MAS / FCA / HKMA / APRA complaint-handling references) is a **known open
item** (check G2); add it by copying the control table and swapping the regulator-reference
column, then re-reviewing with local counsel. At scale, the sibling **Rsk1** compliance
assistant and control-mapping toolkit generate and maintain these crosswalks; a large estate
should integrate them rather than hand-maintain the table.

### Is data residency enforced?

Yes, at deploy time. `infra/terraform/` pins a single in-country region (default
`asia-southeast1` / Singapore) with a fail-fast validation, and binds CMEK (`kms.tf`), a VPC-SC
perimeter (`vpc_sc.tf`) and a locked WORM log bucket (`logging_worm.tf`); the region and tenant
are variables. A residency-violation CI gate is the sibling **Rsk3** `architecture-validator`
(`domain/residency/`), and the exit / concentration-risk plan is **Rgc9**
`operational-resilience-mapping` (`domain/concentration_exit/`); this repo enforces residency in
its own infra and is one of the systems those tools reason about. (An in-repo offline Terraform
`fmt` / `validate` check is itself a small open item, D5.)

### Can we run it against real customer data today?

Not without your own legal, security, and model-risk sign-off. Every fixture and complaint
reference is obviously fictional, and the docs state throughout that this is a reference build.
The adoption checklist ([`docs/ADOPTING.md`](../ADOPTING.md)) lists the steps, replace reference
data, own the escalation policy numbers, wire your IdP, rebuild the eval golden set, that must
precede any live-data use.

### Which complaint-handling scope does it cover, and which does it not?

It covers **file-level** review of a single complaint / conduct file: grounded summary,
categorization, conduct flags, deadline-breach check, and a draft response, always routed to a
human. Enterprise complaint **case management** and workflow (queues, SLAs, routing across many
cases) is the sibling **Hrz7** `human-review-console` (`domain/cases/`), which also owns the
human disposition step; that is an adjacent catalog system, not this repo's job. See
[features-faq.md](features-faq.md) for the boundary.
