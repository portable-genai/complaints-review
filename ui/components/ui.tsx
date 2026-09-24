// Small shared presentational primitives for the B6 console.

import type { ReactNode } from "react";

import type { ReviewRouting } from "../lib/types";

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-ink-200 bg-white shadow-panel">
      <h2 className="border-b border-ink-100 px-4 py-3 text-sm font-semibold text-ink-800">
        {title}
      </h2>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function ReviewBanner({
  requiresReview,
  routing,
}: {
  requiresReview: boolean;
  /** What happened to the hand-off to the review console, when the API reports it. */
  routing?: ReviewRouting;
}) {
  if (!requiresReview) return null;
  return (
    <div className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">
      HUMAN REVIEW REQUIRED — maker-checker gate (P-06). The draft response is a DRAFT and is
      never sent by the system; a human reviews and sends it.
      {routing && routing !== "not_required" ? (
        <p
          data-review-routing={routing}
          className={`mt-1 ${routing === "routed" ? "text-emerald-800" : "text-rose-800"}`}
        >
          {REVIEW_ROUTING_TEXT[routing]}
        </p>
      ) : null}
    </div>
  );
}

// What happened to the human-review hand-off, in the words the reviewer needs. A review that
// requires a checker but is not queued must say so rather than read as reviewed.
const REVIEW_ROUTING_TEXT: Record<Exclude<ReviewRouting, "not_required">, string> = {
  routed: "Sent to the review console.",
  failed: "Could not reach the review console; this review is not queued for a checker.",
  off: "Review routing is off in this deployment; this review is not queued for a checker.",
};

/** Shown when redaction changed what the user submitted before the model saw it. */
export function RedactionNotice() {
  return (
    <div
      role="note"
      data-input-redacted="true"
      className="mb-3 rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900"
    >
      Personal data in your input was masked before the model saw it.
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-ink-400">{children}</p>;
}
