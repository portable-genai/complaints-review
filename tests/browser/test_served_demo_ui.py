"""F2: the presenter demo is driven through a real headless browser, not a string.

``scripts/demo_selftest.py`` starts the real server and reads the served bytes, which
covers the server/renderer path browserlessly. This file closes the other half: a pinned
headless Chromium loads the SERVED pages, clicks the presenter's own ``Next`` button, and
reads every asserted figure back out of the LIVE DOM through the stable ``data-*``
evidence hooks. Nothing here is compared against hard-coded prose; every expectation is
recomputed from the running :class:`DemoSession`.

Playwright is pinned in the ``[demo]`` extra and the browser binary is a network download,
so a fork's day-one offline gate (D3) must not depend on either: with nothing set, an absent
extra or an unlaunchable browser still skips LOUDLY (``-rs``, as ``make demo-browser`` runs
it) rather than passing silently. That default is a courtesy to a clean checkout, not a
licence. Set ``DEMO_BROWSER_REQUIRED`` and the same conditions FAIL instead, because a suite
that declines to run reports exactly the green a suite that ran reports, and a runner that
installed a browser on purpose is the one place that must never be handed a skip.
``CHROME_PATH`` names the binary to drive, the same read ``scripts/complaints_demo_playwright.py``
makes, so a runner carrying its own chromium is driven rather than quietly ignored.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

import pytest

from complaints_review.envread import boolean_setting

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

#: Which local Chrome or Chromium binary Playwright drives, the same read
#: ``scripts/complaints_demo_playwright.py`` makes. Unset means Playwright's own pinned download,
#: because ``executable_path=None`` is Playwright's own default, so honouring the variable changes
#: nothing for anyone who leaves it alone. It was NOT honoured here before, and a runner that ships
#: a distribution chromium and exports ``CHROME_PATH`` was therefore ignored: the launch reached
#: for a download that was not there and the suite skipped. Two-state on purpose, and classified
#: posture-free alongside the other ``CHROME_PATH`` read: it names a program on the runner's own
#: machine, never a host, an origin or an audience, and an unusable value fails the launch loudly
#: rather than quietly widening anything.
CHROME_PATH = os.environ.get("CHROME_PATH") or None

#: Whether a browser was EXPECTED here. Three states, never two:
#:
#: * UNSET: nobody said one was expected, so a launch failure may still skip and a day-one
#:   offline checkout with no ``[demo]`` extra keeps a clean gate;
#: * SET AND EMPTY: an intent WAS expressed and it names nothing, so ``boolean_setting``
#:   refuses rather than guessing which way it pointed;
#: * SET AND TRUE: a browser was promised, so an absent extra or a failed launch FAILS.
#:
#: The last state is why this variable exists. A suite that declines to run reports exactly
#: the green a suite that ran reports, so the one place this evidence must never be allowed to
#: skip is the place that installed a browser on purpose.
BROWSER_REQUIRED = boolean_setting("DEMO_BROWSER_REQUIRED")


def _playwright_api() -> Any:
    """The pinned Playwright API, skipping only when nothing promised a browser."""
    if BROWSER_REQUIRED:
        # A browser was promised, so a missing [demo] extra is a broken promise. Let the
        # ImportError travel instead of converting it into a green tick.
        return importlib.import_module("playwright.sync_api")
    return pytest.importorskip(
        "playwright.sync_api", reason="the pinned [demo] extra is not installed"
    )


playwright_api = _playwright_api()


def _no_browser(reason: str) -> NoReturn:
    """Skip only when nothing said a browser was expected; FAIL when something did.

    An unconditional ``pytest.skip`` here was the defect this file exists to remove, one
    layer in: a suite that declines to run reports the same green as one that ran, so the
    runner that installed a browser on purpose learned nothing from its own green tick.
    """
    if BROWSER_REQUIRED:
        pytest.fail(
            "DEMO_BROWSER_REQUIRED is set, so a browser was expected here and this suite "
            f"must not skip. {reason}",
            pytrace=False,
        )
    pytest.skip(reason)


os.environ.setdefault("COMPLAINTS_PROFILE", "local")


def _load(name: str) -> ModuleType:
    for path in (str(SCRIPTS), str(ROOT / "tests")):
        if path not in sys.path:
            sys.path.insert(0, path)
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


renderer = _load("render_complaints_ui")
demo_queue = _load("complaints_demo")
demo_server = _load("complaints_demo_server")


@pytest.fixture(scope="module")
def served() -> Iterator[tuple[str, object]]:
    """The REAL demo server, on an ephemeral port, for the duration of the module."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), demo_server.Handler)
    server.session = demo_server.DemoSession()
    server.lock = threading.Lock()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server.session
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def page(served: tuple[str, object]) -> Iterator[object]:
    try:
        with playwright_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True, executable_path=CHROME_PATH)
            except Exception as exc:  # pragma: no cover - environment-dependent
                _no_browser(f"no pinned browser binary available: {exc}")
            context = browser.new_context()
            yield context.new_page()
            context.close()
            browser.close()
    except NotImplementedError as exc:  # pragma: no cover - environment-dependent
        _no_browser(f"playwright cannot run here: {exc}")


