# Runbook · `complaints-review` Complaints & Conduct File Review

Operational notes for running and deploying `complaints-review`.

## Profiles

| Profile | When | What it binds |
|---------|------|----------------|
| `onprem` | local dev, CI, tests | placeholder stubs (no Google Cloud SDK needed) |
| `platform` | inside the full platform | HTTP clients to the shared `agent-guardrail-gateway` to `agent-observability` services |
| `gcp` | standalone managed deploy | Document AI, Agent Search, Gemini, Model Armor, DLP, Cloud Logging, Cloud Trace, Gen AI evals |

Set `COMPLAINTS_PROFILE` (env) or `profile:` in `config/settings.yaml`. Defaults to `local`
(the SDK-free offline stack) when unset; production sets `COMPLAINTS_PROFILE=gcp` explicitly.

## Local run

```bash
. .venv/bin/activate
export COMPLAINTS_PROFILE=onprem
complaints-review serve --port 8095        # FastAPI; or: make run-api
# in another shell:
curl -s localhost:8095/healthz
```

The `onprem` profile will raise on any command that touches an adapter (it has only stubs);
use it to exercise the API surface and the health/agent-card endpoints, and the test suite
to exercise the pipeline with fakes.

## Deploy (gcp profile)

1. Provision infra: `cd infra/terraform && terraform init && terraform apply` (review the
   irreversible WORM lock first). Export the outputs into the runtime environment (see
   `infra/terraform/README.md`).
2. Build and push the image (`Dockerfile`), or deploy the ADK agent to Agent Runtime with
   the Agent Platform SDK (see `src/complaints_review/agent/root_agent.py`).
3. Set `COMPLAINTS_PROFILE=gcp` and the `COMPLAINTS_*` env vars (`.env.example`).
4. Run the eval gate against the live evaluator: `python eval/run_eval.py --use-gcp`.

## Health and observability

- `GET /healthz` reports status, active profile and region.
- Traces go to Cloud Trace (message content OFF). Token usage is recorded as span
  attributes for FinOps.
- Audit records go to the locked WORM Cloud Logging bucket (~7-year retention). Records are
  already redacted; no raw PII is ever written.

## Common issues

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| CLI exits with code 2 naming a migration target | running the `onprem` profile, which has placeholder adapters | switch to `gcp` / `platform`, or implement the on-prem adapter |
| `RetrievalEmptyError` | `enterprise-knowledge-base` returned no policy passages for the complaint | check the `enterprise-knowledge-base` corpus / ACL principals for the actor |
| `GuardrailBlockedError` | Model Armor / `agent-guardrail-gateway` blocked the input or the draft | review the flagged content; the request is audited as BLOCKED |
| Import error mentioning `google-cloud-*` | running the `gcp` profile without the `[gcp]` extra | `pip install -e ".[gcp,dev]"` |

## On-prem migration

See `docs/onprem-migration.md`.
