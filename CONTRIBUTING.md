# Contributing · Doc6 Complaints & Conduct File Review

Thanks for helping improve Doc6. This is an engineering-portfolio reference repo: keep it
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
python eval/run_eval.py          # the Hrz4 / P-08 eval gate
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
