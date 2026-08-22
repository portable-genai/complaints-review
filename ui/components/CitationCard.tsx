// Renders a source-and-page Citation chip. Every conduct claim is traceable.

import type { Citation } from "../lib/types";

const TYPE_LABEL: Record<string, string> = {
  complaint_file: "FILE",
  policy: "POLICY",
  regulation: "REGUL",
};

export function CitationCard({ citation }: { citation: Citation }) {
  const page = citation.page != null ? ` p.${citation.page}` : "";
  return (
    <span className="inline-flex items-center gap-1 rounded border border-ink-200 bg-ink-50 px-2 py-0.5 text-xs text-ink-700">
      <span className="font-mono font-semibold text-regblue-700">
        {TYPE_LABEL[citation.source_type] ?? citation.source_type}
      </span>
      <span className="font-mono">
        {citation.source_id}
        {page}
      </span>
      {citation.url ? (
        <a
          href={citation.url}
          target="_blank"
          rel="noreferrer"
          className="text-regblue-600 underline"
        >
          source
        </a>
      ) : null}
    </span>
  );
}

export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) {
    return <span className="text-xs text-ink-400">(no citations)</span>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {citations.map((c, i) => (
        <CitationCard key={`${c.source_id}-${c.page ?? "x"}-${i}`} citation={c} />
      ))}
    </div>
  );
}
