"""Local deployment profile adapters — a WORKING, offline laptop stack.

The ``local`` profile is the third deployment option alongside ``gcp`` (managed
Google Cloud services) and ``onprem`` (fail-fast Google Distributed Cloud migration
placeholders). Unlike ``onprem``, every adapter here is a *real, deterministic*
implementation that runs the whole B6 complaint-review pipeline end to end with **no
Google Cloud, no API key, and no running emulators by default**:

* Knowledge base (governed RAG) -> a ``sqlite3`` **FTS5** index over the policy /
  regulatory passages (BM25 rank), with page-level citations.
* LLM -> a deterministic, schema-driven generator (no model, no network).
* Guardrail -> a heuristic that blocks prompt-injection / jailbreak text.
* PII redaction -> regex de-identification (SG NRIC/FIN, emails, SG phone numbers).
* Audit -> an append-only local store (SQLite or in-memory), read-back supported.
* Tracer -> no-op spans.
* Document extraction -> a local plain-text / pypdf parser.
* Evaluation -> delegates to the in-repo offline eval gate.
* Registry / tool catalog -> in-process stores (a laptop runs one app, not the whole
  platform), seedable and deterministic.

Everything is **seedable** so the test suite stays deterministic, and the default code
path imports **no google-cloud package at module top level**. Optional higher-fidelity
local runs route to Google's official emulators when the standard ``*_EMULATOR_HOST``
env vars are set (the google client is imported lazily, only on that branch); see
:mod:`complaints_review.adapters.local._emulator`.
"""
