# Demo guide - Doc6 Complaints & Conduct File Review

Step-by-step scripts for demoing Doc6 two ways:

- **Demo A - Audit-first complaint review on a laptop** (the headline flow): a conduct
  officer works an intake queue of synthetic complaint files. For each file the system
  redacts PII, screens it, retrieves policy and regulatory guidance, and produces a cited
  summary, a categorisation with conduct flags, and a draft regulator/customer response.
  Runs **fully offline** (no cloud, no API key).
- **Demo B - The same review on the managed GCP stack**: the same artifacts produced
  against real Document AI / Agent Search / Gemini / Model Armor / DLP in
  `asia-southeast1`, served over REST and through the Next.js console.

> The synthetic complaint data is **fictional** (clearly-fake names, NRICs and emails). Do
> not run against live customer data without your own legal, security and model-risk
> sign-off.

---

## 0. Prerequisites

| Need | Demo A (local) | Demo B (GCP) | Notes |
|------|:--:|:--:|-------|
| `git` | yes | yes | clone the repo |
| **Python 3.12+** | yes | yes | the package pins `>=3.12` |
| Node.js 18+ and npm | for the UI / Playwright | for the UI | only if you show the browser console |
| **Playwright** (`pip install playwright` + `playwright install chromium`) | for the guided walkthrough | n/a | Demo A's presenter walkthrough |
| A GCP project + `gcloud` | n/a | yes | billing enabled; `asia-southeast1` available |
| Terraform | n/a | yes | provisions Document AI, DLP, Model Armor, WORM bucket, CMEK |
| Cloud KMS key (regional) | n/a | yes | CMEK; set `COMPLAINTS_KMS_KEY` |

Install/setup references (read these once):

