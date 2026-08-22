# Demo scripts - Complaints & Conduct File Review

All scripts are SDK-free and run against the in-process `local` stack (no Google Cloud,
no API key). They force `COMPLAINTS_PROFILE=local` with ephemeral in-memory stores, so a
run is deterministic and never reads or pollutes a persistent `~/.complaints_review` DB.
Run them from the repo root with the domain package and test fixtures on the path:

```bash
export PYTHONPATH=src:tests
```

| Script | What it does |
|--------|--------------|
| `complaints_demo.py` | Reviews a synthetic intake queue of 3 complaint files end to end and writes the artifact JSON (one entry per file; the prompt-injection file is recorded as blocked). |
| `render_complaints_ui.py` | Renders that JSON into static audit-first HTML pages (one per file + an intake-queue index) for screenshots. |
| `complaints_demo_server.py` | A **live, click-through** server that reviews the *real* queue one file per click and renders the audit-first UI. |
| `complaints_demo_playwright.py` | A **presenter-controlled** Playwright walkthrough of the live server: it narrates each step and waits for you to press Enter before performing it. |

## Static screenshots

```bash
python scripts/complaints_demo.py complaints_demo.json
python scripts/render_complaints_ui.py complaints_demo.json ./out   # ./out/complaint-*.html, index.html
# or, in one step:
make demo                                                           # writes ./demo_out/
```

## Live, presenter-controlled demo

Two terminals:

```bash
# 1) the live demo server  (http://localhost:8096 - separate from the API on :8095)
PYTHONPATH=src:tests python scripts/complaints_demo_server.py

# 2) the guided walkthrough  (a real Chrome window opens)
pip install playwright && playwright install chromium      # one-time
python scripts/complaints_demo_playwright.py
```

The walkthrough is **paced by you**: it prints what the next step will do, waits for you to
press **Enter**, then clicks **Next &#9654;** and spotlights the panel to look at. The four
steps are: intake queue -> File 1 (mis-selling, vulnerable customer, deadline risk) ->
File 2 (recent fees complaint, leaner flags) -> File 3 (prompt-injection, blocked by the
safety pipeline).

You can also just open `http://localhost:8096` and click **Next &#9654;** / **Restart** by
hand - the server holds the live service, so the buttons drive the same real review flow.

Point the walkthrough at the real Next.js console instead of the demo server by setting
`DEMO_URL` (the spotlight/Next-button selectors target the demo server, so for the live
console drive it by hand; `DEMO_URL` is most useful for re-pointing at a different port).

Useful environment overrides for `complaints_demo_playwright.py`:

| Var | Default | Purpose |
|-----|---------|---------|
| `DEMO_URL` | `http://127.0.0.1:8096` | server base URL |
| `HEADLESS=1` | off | run without a window (self-test / recording) |
| `DEMO_AUTO=1` | off | don't wait for Enter - advance automatically |
| `SLOWMO_MS` | `250` headed | per-action slow motion |
| `CHROME_PATH` | - | explicit Chromium/Chrome binary |
| `lock.py` | Compiles both lockfiles and puts the header back, because `uv pip compile` REPLACES the output file: it writes its own two-line provenance comment and destroys the `tag = commit` map the pin tests check against. `make lock` runs this rather than uv directly. |

> `playwright` is a **demo-time** dependency only. It is never added to the package core or
> the `[gcp]` extra; install it ad hoc as shown above.
