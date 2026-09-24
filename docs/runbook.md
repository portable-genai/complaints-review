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

## Runtime controls

`COMPLAINTS_GUARDRAIL`, `COMPLAINTS_PII_REDACTION` and `COMPLAINTS_REVIEW_ROUTING` each switch
one cheap control: the guardrail port (Model Armor under `gcp`, `agent-guardrail-gateway` under
`platform`, the heuristic locally), the redaction port (DLP under `gcp`, the gateway under
`platform`, regex locally) and the review hand-off to `human-review-console`. Each is read once
at startup in three states: unset is on, `true`/`false` (or `on`/`off`, `1`/`0`, `yes`/`no`)
wins, and an emptied or unrecognised value refuses to boot, naming the variable. Off binds an
adapter that does nothing, and a process with any control off logs one warning at startup
naming each.

Under `gcp` or `platform`, a control that is on must be able to work, so the process refuses to
boot when:

- review routing is on and `HUMAN_REVIEW_URL` is not set. Name the console, or set
  `COMPLAINTS_REVIEW_ROUTING=off` to run without routing. Unsetting `HUMAN_REVIEW_URL` does not
  pause routing; the switch does.
- the guardrail is on, bound to Model Armor, and the template id is empty. Name one, or set
  `COMPLAINTS_GUARDRAIL=off`.

What the controls did is on every response a user reads:

- `POST /v1/review` carries `review_routing`: `routed` (the console accepted the review),
  `failed` (the hand-off failed and the review is NOT in the console; logged at WARNING with
  the exception type, and the response still returns), `off` (routing is switched off) or
  `not_required`. The agent's `review_complaint` tool and the CLI's `review` command report
  the same value. The summary and draft endpoints hand nothing to the console, so they do not
  carry it.
- `/v1/review`, `/v1/summary` and `/v1/draft-response` carry `input_redacted: true` when
  redaction changed the complaint before the model saw it. The console says so.

The DLP inspect config (inline, and the Terraform inspect template) masks only `LIKELY`
findings, replaces a match with its info-type name (`[PERSON_NAME]`) rather than a run of `#`,
and excludes complaint vocabulary (regulators, dispute schemes, payment rails, card schemes)
from `PERSON_NAME`. The local redactor leaves an eight-digit amount after a currency code
(`SGD 90000000`) intact rather than masking it as a phone number.

## Common issues

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| CLI exits with code 2 naming a migration target | running the `onprem` profile, which has placeholder adapters | switch to `gcp` / `platform`, or implement the on-prem adapter |
| `RetrievalEmptyError` | `enterprise-knowledge-base` returned no policy passages for the complaint | check the `enterprise-knowledge-base` corpus / ACL principals for the actor |
| `GuardrailBlockedError` | Model Armor / `agent-guardrail-gateway` blocked the input or the draft | review the flagged content; the request is audited as BLOCKED |
| Import error mentioning `google-cloud-*` | running the `gcp` profile without the `[gcp]` extra | `pip install -e ".[gcp,dev]"` |
| Boot fails: "Review routing is on under profile 'gcp' but HUMAN_REVIEW_URL is not set" | no review console is named for a networked process | set `HUMAN_REVIEW_URL` to the `human-review-console` base URL, or `COMPLAINTS_REVIEW_ROUTING=off` |
| a review carries `review_routing: "failed"` | the console was unreachable or refused the hand-off; the review is NOT queued | read the WARNING "human-review hand-off failed: <exception type>", fix the console or credentials, and re-run the review |

## On-prem migration

See `docs/onprem-migration.md`.
