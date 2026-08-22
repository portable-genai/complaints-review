# Portability FAQ

For architecture, cloud-governance, and exit-planning teams. The claim this repo makes is
"no vendor lock-in" (General Principle P-02): the whole stack migrates by configuration, not
by a rewrite. Cross-references: [`ARCHITECTURE.md`](../../ARCHITECTURE.md),
[`docs/onprem-migration.md`](../onprem-migration.md), [`DEMO.md`](../../DEMO.md).

### What does "portable" actually mean here?

Two axes with a rehearsed exit today, and a third that is proven at the interface. **Compute:**
the whole stack rebinds by a one-line profile change with no `domain/` edits. **Data:** the
audit trail exports to an open, documented JSONL format and reloads elsewhere with the hash
chain re-verified. **Identity:** identity resolves across hosts by an adapter swap (seeded
persona / IAP assertion / client-IdP placeholder), not a rewrite. Note that an *executable*
one-command portability proof (a `scripts/portability_demo.py` behind an exit code, the Doc1
pattern) is a **known open item**, tracked as check F3 in
[`docs/practices-audit.md`](../practices-audit.md); today the guarantees are proven by the
contract tests and the audit export/restore path rather than by a single script.

### How does the profile switch work?

The pure-domain core speaks only to `typing.Protocol` **ports**; four **adapter families**
implement them, and `config/settings.yaml` binds one adapter per port per profile. Setting
`COMPLAINTS_PROFILE` (or `profile:` in the settings) rebinds the entire stack:

- `local`: a WORKING offline stack (SQLite FTS5 knowledge base, deterministic LLM, regex
  DLP redactor, heuristic guardrail, hash-chained append-only audit, no-op tracer, local
  document parser). No Google Cloud SDK. The default for dev/test/CI.
- `gcp`: real managed services (Document AI, Agent Search, Gemini, Model Armor, DLP, Cloud
  Logging WORM, Cloud Trace, Gen AI Evals).
- `platform`: thin HTTP clients delegating to the sibling horizontal-platform and
  de-risking services.
- `onprem`: fail-fast placeholder stubs that still satisfy every Protocol (the sovereign-exit
  target); a primary CLI command exits non-zero by design until the on-prem work is done.

No `domain/` code changes across any of these. The contract test
(`tests/contract/test_port_parity.py`) proves both `local` and `onprem` construct and satisfy
every port with a single `Settings` argument and no cloud SDK installed, and
`tests/contract/test_behavioral_parity.py` proves the `local` adapter and the real `platform`
httpx delegate yield the identical domain object at the redaction and knowledge-base
boundaries.

### Is the domain really free of a kernel/vertical split, and does that hurt portability?

Not for the profile-swap guarantee. The `domain/` package is pure stdlib and imports no cloud
SDK or framework, so it moves across hosts unchanged regardless of internal structure. A
formal `domain/kernel.py` split (separating the vertical-neutral machinery from the complaints
artifacts, so a *different vertical* can reuse the kernel cleanly) is a **known open item**
(check A7 in [`docs/practices-audit.md`](../practices-audit.md)); it improves reuse for a fork
into another document-diligence vertical, but the port layer already gives you the
where-it-runs portability for free.

### How do we get our data out?

The `local` audit store wraps the shared `hex_service_kit.audit.HashChainedAuditLog`, which
exports to JSON Lines (one `{seq, prev_hash, entry_hash, event}` object per line) and reloads
into a fresh store with the hash chain re-verified line by line (`verify_chain()`). Records
rehydrate to first-class `AuditEvent` objects via `domain/serialization.py`. The exit story
for the audit trail is "copy the JSONL file", not "migrate a product". Case artifacts and the
four review outputs serialize the same way via `to_jsonable`.

### Is on-prem / sovereign deployment real or aspirational?

The `onprem` adapters are deliberate fail-fast placeholders (they raise `NotImplementedError`)
that nonetheless satisfy every Protocol and construct with a single `Settings` arg, so the
*interface contract* for a sovereign migration is proven and enforced by CI today. The actual
on-prem implementations are the migration work, scoped in
[`docs/onprem-migration.md`](../onprem-migration.md). This repo is not the sovereign-exit
*planner* (that is the sibling **Rgc9** `operational-resilience-mapping`: APRA CPS 230, MAS/HKMA
outsourcing); this repo is one of the systems whose exit that planner reasons about.

### Does residency compromise portability?

No: residency is a deploy-time pin (`infra/terraform/` fixes the region to `asia-southeast1`
with a fail-fast validation, plus CMEK, a VPC-SC perimeter and a WORM log bucket), and
portability is the ability to change *where* the stack runs by configuration. They are
orthogonal. A second region or enterprise is a tfvars change, not a fork. Residency
enforcement overlaps with the sibling **Rsk3** `architecture-validator` (a CI gate for region
violations), which a fork should run rather than re-implement; note that an in-repo offline
Terraform `fmt`/`validate` check is itself a small open item (D5).

### What is NOT yet portable / executable?

- The one-command executable portability proof (`scripts/portability_demo.py`, F3) is not yet
  built; parity is proven by the contract tests instead.
- The `onprem` adapters are interface-complete placeholders, not working sovereign
  implementations; that is the migration work in `docs/onprem-migration.md`.
