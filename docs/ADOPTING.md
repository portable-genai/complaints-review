# Adopting this repo as your base

This repository (`complaints-review`, the Complaints and Conduct File Review agent) is a **common base**
that BFSI institutions (and other regulated industries) can fork to build their own
document-diligence review agents: complaints and conduct review, credit-memo review,
claims triage, ESG due diligence, and similar. It ships a reusable hexagonal core (a pure
stdlib domain, typed ports, swappable adapter profiles, a green offline gate) plus a fully
worked complaints / conduct vertical you can keep, replace, or learn from.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical
rebrand** (one script) and the **human decisions** the script cannot make for you.

> Related reading: [`ARCHITECTURE.md`](../ARCHITECTURE.md),
> [`CONTRIBUTING.md`](../CONTRIBUTING.md) (adding a port / sub-service), the
> [`faq/`](faq/) directory.

---

## 1. What you keep vs what you rewrite

The domain is pure stdlib (no cloud SDK, no framework), so it moves across hosts unchanged.
For a new vertical, the boundary is:

| Layer | Where | For a new vertical |
|---|---|---|
| **Kernel surface** (vertical-neutral intent) | `domain/kernel.py` names `Citation`, model envelopes, safety and audit contracts, but currently re-exports them from mixed `domain/models.py` | preserve the contract; a full split still moves the definitions into the kernel |
| **Policy** (your numbers) | the typed `policy:` settings for escalation flags, severity set, deadline window and vulnerability keywords | change by config and policy review |
| **Vertical** (complaints artifacts) | `domain/models.py`, the narrating services, `domain/prompts.py`, the local fixtures, the eval golden set, the UI review panels | rewrite for your artifacts |

The named kernel surface exists, but neutral and vertical definitions still originate together in
`domain/models.py`; completing the dependency inversion remains A7. This does not change runtime
portability, but it does affect how cleanly a fork lifts the kernel into another vertical.

Compliance-tunable values now come from typed `policy:` settings and are injected through the
shared composition root. Override tests cover categorisation and review behavior.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly:

- **Upstream-owned** (take our changes): `ports/`, `tests/contract/`, the eval harness
  (`eval/run_eval.py` mechanics), CI workflows, and the hexagon wiring (`config.py`
  `Container`).
- **Adopter-owned** (yours; expect to edit): `config/settings.yaml` *values*, the local
  fixtures, `adapters/onprem/*`, UI theming / branding, the golden eval dataset
  (`eval/datasets/`), and the `COMPLIANCE.md` jurisdiction rows.

Track upstream via git tags; rebase your adopter-owned
changes onto each release rather than merging `main` continuously.

## 3. The mechanical rebrand (one script)

`scripts/rename_fork.py` rewrites the package name, CLI entry point, `COMPLAINTS_` env
prefix, and resource ids across the tree in one pass. Preview first, then apply:

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_conduct_agent --cli acme-conduct \
    --env-prefix ACME --resource acme-conduct-review --dry-run

# Apply:
python scripts/rename_fork.py --package acme_conduct_agent --cli acme-conduct \
    --env-prefix ACME --resource acme-conduct-review --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make lint test eval
```

Add `--include-docs` to sweep Markdown prose too. Note that in this repo the CLI entry point
and the resource-id stem are the same string (`complaints-review`), so pass the same value
for `--cli` and `--resource` if you want them aligned (the common case); the distribution
name (`complaints-review`) is independent and defaults to the `--resource` value
if you do not pass `--dist`. The script deliberately does NOT touch the human decisions below.

## 4. The human decisions (the script can't make these)

1. **Region / residency.** Set the Terraform `region` / tfvars to your in-country region.
   The build defaults to `asia-southeast1` (MAS / Singapore). See
   [`docs/runbook.md`](runbook.md).
2. **Identity / IdP.** `complaints-review` owns no login flow: end-user identity is the IAP-injected
   assertion (`gcp`/`platform`) or a seeded dev persona (`local`), and `onprem` is a
   client-IdP placeholder. Wire your IdP / IAP at the deployment layer and implement the
   `onprem` identity adapter for a sovereign deployment. See
   [`docs/embedding-and-identity.md`](embedding-and-identity.md).
3. **PII / jurisdiction pack.** Set `pii.jurisdictions` (and the matching env for the eval
   gate) so redaction and the `pii_safety` metric detect YOUR national identifiers, not just
   the SG NRIC / FIN. The patterns come from the shared `pii-kit`; add a pack version if your
   jurisdiction is not yet covered.
4. **Escalation policy.** Own the `policy:` settings for escalating flags, the high-severity set,
   statutory deadline window and vulnerability keywords. The defaults are reference values, and
   both API and agent paths receive the same injected policy.
5. **Reference data is fictional.** Every fixture and the golden dataset
   (`eval/datasets/golden_complaints.jsonl`) use obviously-fake ids and customers. Swap them
   for your own synthetic data. **Do not run against live customer data without your own
   legal, security and model-risk sign-off.**
6. **Eval golden set.** Rebuild `eval/datasets/` and the rubrics for your vertical: a fork
   inherits a green gate that measures the WRONG thing until you do. The gate structure is
   generic; the golden cases are yours.
7. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root),
   `infra/terraform/` (region pin, CMEK, VPC-SC, WORM log bucket), and the loopback-by-default
   binding before you expose anything.

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable GRC systems. Several concerns it *touches*
are owned by sibling platform services, and you should integrate rather than rebuild them (see
[`docs/faq/features-faq.md`](faq/features-faq.md) for the full map): the guardrail gateway
(`agent-guardrail-gateway`), the governed knowledge base (`enterprise-knowledge-base`), the agent registry (`agent-registry`), the AI-quality / eval
gate (`model-quality-gate`), observability + WORM audit (`agent-observability`), the human-review / maker-checker console (`human-review-console`,
the rule-R8 target), the compliance assistant (`compliance-advisory`), and the on-prem DLP gate (`onprem-dlp`). The
`platform` profile's adapters are already thin HTTP clients to those services.

## 6. Adoption checklist

- [ ] Ran `scripts/rename_fork.py`, recreated the venv, `make lint test eval` green.
- [ ] Set region + Terraform tfvars to your in-country region.
- [ ] Wired your IdP / IAP at the deployment layer; implemented the `onprem` identity adapter if going sovereign.
- [ ] Set `pii.jurisdictions` (+ the eval-gate env); `pii_safety` exercises your ids.
- [ ] Owned the escalation policy numbers with your compliance function and pinned them in a test.
- [ ] Replaced every synthetic fixture and the golden dataset.
- [ ] Rebuilt the eval golden set + rubrics for your vertical.
- [ ] Reviewed the deploy posture (Dockerfile, Terraform, bind address).
- [ ] Decided which sibling platform services you integrate vs stub.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
