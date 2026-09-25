# Contributing · `complaints-review` Complaints & Conduct File Review

Thanks for helping improve `complaints-review`. This is an engineering-portfolio reference repo: keep it
internally consistent, production-grade in style, and green on the offline gate.

## Setup

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"          # no Google Cloud SDK needed for development
export COMPLAINTS_PROFILE=onprem
```

## The gate (must be green before you push)

```bash
ruff check src tests             # lint
ruff format --check src tests    # format
pytest -m 'not integration' -q   # unit + contract
mypy src                         # type-check (best-effort)
python eval/run_eval.py          # the `model-quality-gate` / P-08 eval gate
```

`make fmt` auto-formats and auto-fixes; `make lint`, `make test`, `make eval` mirror the
gate. CI runs exactly this on the `onprem` profile with no cloud credentials.

## Architecture rules (do not break these)

- **The domain stays pure.** `src/complaints_review/domain/` imports only the standard
  library and its own modules: no `google-cloud-*`, no ADK, no FastAPI, no httpx, no
  pydantic.
- **GCP imports are lazy.** Every `google-*` import in `adapters/gcp/*` (and ADK in
  `agent/*`) lives inside a method or under `TYPE_CHECKING`, never at module top level. The
  whole suite must import and run with no Google Cloud SDK installed.
- **Adapters take exactly `Settings`.** Every registered adapter is
  `def __init__(self, settings: Settings)`. The contract test enforces this.
- **New ports come with all three families.** A `gcp` adapter (lazy SDK), a `platform`
  client where a sibling service owns the capability, and an `onprem` stub that raises
  `NotImplementedError` (or a safe no-op for non-essential ports like tracing). Add the
  binding to `config/settings.yaml` and the Protocol to `tests/contract`.
- **The model port notes what answered, and samples per call.** After a successful call the
  `gcp` adapter calls `hex_service_kit.provenance.note_model(<the model id it called>)`, and
  `note_search()` only when an online search tool was attached to that call; the `local` stub
  notes `deterministic-offline-stub`; the `live` adapter needs nothing, the kit client notes
  itself. `api/app.py` emits them as `X-Answered-By` / `X-Search-Used` (and exposes both
  through CORS, since the console calls the service directly), and the console's pills show
  them. `LlmRequest.temperature` is `float | None`, and `None` means the adapter sends NO
  temperature. Pin `0.0` where the output is extracted, classified or compared (the summary
  and the categorisation); leave drafting free (the draft response). `generator_model` must be
  the model the adapter calls: there is no flag that swaps in another.
  Tests: `tests/unit/test_answer_provenance.py`.
- **Cite everything; never auto-send.** Conduct decisions carry page-level citations; the
  draft response is always a draft the system never sends (P-06 / R1).

## Markdown

Minimise em-dashes in markdown (use colons, commas, parentheses, or `n/a`). Validate every
mermaid diagram with `mmdc` before committing.

## Commits

Keep commits focused and the gate green. Synthetic data must stay obviously fictional.

## Adding an adapter or sub-service

For an adapter, update the typed port, implement every declared profile family, update
`config/settings.yaml`, and extend `tests/contract/test_port_parity.py` with set-equality
between ports and settings. For a sub-service, add the pure domain service, re-export it
from `domain/services.py`, wire it in `api/deps.py`, add one test per deterministic flag,
threshold, escalation, and replay case, add eval and audit/demo coverage, then update SPEC,
ARCHITECTURE, COMPLIANCE, runbook, model card, and changelog.
