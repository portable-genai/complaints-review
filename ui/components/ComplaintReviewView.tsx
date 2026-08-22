// Renders a full ComplaintReview: summary, categorisation, conduct flags, draft response.

import type { ComplaintReview } from "../lib/types";
import { CitationList } from "./CitationCard";
import { ConductFlagBadge, SeverityPill } from "./SeverityBadge";
import { Empty, Panel, ReviewBanner } from "./ui";

export function ComplaintReviewView({ review }: { review: ComplaintReview }) {
  const { summary, categorization, conduct_flags, draft_response } = review;
  return (
    <div className="space-y-4">
      <ReviewBanner requiresReview={review.requires_human_review} />

      <Panel title="Summary">
        <p className="mb-2 text-sm text-ink-800">{summary.issue}</p>
        <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-ink-600">
          <div>
            <dt className="inline font-medium text-ink-500">products: </dt>
            <dd className="inline">{summary.products.join(", ") || "n/a"}</dd>
          </div>
          <div>
            <dt className="inline font-medium text-ink-500">channel: </dt>
            <dd className="inline">{summary.channel}</dd>
          </div>
        </dl>
        {summary.timeline.length > 0 ? (
          <ul className="mb-3 space-y-1 text-sm text-ink-700">
            {summary.timeline.map((ev, i) => (
              <li key={i}>
                <span className="font-mono text-ink-500">{ev.date}</span> · {ev.event}
              </li>
            ))}
          </ul>
        ) : null}
        <CitationList citations={summary.citations} />
      </Panel>

      <Panel title="Categorisation">
        <div className="mb-2 flex items-center gap-2 text-sm">
          <span className="font-semibold text-ink-900">{categorization.category}</span>
          <SeverityPill severity={categorization.severity} />
        </div>
        <p className="mb-1 text-sm text-ink-700">
          <span className="font-medium text-ink-500">root cause: </span>
          {categorization.root_cause.description}
          {categorization.root_cause.systemic ? " (systemic)" : ""}
        </p>
        {categorization.regulatory_relevance.length > 0 ? (
          <p className="mb-2 text-sm text-ink-600">
            <span className="font-medium text-ink-500">regulatory relevance: </span>
            {categorization.regulatory_relevance.join(", ")}
          </p>
        ) : null}
        <CitationList citations={categorization.citations} />
      </Panel>

      <Panel title={`Conduct flags (${conduct_flags.length})`}>
        {conduct_flags.length === 0 ? (
          <Empty>No conduct flags raised.</Empty>
        ) : (
          <ul className="space-y-3">
            {conduct_flags.map((flag, i) => (
              <li key={i} className="border-l-2 border-red-200 pl-3">
                <div className="mb-1 flex items-center gap-2">
                  <ConductFlagBadge kind={flag.kind} />
                  <SeverityPill severity={flag.severity} />
                </div>
                <p className="mb-1 text-sm text-ink-700">{flag.detail}</p>
                <CitationList citations={flag.citations} />
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {draft_response ? (
        <Panel title="Draft response (not sent)">
          <p className="mb-2 text-xs font-medium text-amber-700">
            tone: {draft_response.tone} · draft · never sent by the system
          </p>
          <pre className="mb-3 whitespace-pre-wrap rounded bg-ink-50 p-3 text-sm text-ink-800">
            {draft_response.body}
          </pre>
          <CitationList citations={draft_response.citations} />
        </Panel>
      ) : null}
    </div>
  );
}
