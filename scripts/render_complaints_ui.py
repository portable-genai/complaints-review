"""Render the audit-first complaint-review UI from the demo JSON into static HTML.

Server-side, dependency-free rendering of a :class:`ComplaintReview` (one page per
complaint file plus an intake-queue index), faithful to the React/Next.js console
(``ui/components/ComplaintReviewView.tsx``) and the same ink / regblue palette, Panel
chrome and source-and-page citation chips. Used to produce screenshots for slides with
the synthetic, fictional complaint data.

    PYTHONPATH=src:tests python scripts/render_complaints_ui.py complaints_demo.json out_dir/
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

CATEGORY_LABEL = {
    "mis_selling": "Mis-selling",
    "fees_charges": "Fees & charges",
    "service": "Service",
    "access": "Access",
    "conduct": "Conduct",
    "fraud": "Fraud",
    "other": "Other",
}
FLAG_LABEL = {
    "vulnerable_customer": "Vulnerable customer",
    "systemic_issue": "Systemic issue",
    "regulatory_breach": "Regulatory breach",
    "deadline_risk": "Deadline risk",
}
SEV_COLOR = {
    "low": ("#eef2f7", "#546b8b"),
    "medium": ("#fef3c7", "#92400e"),
    "high": ("#ffedd5", "#c2410c"),
    "critical": ("#fee2e2", "#b91c1c"),
}
SRC_LABEL = {"policy": "POLICY", "regulation": "REG", "complaint_file": "FILE"}

CSS = """
:root{--ink-50:#f5f7fa;--ink-100:#e6ebf2;--ink-200:#cdd7e4;--ink-300:#a6b6cc;
--ink-400:#7790ae;--ink-500:#546b8b;--ink-600:#3f5470;--ink-700:#33445b;--ink-800:#1f2a3a;
--ink-900:#131b27;--regblue-50:#eef4ff;--regblue-100:#dbe7ff;--regblue-500:#3a60f0;
--regblue-600:#2945d6;--regblue-700:#2237ad;
--ok:#059669;--ok-bg:#ecfdf5;--warn:#d97706;--warn-bg:#fffbeb;
--shadow:0 1px 2px rgba(11,16,26,.06),0 8px 24px rgba(11,16,26,.06);}
*{box-sizing:border-box}
body{margin:0;background:var(--ink-50);color:var(--ink-800);
font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
font-size:14px;line-height:1.5;padding:24px 18px}
.wrap{max-width:880px;margin:0 auto}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
a{color:var(--regblue-700);text-decoration:none}
h1{font-size:18px;margin:0 0 2px}
.sub{color:var(--ink-500);font-size:13px;margin:0 0 16px}
.sub b{color:var(--ink-800)}
.crumbs{font-size:12px;margin:0 0 14px}
.panel{border:1px solid var(--ink-200);background:#fff;border-radius:10px;box-shadow:var(--shadow);margin-bottom:16px}
.panel>h2{border-bottom:1px solid var(--ink-100);padding:11px 16px;margin:0;font-size:13px;font-weight:600;color:var(--ink-800);
display:flex;justify-content:space-between;align-items:center}
.panel>.body{padding:16px}
.statuspill{font-size:11px;font-weight:600;padding:2px 9px;border-radius:999px}
.review{border:1px solid #fcd34d;background:var(--warn-bg);color:#92400e;border-radius:8px;padding:8px 12px;font-size:12px;font-weight:600;margin-bottom:14px}
.blocked{border:1px solid #fca5a5;background:#fef2f2;color:#b91c1c;border-radius:8px;padding:10px 12px;font-size:13px;font-weight:600;margin-bottom:14px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:13px;color:var(--ink-600);margin:0}
.kv dt{color:var(--ink-500);font-weight:500}
.kv dd{margin:0;color:var(--ink-800)}
.issue{font-size:14px;color:var(--ink-800);margin:0 0 10px}
.tl{margin:8px 0 0;padding:0;list-style:none;font-size:13px;color:var(--ink-700)}
.tl li{margin-top:3px}
.tl .d{font-family:ui-monospace,Menlo,monospace;color:var(--ink-500)}
.cat{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.cat .name{font-weight:700;font-size:15px;color:var(--ink-900)}
.muted{color:var(--ink-400);font-size:12px}
.tags{display:flex;gap:5px;flex-wrap:wrap;margin-top:6px}
.tag{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--regblue-700);background:var(--regblue-50);border:1px solid var(--regblue-100);border-radius:5px;padding:1px 7px}
.sev{font-size:10px;font-weight:700;text-transform:uppercase;padding:2px 7px;border-radius:5px}
.flag{border-left:3px solid #fca5a5;padding:8px 0 8px 12px;margin-bottom:10px}
.flag:last-child{margin-bottom:0}
.flag .h{display:flex;gap:8px;align-items:center;margin-bottom:3px}
.flag .kind{font-weight:600;font-size:13px;color:var(--ink-800)}
.flag .d{font-size:13px;color:var(--ink-600)}
.empty{color:var(--ok);font-size:13px;background:var(--ok-bg);border:1px solid #a7f3d0;border-radius:8px;padding:10px 12px}
.draft{white-space:pre-wrap;background:var(--ink-50);border:1px solid var(--ink-100);border-radius:8px;padding:12px;font-size:13px;color:var(--ink-800);margin:0 0 10px}
.cites{margin-top:10px;display:flex;gap:5px;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--ink-200);background:var(--ink-50);border-radius:6px;padding:2px 8px;font-size:11px;color:var(--ink-700)}
.chip .ty{font-family:ui-monospace,Menlo,monospace;font-weight:600;color:var(--regblue-700)}
.chip .sr{font-family:ui-monospace,Menlo,monospace}
.foot{font-size:11px;color:var(--ink-400);text-align:center;margin-top:18px}
table.q{width:100%;border-collapse:collapse;font-size:13px}
table.q th,table.q td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--ink-100)}
table.q th{font-size:11px;text-transform:uppercase;color:var(--ink-400);font-weight:600}
table.q td.num{font-variant-numeric:tabular-nums}
"""


def esc(s: object) -> str:
    return html.escape(str(s if s is not None else ""))


def sev_pill(sev: str) -> str:
    bg, fg = SEV_COLOR.get(sev, SEV_COLOR["low"])
    return f'<span class="sev" style="background:{bg};color:{fg}">{esc(sev)}</span>'


def chip(c: dict) -> str:
    ty = SRC_LABEL.get(c.get("source_type", ""), str(c.get("source_type", "")).upper())
    page = f" p.{c['page']}" if c.get("page") is not None else ""
    title = f" · {esc(c.get('title'))}" if c.get("title") else ""
    return (
        f'<span class="chip" data-citation="{esc(c.get("source_id"))}" '
        f'data-citation-type="{esc(c.get("source_type", ""))}">'
        f'<span class="ty">{esc(ty)}</span>'
        f'<span class="sr">{esc(c.get("source_id"))}{esc(page)}</span>{title}</span>'
    )


def cite_block(citations: list[dict]) -> str:
    if not citations:
        return '<div class="cites" data-citation-count="0"><span class="muted">(no citations)</span></div>'
    return (
        f'<div class="cites" data-citation-count="{len(citations)}">'
        + "".join(chip(c) for c in citations)
        + "</div>"
    )


def total_citations(review: dict) -> int:
    """Every citation the review carries, counted the way the served page renders them.

    F2 evidence hook: the served page must report the SAME number the running app
    computed, so this helper is the one definition both sides read.
    """
    total = len(review.get("summary", {}).get("citations", []))
    total += len(review.get("categorization", {}).get("citations", []))
    for flag in review.get("conduct_flags", []) or []:
        total += len(flag.get("citations", []))
    draft = review.get("draft_response") or {}
    total += len(draft.get("citations", []))
    return total


def page(title: str, body: str) -> str:
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}</title>"
        f"<style>{CSS}</style></head><body><div class='wrap'>{body}</div></body></html>"
    )


def render_summary(summary: dict) -> str:
    timeline = "".join(
        f'<li><span class="d">{esc(ev.get("date"))}</span> · {esc(ev.get("event"))}</li>'
        for ev in summary.get("timeline", [])
        if ev.get("event")
    )
    products = ", ".join(summary.get("products") or []) or "n/a"
    parties = ", ".join(summary.get("parties") or []) or "n/a"
    return f"""
    <section class="panel" data-panel="summary"><h2>Summary</h2>
    <div class="body" data-timeline-count="{len(summary.get("timeline", []))}"
         data-products-count="{len(summary.get("products") or [])}">
      <p class="issue">{esc(summary.get("issue"))}</p>
      <dl class="kv">
        <dt>products</dt><dd>{esc(products)}</dd>
        <dt>channel</dt><dd>{esc(summary.get("channel"))}</dd>
        <dt>parties</dt><dd>{esc(parties)}</dd>
      </dl>
      {f'<ul class="tl">{timeline}</ul>' if timeline else ""}
      {cite_block(summary.get("citations", []))}
    </div></section>"""


def render_categorization(cat: dict) -> str:
    label = CATEGORY_LABEL.get(cat.get("category", ""), cat.get("category", ""))
    rc = cat.get("root_cause", {})
    systemic = " (systemic)" if rc.get("systemic") else ""
    rel = cat.get("regulatory_relevance") or []
    tags = "".join(f'<span class="tag">{esc(r)}</span>' for r in rel)
    return f"""
    <section class="panel" data-panel="categorisation"><h2>Categorisation</h2>
    <div class="body" data-category="{esc(cat.get("category", ""))}"
         data-severity="{esc(cat.get("severity", "medium"))}"
         data-systemic="{esc(str(bool(rc.get("systemic"))).lower())}"
         data-regulatory-count="{len(rel)}">
      <div class="cat"><span class="name">{esc(label)}</span>{sev_pill(cat.get("severity", "medium"))}</div>
      <p class="muted" style="font-size:13px;color:var(--ink-700)">
        <b style="color:var(--ink-500);font-weight:500">root cause:</b>
        {esc(rc.get("description"))}{esc(systemic)}</p>
      {f'<div class="tags">{tags}</div>' if tags else ""}
      {cite_block(cat.get("citations", []))}
    </div></section>"""


def render_flags(flags: list[dict]) -> str:
    if not flags:
        return (
            '<section class="panel" data-panel="conduct-flags">'
            '<h2>Conduct flags <span class="muted">0</span></h2>'
            '<div class="body" data-flag-count="0">'
            '<div class="empty">✓ No conduct flags raised on this file.</div>'
            "</div></section>"
        )
    items = []
    for f in flags:
        label = FLAG_LABEL.get(f.get("kind", ""), f.get("kind", ""))
        items.append(
            f'<div class="flag" data-flag-kind="{esc(f.get("kind", ""))}" '
            f'data-flag-severity="{esc(f.get("severity", "medium"))}">'
            f'<div class="h"><span class="kind">{esc(label)}</span>'
            f"{sev_pill(f.get('severity', 'medium'))}</div>"
            f'<div class="d">{esc(f.get("detail"))}</div>'
            f"{cite_block(f.get('citations', []))}</div>"
        )
    return (
        f'<section class="panel" data-panel="conduct-flags">'
        f'<h2>Conduct flags <span class="muted">{len(flags)}</span></h2>'
        f'<div class="body" data-flag-count="{len(flags)}">{"".join(items)}</div></section>'
    )


def render_draft(draft: dict | None) -> str:
    if not draft:
        return ""
    return f"""
    <section class="panel" data-panel="draft-response"><h2>Draft response
      <span class="statuspill" style="background:#fef3c7;color:#92400e">DRAFT · never sent</span></h2>
      <div class="body" data-draft="{esc(str(bool(draft.get("is_draft"))).lower())}"
           data-draft-tone="{esc(draft.get("tone", ""))}">
      <p class="muted">tone: {esc(draft.get("tone"))} · is_draft={esc(str(draft.get("is_draft")).lower())} ·
        a human reviews and sends it (P-06 / R1)</p>
      <pre class="draft">{esc(draft.get("body"))}</pre>
      {cite_block(draft.get("citations", []))}
    </div></section>"""


def render_complaint(record: dict) -> str:
    file = record.get("file", {})
    fid = record.get("file_id")
    review = record.get("review") or {}
    cat = review.get("categorization") or {}
    # One stable, styling-independent block carrying every load-bearing figure this page
    # asserts (F2). A renderer that stops computing one of them, or a server that serves a
    # stale record, fails the served self-test and the browser walkthrough alike.
    hooks = (
        f"<div data-review-file='{esc(fid)}' "
        f"data-review-blocked='{esc(str(bool(record.get('blocked'))).lower())}' "
        f"data-review-category='{esc(cat.get('category', ''))}' "
        f"data-review-severity='{esc(cat.get('severity', ''))}' "
        f"data-review-flags='{len(review.get('conduct_flags', []) or [])}' "
        f"data-review-citations='{total_citations(review) if review else 0}' "
        f"data-review-human='{esc(str(bool(review.get('requires_human_review'))).lower())}'"
        f"></div>"
    )
    header = (
        hooks + f"<p class='crumbs'><a href='index.html'>&larr; Intake queue</a></p>"
        f"<h1>Complaint review — <span class='mono'>{esc(fid)}</span></h1>"
        f"<p class='sub'>product <b>{esc(file.get('product'))}</b> · channel "
        f"<b>{esc(file.get('channel'))}</b> · received <b>{esc(file.get('received_date'))}</b> · "
        f"actor <span class='mono'>{esc(record.get('actor', ''))}</span></p>"
    )
    if record.get("blocked"):
        body = (
            header + '<div class="blocked">BLOCKED by the safety pipeline — no artifact emitted. '
            "The request was refused and audited as BLOCKED, then routed for human review.</div>"
            + '<section class="panel" data-panel="why-blocked"><h2>Why it was blocked</h2>'
            '<div class="body">'
            f'<p class="issue">{esc(record.get("reason"))}</p>'
            '<p class="muted">The complaint narrative is redacted, then screened by the input '
            "guardrail before any model or knowledge-base call. A prompt-injection / jailbreak "
            "pattern fails the screen, so the pipeline raises rather than emit an ungrounded or "
            "unsafe conduct decision.</p></div></section>"
            "<p class='foot'>Audit-first complaint review · synthetic fictional data · "
            "deterministic local safety pipeline</p>"
        )
        return page(f"Complaint {fid} — blocked", body)

    body = (
        header + '<div class="review">HUMAN REVIEW REQUIRED — maker-checker gate (P-06). '
        "The agent proposes; a qualified checker disposes and sends the draft.</div>"
        + render_summary(review["summary"])
        + render_categorization(review["categorization"])
        + render_flags(review.get("conduct_flags", []))
        + render_draft(review.get("draft_response"))
        + "<p class='foot'>Audit-first complaint review · synthetic fictional data · "
        "redact -> guardrail -> retrieve -> summarise -> categorise -> draft -> audit</p>"
    )
    return page(f"Complaint {fid}", body)


def render_index(data: dict) -> str:
    rows = []
    for rec in data["complaints"]:
        fid = rec["file_id"]
        file = rec.get("file", {})
        href = f"complaint-{fid}.html"
        if rec.get("blocked"):
            rows.append(
                f"<tr><td><a href='{esc(href)}'>{esc(fid)}</a></td>"
                f"<td>{esc(file.get('product'))}</td><td>{esc(file.get('channel'))}</td>"
                f'<td><span class="sev" style="background:#fee2e2;color:#b91c1c">blocked</span></td>'
                f"<td>—</td><td class='num'>—</td></tr>"
            )
            continue
        review = rec["review"]
        cat = review["categorization"]
        rows.append(
            f"<tr><td><a href='{esc(href)}'>{esc(fid)}</a></td>"
            f"<td>{esc(file.get('product'))}</td><td>{esc(file.get('channel'))}</td>"
            f"<td>{esc(CATEGORY_LABEL.get(cat['category'], cat['category']))} {sev_pill(cat['severity'])}</td>"
            f"<td>{esc(review['summary']['issue'])[:60]}…</td>"
            f"<td class='num'>{len(review.get('conduct_flags', []))}</td></tr>"
        )
    body = (
        "<h1>Complaints & Conduct File Review — intake queue</h1>"
        f"<p class='sub'>{len(data['complaints'])} synthetic complaint files reviewed end to end "
        "under the offline local profile. Every artifact is cited and flagged for human review; "
        "the prompt-injection file is refused by the safety pipeline.</p>"
        '<section class="panel" data-panel="reviewed-files"><h2>Reviewed files</h2>'
        '<div class="body">'
        "<table class='q'><tr><th>File</th><th>Product</th><th>Channel</th>"
        "<th>Categorisation</th><th>Issue</th><th>Flags</th></tr>"
        + "".join(rows)
        + "</table></div></section>"
        "<p class='foot'>Audit-first complaint review · synthetic fictional data</p>"
    )
    return page("Complaints intake queue", body)


def main(json_path: str, out_dir: str) -> None:
    data = json.loads(Path(json_path).read_text())
    # Surface the actor on each record so a single page renders standalone.
    for rec in data["complaints"]:
        rec.setdefault("actor", data.get("actor", ""))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    written = []
    for rec in data["complaints"]:
        p = out / f"complaint-{rec['file_id']}.html"
        p.write_text(render_complaint(rec))
        written.append(p)
    idx = out / "index.html"
    idx.write_text(render_index(data))
    written.append(idx)
    for p in written:
        print("wrote", p)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
