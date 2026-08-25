# B6 Complaints & Conduct File Review : developer Makefile.
#
# The default dev/test profile is LOCAL: a WORKING offline stack (SQLite FTS5 retrieval,
# deterministic LLM, regex DLP, heuristic guardrail) that runs end to end with NO Google
# Cloud SDK installed. Override PROFILE=gcp for the managed stack, or PROFILE=onprem for
# the fail-fast Google Distributed Cloud migration placeholders.

PYTHON      ?= python3
PIP         ?= pip
PROFILE     ?= local
SRC         := src/complaints_review
TESTS       := tests
API_APP     := complaints_review.api.app:app
API_HOST    ?= 127.0.0.1  # no-auth local dev binds loopback; override deliberately
API_PORT    ?= 8095
UI_DIR      := ui
TF_DIR      := infra/terraform
DEMO_PORT   ?= 8096
DEMO_OUT    ?= demo_out
# The demo scripts the gate lints. The renderer is in this list because the served
# self-test and the browser walkthrough now both read the evidence hooks it emits, so it
# is gate-relevant code, not a scratch script.
DEMO_SCRIPTS := scripts/demo_selftest.py scripts/portability_demo.py scripts/render_complaints_ui.py

export COMPLAINTS_PROFILE := $(PROFILE)

.DEFAULT_GOAL := help
.PHONY: help install install-demo install-gcp lock fmt lint test eval check ui-install ui-check run-local run-api run-ui demo demo-server demo-selftest demo-browser tf-plan clean

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install the package + dev tooling (NO GCP SDK : local/test profile).
	$(PIP) install -e ".[dev]"

install-demo: ## Install the pinned headless-browser extra, then fetch its browser binary.
	$(PIP) install -e ".[dev,demo]"
	$(PYTHON) -m playwright install chromium

install-gcp: ## Install with the managed-stack extra (google-adk, genai, documentai, ...).
	$(PIP) install -e ".[gcp,dev]"

lock: ## Recompile every lockfile from pyproject.toml and restore the tag = commit headers.
	$(PYTHON) scripts/lock.py

fmt: ## Auto-format and auto-fix lint issues.
	ruff format $(SRC) $(TESTS) eval
	ruff check --fix $(SRC) $(TESTS) eval

lint: ## Lint (ruff) and type-check (mypy).
	ruff check $(SRC) $(TESTS) eval $(DEMO_SCRIPTS)
	ruff format --check $(SRC) $(TESTS) eval $(DEMO_SCRIPTS)
	mypy $(SRC)

test: ## Run unit + contract tests on the local profile (no GCP SDK required).
	COMPLAINTS_PROFILE=local pytest -m 'not integration' -q

eval: ## Run the A4 eval gate (categorisation / groundedness / citations / pii_safety).
	$(PYTHON) eval/run_eval.py

portability: ## Execute the bounded offline/profile portability proof.
	PYTHONPATH=src $(PYTHON) scripts/portability_demo.py

check: lint test eval demo-selftest portability ## The full offline Python gate. Must be green to land.

demo-selftest: ## Prove the real presenter states and evidence hooks cannot rot silently.
	PYTHONPATH=src:tests:scripts $(PYTHON) scripts/demo_selftest.py

demo-browser: ## Drive the SERVED presenter demo through a real headless browser ([demo] extra).
	COMPLAINTS_PROFILE=local pytest tests/browser -q -rs

ui-install: ## Install the console's pinned dependencies from the committed lockfile.
	npm ci --prefix $(UI_DIR)

ui-check: ## The console gate: types, CSP unit tests, a real build, then a REAL hydration proof.
	npm --prefix $(UI_DIR) run lint
	npm --prefix $(UI_DIR) test
	NEXT_TELEMETRY_DISABLED=1 npm --prefix $(UI_DIR) run build
	npm --prefix $(UI_DIR) run assert-hydratable

run-local: ## End-to-end offline smoke: review a complaint under the local profile.
	COMPLAINTS_PROFILE=local complaints-review review CMP-LOCAL-001 \
		--narrative "The branch sold me a structured investment product I did not understand and I am a vulnerable customer." \
		--product "structured investment product" --channel branch --received 2026-06-01

demo: ## Offline demo: review the synthetic queue and render static audit-first HTML.
	PYTHONPATH=src:tests $(PYTHON) scripts/complaints_demo.py $(DEMO_OUT)/complaints_demo.json
	PYTHONPATH=src:tests $(PYTHON) scripts/render_complaints_ui.py $(DEMO_OUT)/complaints_demo.json $(DEMO_OUT)
	@echo "open $(DEMO_OUT)/index.html"

demo-server: ## Live, click-through demo server (offline) on :$(DEMO_PORT).
	PYTHONPATH=src:tests $(PYTHON) scripts/complaints_demo_server.py --port $(DEMO_PORT)

run-api: ## Run the FastAPI service (PROFILE=$(PROFILE)).
	uvicorn $(API_APP) --host $(API_HOST) --port $(API_PORT) --reload

run-ui: ## Run the React / Next.js UI (dev server).
	cd $(UI_DIR) && npm install && npm run dev

tf-plan: ## Terraform plan for the asia-southeast1 infrastructure.
	cd $(TF_DIR) && terraform init -input=false && terraform plan

clean: ## Remove caches and build artefacts.
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