def _attr(page: object, selector: str) -> str:
    locator = page.locator(selector)
    assert locator.count() == 1, f"{selector} is not on the live page exactly once"
    name = selector.split("[", 1)[1].split("]", 1)[0]
    return locator.get_attribute(name)


def test_the_served_demo_walks_every_step_in_a_real_browser(page, served) -> None:
    base, session = served
    page.goto(f"{base}/restart", wait_until="load")

    steps = demo_server.STEPS

    for index in range(len(steps)):
        bar = page.locator("[data-demo='presenter-step']")
        assert bar.get_attribute("data-step") == str(index)

        if index == 0:
            assert _attr(page, "[data-queue-count]") == str(len(demo_queue.QUEUE))
            rendered_files = page.locator("[data-queue-file]").evaluate_all(
                "rows => rows.map(r => r.getAttribute('data-queue-file'))"
            )
            assert rendered_files == [f.id for f in demo_queue.QUEUE]
            assert page.locator("[data-panel='intake-queue']").count() == 1
        else:
            record = session.records[-1]
            review = record.get("review") or {}
            blocked = bool(record.get("blocked"))

            # Figures read out of the LIVE DOM, checked against the running app.
            assert _attr(page, "[data-review-file]") == record["file_id"]
            assert _attr(page, "[data-review-blocked]") == str(blocked).lower()
            assert (
                _attr(page, "[data-review-human]")
                == str(bool(review.get("requires_human_review"))).lower()
            )

            if blocked:
                assert page.locator("[data-panel='why-blocked']").count() == 1
                assert _attr(page, "[data-review-citations]") == "0"
            else:
                for panel in ("summary", "categorisation", "conduct-flags", "draft-response"):
                    assert page.locator(f"[data-panel='{panel}']").count() == 1, panel

                cat = review["categorization"]
                flags = review.get("conduct_flags", []) or []
                assert _attr(page, "[data-review-category]") == cat["category"]
                assert _attr(page, "[data-review-severity]") == cat["severity"]
                assert _attr(page, "[data-review-flags]") == str(len(flags))
                assert _attr(page, "[data-review-citations]") == str(
                    renderer.total_citations(review)
                )
                assert _attr(page, "[data-category]") == cat["category"]
                assert _attr(page, "[data-severity]") == cat["severity"]
                assert (
                    _attr(page, "[data-systemic]")
                    == str(bool(cat["root_cause"]["systemic"])).lower()
                )
                assert _attr(page, "[data-flag-count]") == str(len(flags))
                assert (
                    _attr(page, "[data-draft]")
                    == str(bool((review.get("draft_response") or {}).get("is_draft"))).lower()
                )

                rendered_kinds = page.locator("[data-flag-kind]").evaluate_all(
                    "els => els.map(e => e.getAttribute('data-flag-kind'))"
                )
                assert rendered_kinds == [f["kind"] for f in flags]
                rendered_severities = page.locator("[data-flag-severity]").evaluate_all(
                    "els => els.map(e => e.getAttribute('data-flag-severity'))"
                )
                assert rendered_severities == [f["severity"] for f in flags]

                # Every live citation the running app produced is in the live DOM.
                rendered_citations = page.locator("[data-citation]").evaluate_all(
                    "els => els.map(e => e.getAttribute('data-citation'))"
                )
                assert len(rendered_citations) == renderer.total_citations(review)
                assert rendered_citations, "the running app produced no citations to prove"
                for citation in review["summary"]["citations"] + cat["citations"]:
                    assert citation["source_id"] in rendered_citations

        if index < len(steps) - 1:
            page.locator("button.next:not([disabled])").click()
            page.wait_for_load_state("load")

    assert page.locator("button.next[disabled]").count() == 1
    assert "BLOCKED by the safety pipeline" in page.content()


def test_the_reviewed_step_serves_its_maker_checker_gate_in_the_browser(page, served) -> None:
    """The maker-checker banner and its citations survive the round trip to the DOM."""
    base, session = served
    page.goto(f"{base}/restart", wait_until="load")
    page.locator("button.next:not([disabled])").click()
    page.wait_for_load_state("load")

    review = session.records[-1]["review"]
    assert "HUMAN REVIEW REQUIRED" in page.content()
    assert _attr(page, "[data-review-human]") == "true"
    rendered_citations = page.locator("[data-citation]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-citation'))"
    )
    assert review["summary"]["citations"], "the running app produced no summary citations"
    for citation in review["summary"]["citations"]:
        assert citation["source_id"] in rendered_citations
