#!/usr/bin/env python3
"""Credential-free anti-rot check for the real Doc6 presenter demo.

Two stages, both executed, neither reading hard-coded prose:

1. **In-process** : the real :class:`DemoSession` reviews the real synthetic intake
   queue and renders every presenter step.
2. **Served** : the real ``ThreadingHTTPServer`` is started on an ephemeral port and the
   whole presenter journey is driven over HTTP with ``POST /advance``. Every figure
   asserted at this stage is read out of the SERVED bytes through the stable ``data-*``
   evidence hooks and compared with the value the RUNNING app computed, so a renderer
   that stops emitting a figure, a server that stops advancing, or a hook that gets
   renamed all fail here. A step that only rendered in-process was invisible to the old
   check, which never served a byte.

The headless-browser journey over the same served pages lives in
``tests/browser/test_served_demo_ui.py`` and needs the pinned ``[demo]`` extra.
"""

from __future__ import annotations

import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import render_complaints_ui as r
from complaints_demo_server import STEPS, DemoSession, Handler


def _hook(html: str, attribute: str) -> str:
    """Read one stable ``data-*`` evidence hook out of served markup."""
    match = re.search(rf"{attribute}='([^']*)'", html) or re.search(rf'{attribute}="([^"]*)"', html)
    assert match, f"evidence hook {attribute} is missing from the served page"
    return match.group(1)


def _hooks(html: str, attribute: str) -> list[str]:
    return re.findall(rf"{attribute}='([^']*)'", html) or re.findall(
        rf'{attribute}="([^"]*)"', html
    )


def check_in_process() -> None:
    session = DemoSession()
    opening = session.render()
    assert "intake queue" in opening.lower() and "data-demo='presenter-step'" in opening
    page = opening
    while not session.at_end:
        session.advance()
        page = session.render()
        assert f"data-step='{session.idx}'" in page
    assert len(session.records) == 3 and session.records[-1]["blocked"] is True
    assert session.records[0]["review"]["requires_human_review"] is True
    assert session.idx == len(STEPS) - 1 and "Demo complete" in page
    print("PASS demo: queue, deterministic conduct review, and safety refusal rendered")


def check_served() -> None:
    """Drive the REAL server over HTTP and assert live figures from served bytes."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.session = DemoSession()  # type: ignore[attr-defined]
    server.lock = threading.Lock()  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    session = server.session  # type: ignore[attr-defined]

    try:
        for index in range(len(STEPS)):
            with urllib.request.urlopen(f"{base}/", timeout=20) as response:  # noqa: S310
                assert response.status == 200
                page = response.read().decode("utf-8")

            # The served page is at the step the served app believes it is at.
            assert _hook(page, "data-step") == str(index), f"served step marker is not {index}"

            if index == 0:
                # The intro serves the whole intake queue, one row per queued file.
                import complaints_demo as demo

                assert _hook(page, "data-queue-count") == str(len(demo.QUEUE))
                assert _hooks(page, "data-queue-file") == [f.id for f in demo.QUEUE]
                assert "intake-queue" in _hooks(page, "data-panel")
            else:
                record = session.records[-1]
                review = record.get("review") or {}
                blocked = bool(record.get("blocked"))

                # Live figures: served bytes vs what the running app computed.
                assert _hook(page, "data-review-file") == record["file_id"]
                assert _hook(page, "data-review-blocked") == str(blocked).lower()
                assert (
                    _hook(page, "data-review-human")
                    == str(bool(review.get("requires_human_review"))).lower()
                )

                panels = _hooks(page, "data-panel")
                if blocked:
                    assert "why-blocked" in panels, "served page lost the why-blocked panel hook"
                    assert _hook(page, "data-review-citations") == "0"
                    assert "BLOCKED by the safety pipeline" in page
                else:
                    for required in (
                        "summary",
                        "categorisation",
                        "conduct-flags",
                        "draft-response",
                    ):
                        assert required in panels, f"served page lost the {required} panel hook"

                    cat = review["categorization"]
                    flags = review.get("conduct_flags", []) or []
                    assert _hook(page, "data-review-category") == cat["category"]
                    assert _hook(page, "data-review-severity") == cat["severity"]
                    assert _hook(page, "data-review-flags") == str(len(flags))
                    assert _hook(page, "data-review-citations") == str(r.total_citations(review))
                    assert _hook(page, "data-category") == cat["category"]
                    assert _hook(page, "data-severity") == cat["severity"]
                    assert (
                        _hook(page, "data-systemic")
                        == str(bool(cat["root_cause"]["systemic"])).lower()
                    )
                    assert _hook(page, "data-regulatory-count") == str(
                        len(cat.get("regulatory_relevance") or [])
                    )
                    assert _hook(page, "data-flag-count") == str(len(flags))
                    assert _hooks(page, "data-flag-kind") == [f["kind"] for f in flags]
                    assert _hooks(page, "data-flag-severity") == [f["severity"] for f in flags]

                    draft = review.get("draft_response") or {}
                    assert _hook(page, "data-draft") == str(bool(draft.get("is_draft"))).lower()

                    # Every live citation the running app produced is on the served page.
                    served_citations = _hooks(page, "data-citation")
                    assert len(served_citations) == r.total_citations(review)
                    assert served_citations, "the running app produced no citations to prove"
                    for citation in review["summary"]["citations"] + cat["citations"]:
                        assert citation["source_id"] in served_citations

            if index < len(STEPS) - 1:
                request = urllib.request.Request(f"{base}/advance", method="POST", data=b"")
                with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                    assert response.status in (200, 303)
            else:
                assert "Demo complete" in page

        # The audit/state endpoint must serve too, agreeing with the running session.
        with urllib.request.urlopen(f"{base}/state", timeout=20) as response:  # noqa: S310
            assert response.status == 200
            state = response.read().decode("utf-8")
        assert f'"step": {session.idx}' in state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    print(
        "PASS served: every presenter step, panel hook and live figure read back over "
        "HTTP from the running demo server"
    )


def main() -> int:
    check_in_process()
    check_served()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