- Local install and profiles -> [README "Quickstart"](README.md#quickstart-no-google-cloud-sdk-required)
- GCP install and deploy -> [`docs/runbook.md`](docs/runbook.md#deploy-gcp-profile)
- Running the surfaces (API / CLI / UI) -> [README "HTTP API"](README.md#http-api) and [README "CLI"](README.md#cli)
- The demo scripts -> [`scripts/README.md`](scripts/README.md)
- The UI console -> [`ui/README.md`](ui/README.md)
- Config (`${ENV_VAR}` resolved at load) -> [`config/settings.yaml`](config/settings.yaml)

---

## 1. Common setup (both demos)

```bash
git clone https://github.com/portable-genai/complaints-review.git
cd complaints-review

python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # core + dev tooling (NO google-cloud-* packages)

# Sanity check the offline stack before presenting:
export COMPLAINTS_PROFILE=local
make lint test                   # ruff + mypy + pytest (all local, no cloud)
```

See [README "Quickstart"](README.md#quickstart-no-google-cloud-sdk-required) for details.

---

## 2. Demo A - Audit-first complaint review (local, offline)

The review pipeline runs on the in-process `local` adapter stack (SQLite FTS5 retrieval,
deterministic LLM, regex DLP, heuristic guardrail, append-only audit), so it needs **no
Google Cloud and no API key** - ideal for a laptop demo. Four ways to present it, in order
of polish.

### 2.1 Guided, presenter-controlled walkthrough (recommended)

A real browser opens; the script narrates each step and **waits for you to press Enter**
before performing it, so you control the pace. (One-time: `pip install playwright &&
playwright install chromium`.)

```bash
# Terminal 1 - the live demo server (http://localhost:8096)
source .venv/bin/activate
PYTHONPATH=src:tests python scripts/complaints_demo_server.py

# Terminal 2 - the guided walkthrough (a Chrome window opens)
source .venv/bin/activate
python scripts/complaints_demo_playwright.py
```

You'll step through, pressing Enter each time:

1. **Intake queue** - three synthetic complaint files awaiting review; no artifacts yet.
2. **File 1** - a bereaved, vulnerable customer alleging mis-selling of a structured
   investment product, received weeks ago -> categorisation **mis-selling / HIGH**, **two
   deterministic conduct flags** (vulnerable customer + deadline risk), a cited draft
   response. PII (NRIC, email, phone) is redacted before any model/KB call.
3. **File 2** - a recent fees complaint, within the 21-day handling window -> same
   audit-first treatment with a **leaner flag set** (no deadline-risk, no vulnerable flag).
4. **File 3** - a prompt-injection email -> **blocked** by the input guardrail and audited
   as BLOCKED, rather than emitting an ungrounded artifact.

**What to point at on screen:** the HUMAN-REVIEW banner (maker-checker, P-06), the
categorisation pill and severity, the conduct-flags panel shrinking between File 1 and
File 2, the source-and-page **citation chips** on every artifact, the draft response
marked DRAFT / never sent, and the BLOCKED envelope on File 3. Full options (`SLOWMO_MS`,
`HEADLESS`, `CHROME_PATH`, ...) are in [`scripts/README.md`](scripts/README.md).

### 2.2 Manual, click-through (no Playwright)

Run only the server and drive it yourself in any browser:

```bash
PYTHONPATH=src:tests python scripts/complaints_demo_server.py     # http://localhost:8096
```

Open `http://localhost:8096` and click **Next &#9654;** to review the next file, **Restart**
to reset. Same four steps as above.

Or drive the **real console** against the **real API** offline (two terminals):

```bash
make run-api PROFILE=local      # FastAPI on :8095, profile=local
make run-ui                     # Next.js console on http://localhost:3000
```

Then in the console paste a narrative (e.g. *"I am a recently bereaved and vulnerable
customer. The branch sold me a structured investment product I did not understand."*),
product `structured investment product`, channel `branch`, and click **Review complaint**.

### 2.3 Static artifacts (slides / screenshots)

Generate the audit-first pages and JSON without a browser:

```bash
PYTHONPATH=src:tests python scripts/complaints_demo.py complaints_demo.json        # prints the per-file summary
PYTHONPATH=src:tests python scripts/render_complaints_ui.py complaints_demo.json ./out
# -> ./out/index.html, complaint-CMP-2026-0001.html, complaint-CMP-2026-0002.html, complaint-CMP-2026-9999.html
# or, in one step:
make demo                                                                          # writes ./demo_out/
```

### 2.4 One-shot review via the CLI (quick variant)

If you only want to show a single cited review (not the whole queue):

```bash
export COMPLAINTS_PROFILE=local
complaints-review review CMP-LOCAL-001 \
  --narrative "The branch sold me a structured investment product I did not understand and I am a vulnerable customer." \
  --product "structured investment product" --channel branch --received 2026-06-01
# or simply:
make run-local
```

---

## 3. Demo B - Complaint review on the managed GCP stack

Shows the same domain producing the same cited artifacts against **real managed services**
in `asia-southeast1`. Follow [`docs/runbook.md`](docs/runbook.md#deploy-gcp-profile) for the
authoritative deploy steps; the short version:

### 3.1 GCP setup

```bash
source .venv/bin/activate
pip install -e ".[gcp,dev]"                 # adds google-adk, google-genai, documentai, dlp, ...

export GOOGLE_CLOUD_PROJECT=your-sg-project
export COMPLAINTS_PROFILE=gcp
export COMPLAINTS_KMS_KEY="projects/.../locations/asia-southeast1/keyRings/.../cryptoKeys/..."
gcloud auth application-default login
```

### 3.2 Provision infra (one-time)

```bash
make tf-plan          # review the plan - the WORM bucket lock is IRREVERSIBLE
cd infra/terraform && terraform apply && cd ../..
# Export the outputs the app reads (see docs/runbook.md):
export COMPLAINTS_DOCAI_PROCESSOR="$(terraform -chdir=infra/terraform output -raw documentai_processor_id)"
export COMPLAINTS_DLP_INSPECT_TEMPLATE="$(terraform -chdir=infra/terraform output -raw dlp_inspect_template)"
export COMPLAINTS_DLP_DEIDENTIFY_TEMPLATE="$(terraform -chdir=infra/terraform output -raw dlp_deidentify_template)"
```

Details and gotchas (region fail-fast, key rotation, retention): [`docs/runbook.md`](docs/runbook.md).

### 3.3 Run and show

```bash
make run-api          # FastAPI on :8095, profile=gcp
```

Then demo any surface (see [README "HTTP API"](README.md#http-api)):

The request body carries no `actor`: identity is resolved server side from the verified
`Principal` (an IAP assertion in the gcp/platform profiles, or a seeded dev persona selected via the
`X-Dev-Persona` header in the local profile). See [docs/embedding-and-identity.md](docs/embedding-and-identity.md).

```bash
# REST - produce a full cited review. In local mode, pick a seeded persona with X-Dev-Persona
# (omit it to use the default persona). List personas with: curl -s localhost:8095/v1/personas
curl -s localhost:8095/v1/review \
  -H 'content-type: application/json' -H 'X-Dev-Persona: analyst' -d '{
  "file": {
    "id": "CMP-2026-0001",
    "customer_ref": "CUST-FAKE-001",
    "product": "structured investment product",
    "channel": "branch",
    "received_date": "2026-05-01",
    "narrative": "I am a recently bereaved and vulnerable customer. The branch sold me a structured investment product I did not understand and I want my money back."
  }
}' | python -m json.tool

# Just the summary, or just the draft response (a draft, never sent):
curl -s localhost:8095/v1/summary        -H 'content-type: application/json' -d @file.json | python -m json.tool
curl -s localhost:8095/v1/draft-response -H 'content-type: application/json' -d @file.json | python -m json.tool

# Seeded dev personas (local profile only), agent card, health
curl -s localhost:8095/v1/personas | python -m json.tool
curl -s localhost:8095/.well-known/agent-card.json | python -m json.tool
curl -s localhost:8095/healthz
```

Or the browser console (talks to the API on :8095) - see [`ui/README.md`](ui/README.md):

```bash
make run-ui           # http://localhost:3000
```

**What to highlight:** every claim carries a source-and-page **citation**; customer PII is
redacted before any model/index/audit call; the draft response is **always** a draft and
the review is **always** flagged for human review (maker-checker, P-06); everything stays
in `asia-southeast1` with CMEK ([README "Architecture at a glance"](README.md#architecture-at-a-glance)).

---

## 4. Talking points

- **Audit-first output.** Summary, categorisation, conduct flags and the draft response
  are each cited to the exact policy clause or regulatory paragraph, so a reviewer can
  verify every claim. A conduct decision a reviewer cannot trace to a page is worthless.
- **The system does the safety-critical parts deterministically.** PII redaction, the
  guardrail screen, and the mandatory conduct flags (vulnerable-customer keyword, breach
  of the 21-day handling window) are pure functions an auditor can replay; the LLM only
  narrates and drafts. Deterministic flags are authoritative - the model cannot remove them.
- **It refuses rather than guesses.** Empty retrieval or a guardrail block raises and is
  audited as BLOCKED; the pipeline never emits a partial, ungrounded or unsafe artifact.
- **Guardrails hold.** Redact-before-everything, WORM audit, governed Hrz2 retrieval scoped
  by the actor's ACL, maker-checker on every review, and a draft that the system never
  sends - a human reviews and sends it (P-06 / R1).

---

## 5. Troubleshooting and cleanup

| Symptom | Fix |
|---------|-----|
| `python3.12: command not found` | Install Python 3.12+; the package pins `>=3.12`. |
| Playwright: "executable doesn't exist" | `playwright install chromium`, or set `CHROME_PATH=/path/to/chrome`. |
| No display for the headed walkthrough | Use §2.2 (manual browser) on a machine with a display, or `HEADLESS=1 DEMO_AUTO=1 python scripts/complaints_demo_playwright.py` to self-run. |
| "Cannot reach the demo server" | Start §2.1 Terminal 1 first; or set `DEMO_URL` if you changed `--port`. |
| Port 8096 / 8095 in use | `python scripts/complaints_demo_server.py --port 9000` (then `DEMO_URL=http://127.0.0.1:9000`); API port via `make run-api API_PORT=...`. |
| Exit code 2 from a CLI command | You're on `COMPLAINTS_PROFILE=onprem` (fail-fast). Use `local` (Demo A) or `gcp` (Demo B). |
| Browser console shows a network error | The API must be running (`make run-api PROFILE=local`) and CORS allows `http://localhost:3000` by default. |
| GCP deploy / region / VPC-SC errors | See [`docs/runbook.md` "Common issues"](docs/runbook.md#common-issues). |

**Stop / clean up:** Ctrl-C the demo server, `make run-api` and `make run-ui`. The demo
scripts use ephemeral in-memory stores, so nothing persists. For GCP, scale the deployment
to zero or remove the app SA's model-access role - the audit trail remains intact (see
[`docs/runbook.md`](docs/runbook.md)). `make clean` removes local caches/artefacts; the
demo output lives under `demo_out/` (git-ignored).
