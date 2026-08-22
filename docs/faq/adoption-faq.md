# Adoption FAQ

For an engineering lead forking this repo as their institution's base. The step-by-step is
[`docs/ADOPTING.md`](../ADOPTING.md); this answers the "will it hurt later?" questions.

### How do I rebrand it for my institution?

`scripts/rename_fork.py` rewrites the package name (`complaints_review`), the CLI entry point
(`complaints-review`), the `COMPLAINTS_` env prefix, the resource-id stem (`complaints-review`)
and the distribution name (`complaints-review`) in one pass (preview with
`--dry-run`, apply with `--yes`). Then recreate the venv, `pip install -e ".[dev]"`, and run
`make lint test eval`. The script does the mechanical rename; the human decisions (region,
IdP, PII pack, escalation policy, fixtures, eval golden set) are the checklist in
[`ADOPTING.md`](../ADOPTING.md).

### If several banks fork this, how does each take upstream fixes?

Track upstream via **git tags** (semver). The repo declares a **core-vs-adopter-owned boundary** (ADOPTING §2): upstream owns
`ports/`, `tests/contract/`, the eval harness mechanics, the hexagon wiring (`config.py`
`Container`) and CI; you own `config/settings.yaml` values, the local fixtures, the eval golden
set, `adapters/onprem/*`, and UI theming. Rebase your adopter-owned changes onto each release
rather than merging `main` continuously, so conflicts stay in files you were told to expect.

### How do I add a new outbound dependency (a new port)?

There is a fixed touch list, and the contract test fails loudly if you miss part of it
(`test_port_protocols_matches_settings_adapters`, a set-equality drift guard that fails in
BOTH directions): define the `@runtime_checkable` Protocol under `ports/`, re-export it from
`ports/__init__.py`, implement one adapter per profile (at least `local` and `onprem`), bind
all of them under `adapters:` in `config/settings.yaml`, add the port to `PORT_PROTOCOLS` in
the parity test, add a `cached_property` on the `Container`, and wire it in `api/deps.py`. See
[`CONTRIBUTING.md`](../../CONTRIBUTING.md).

### How do I add a new sub-service or output panel?

A sub-service is pure domain: add `domain/<name>_service.py` (stdlib only), re-export it from
`domain/services.py`, construct it in `api/deps.py`, and unit-test it. Keep the consequential
math deterministic and let the LLM only narrate / classify (the "deterministic domain service"
pattern). For an output panel, `scripts/render_complaints_ui.py` already renders the attached
artifacts; add a hook so the demo walkthrough can target it.

### How do I change the taxonomy (categories, conduct-flag kinds, severities)?

The domain vocabularies are `StrEnum`s (a member IS its wire value) and the engines are typed
on `str`, so you can extend the vocabulary without editing engine code, and serialized JSON
values are the enum strings. To replace a taxonomy wholesale for a different vertical, edit the
enums in `domain/models.py` and the label maps in the UI.

### How do I retune the escalation policy without touching code?

Honest answer: not yet fully. Today the compliance-tunable values are **module constants**,
the escalating-flags and high-severity sets in `domain/review_policy.py`, and the statutory
deadline window (`_DEADLINE_DAYS`) and vulnerability keywords in
`domain/categorization_service.py`. Externalizing them into a `policy:` section of
`config/settings.yaml` (with a defaults-equal-reference override test, the Doc1 pattern) is a
**known open item**, tracked as check B4 in [`docs/practices-audit.md`](../practices-audit.md).
Until it lands, own those numbers by editing the constants (and add a test that pins your
values); do not assume a settings-reachable override exists.

### Will the demo rot after I diverge?

Be aware that a CI demo self-test does **not** exist here yet (check F2 in
[`docs/practices-audit.md`](../practices-audit.md)): there is no headless assertion of the
live demo state and no `test_demo_server.py`, so a refactor that breaks the walkthrough will
not fail the PR on its own. If the demo matters to your delivery, adding that self-test is a
recommended early step; the Doc1 base has one you can mirror.

### Does the CI run for my fork out of the box?

Yes. CI and the eval gate run on the `local`/`onprem` profiles with **no cloud credentials and
no org secrets**, so a fork's build is green immediately. You add secrets only when you wire
the `gcp`/`platform` profiles. Note the eval gate measures the *reference* vertical until you
rebuild the golden set (`eval/datasets/golden_complaints.jsonl`); that is an explicit adoption
step, not a silent pass.
