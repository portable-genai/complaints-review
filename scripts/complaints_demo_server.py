"""Live, click-through demo server for the B6 complaint-review flow (stdlib only).

Holds a real :class:`ComplaintReviewService` over the offline ``local`` adapter stack and
reviews the *actual* synthetic intake queue one file per click : intro -> review the
mis-selling/vulnerable file -> review the fees file -> the prompt-injection file is refused
by the safety pipeline -> done : rendering the audit-first UI at each step. No Google
Cloud, no API key, no extra dependencies (the demo port is separate from the API's 8095).

    PYTHONPATH=src:tests python scripts/complaints_demo_server.py [--port 8096]

Then open http://localhost:8096 and click "Next ▶", or drive it with
``scripts/complaints_demo_playwright.py`` for a presenter-controlled walkthrough.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Force the SDK-free local profile with ephemeral in-memory stores (deterministic, offline).
os.environ.setdefault("COMPLAINTS_PROFILE", "local")
os.environ.setdefault("COMPLAINTS_LOCAL_DB", ":memory:")
os.environ.setdefault("COMPLAINTS_LOCAL_AUDIT", ":memory:")

import complaints_demo as demo  # noqa: E402  sibling script: the synthetic intake queue
import render_complaints_ui as r  # noqa: E402  sibling script: the audit-first rendering

from complaints_review.api.deps import build_review_service  # noqa: E402
from complaints_review.config import build_container  # noqa: E402
from complaints_review.domain.errors import (  # noqa: E402
    GuardrailBlockedError,
    RetrievalEmptyError,
)
from complaints_review.domain.serialization import to_jsonable  # noqa: E402

# The scripted demo steps. Step 0 is the intro; steps 1..N each review one queued file.
STEPS = [
    {
        "key": "intro",
        "label": "Intake queue — three synthetic complaint files",
        "next": "Review the mis-selling complaint from a vulnerable customer",
    },
    {
        "key": "file-0",
        "label": "Mis-selling · vulnerable customer · past deadline",
        "next": "Review the recent fees complaint",
    },
    {
        "key": "file-1",
        "label": "Fees complaint · recent · within the handling window",
        "next": "Review the prompt-injection attempt (it will be blocked)",
    },
    {
        "key": "file-2",
        "label": "Prompt-injection attempt — refused by the safety pipeline",
        "next": None,
    },
]

_CONTROL_CSS = """
.democtl{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:12px;
  margin:-24px -18px 16px;padding:12px 18px;background:#0b101a;color:#fff}
.democtl .lbl{font-size:13px}.democtl .lbl b{color:#90b2ff}
.democtl .spacer{flex:1}
.democtl form{margin:0}
.democtl button{font:inherit;font-size:13px;font-weight:600;border:0;border-radius:7px;
  padding:7px 14px;cursor:pointer}
.democtl .next{background:#3a60f0;color:#fff}.democtl .next:disabled{opacity:.4;cursor:default}
.democtl .restart{background:transparent;color:#a6b6cc;border:1px solid #33445b}
.democtl .pill{font-variant-numeric:tabular-nums;color:#cdd7e4;font-size:12px}
"""


class DemoSession:
    """Drives the real review service forward one queued file per click."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.svc = build_review_service(build_container())
        self.idx = 0
        # records[i] is the JSON-able review/blocked record for QUEUE[i], lazily filled.
        self.records: list[dict] = []

    @property
    def at_end(self) -> bool:
        return self.idx >= len(STEPS) - 1

    def advance(self) -> None:
        if self.at_end:
            return
        self.idx += 1
        file_idx = self.idx - 1  # step 1 -> file 0, etc.
        if 0 <= file_idx < len(demo.QUEUE):
            self.records.append(self._review(demo.QUEUE[file_idx]))

    def _review(self, file: object) -> dict:
        try:
            review = self.svc.review(file, actor=demo.ACTOR)  # type: ignore[arg-type]
        except (GuardrailBlockedError, RetrievalEmptyError) as exc:
            return {
                "file_id": file.id,  # type: ignore[attr-defined]
                "file": to_jsonable(file),
                "actor": demo.ACTOR,
                "blocked": True,
                "reason": str(exc),
                "review": None,
            }
        return {
            "file_id": file.id,  # type: ignore[attr-defined]
            "file": to_jsonable(file),
            "actor": demo.ACTOR,
            "blocked": False,
            "reason": "",
            "review": to_jsonable(review),
        }

    # -- rendering --------------------------------------------------------- #
    def render(self) -> str:
        if self.idx == 0 or not self.records:
            html = r.page("Complaints demo — intake queue", self._intro_body())
        else:
            html = r.render_complaint(self.records[-1])
        return self._inject_controls(html)

    def _intro_body(self) -> str:
        rows = []
        for f in demo.QUEUE:
            rows.append(
                f"<tr data-queue-file='{r.esc(f.id)}'><td class='mono'>{r.esc(f.id)}</td>"
                f"<td>{r.esc(f.product)}</td><td>{r.esc(f.channel.value)}</td>"
                f"<td>{r.esc(f.received_date)}</td></tr>"
            )
        return (
            "<h1>Complaints & Conduct File Review — live demo</h1>"
            "<p class='sub'>A conduct officer works an intake queue of three synthetic "
            "complaint files. Click <b>Next &#9654;</b> to review each one with the real "
            "service under the offline local profile.</p>"
            '<section class="panel" data-panel="intake-queue">'
            "<h2>Intake queue (synthetic, fictional)</h2>"
            f"<div class='body' data-queue-count='{len(demo.QUEUE)}'>"
            "<table class='q'><tr><th>File</th><th>Product</th><th>Channel</th><th>Received</th></tr>"
            + "".join(rows)
            + "</table>"
            "<p class='muted' style='margin-top:10px'>Each review runs redact &rarr; input "
            "guardrail &rarr; retrieve policy/regulation &rarr; summarise &rarr; categorise "
            "(+ deterministic conduct flags) &rarr; draft response &rarr; output guardrail "
            "&rarr; audit. The draft is never sent by the system (P-06 / R1).</p>"
            "</div></section>"
            "<p class='foot'>Audit-first complaint review · synthetic fictional data · "
            "deterministic offline pipeline</p>"
        )

    def _inject_controls(self, html: str) -> str:
        step = STEPS[self.idx]
        nxt = step["next"]
        pill = ""
        if self.records and not self.records[-1].get("blocked"):
            cat = self.records[-1]["review"]["categorization"]
            pill = f"<span class='pill'>{r.esc(cat['category'])} · {r.esc(cat['severity'])}</span>"
        elif self.records and self.records[-1].get("blocked"):
            pill = "<span class='pill'>blocked</span>"
        next_btn = (
            f"<form method='post' action='/advance'><button class='next' type='submit'>"
            f"Next &#9654; &nbsp;·&nbsp; {r.esc(nxt)}</button></form>"
            if nxt
            else "<button class='next' disabled>Demo complete &#10003;</button>"
        )
        bar = (
            f"<div class='democtl' data-demo='presenter-step' data-step='{self.idx}'>"
            f"<span class='lbl'>Step {self.idx + 1}/{len(STEPS)} — <b>{r.esc(step['label'])}</b></span>"
            f"{pill}<span class='spacer'></span>{next_btn}"
            "<form method='post' action='/restart'><button class='restart' type='submit'>Restart</button></form>"
            "</div>"
        )
        html = html.replace("</style>", _CONTROL_CSS + "</style>", 1)
        return html.replace("<div class='wrap'>", "<div class='wrap'>" + bar, 1)


class Handler(BaseHTTPRequestHandler):
    session: DemoSession  # set on the server instance below

    def _send(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, to: str = "/") -> None:
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    @property
    def _sess(self) -> DemoSession:
        return self.server.session  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        with self.server.lock:  # type: ignore[attr-defined]
            if path == "/":
                self._send(self._sess.render())
            elif path == "/state":
                self._send(json.dumps({"step": self._sess.idx}), 200)
            elif path == "/restart":
                # Allowed over GET so the walkthrough can reset with a plain navigation.
                self._sess.reset()
                self._redirect("/")
            else:
                self._send("<h1>404</h1>", 404)

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        with self.server.lock:  # type: ignore[attr-defined]
            if path == "/advance":
                self._sess.advance()
            elif path == "/restart":
                self._sess.reset()
        self._redirect("/")

    def log_message(self, *args: object) -> None:  # quiet console
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Live complaint-review demo server")
    parser.add_argument("--port", type=int, default=8096)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.session = DemoSession()  # type: ignore[attr-defined]
    server.lock = threading.Lock()  # type: ignore[attr-defined]
    print(f"Complaints demo server on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
