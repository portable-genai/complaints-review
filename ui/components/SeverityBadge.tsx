// Coloured severity pill and conduct-flag-kind badge for the review.

const SEVERITY_STYLE: Record<string, string> = {
  low: "bg-ink-100 text-ink-600",
  medium: "bg-amber-100 text-amber-700",
  high: "bg-orange-100 text-orange-700",
  critical: "bg-red-100 text-red-700",
};

export function SeverityPill({ severity }: { severity: string }) {
  const style = SEVERITY_STYLE[severity] ?? "bg-ink-100 text-ink-600";
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${style}`}>{severity}</span>
  );
}

const FLAG_LABEL: Record<string, string> = {
  vulnerable_customer: "VULNERABLE CUSTOMER",
  systemic_issue: "SYSTEMIC ISSUE",
  regulatory_breach: "REGULATORY BREACH",
  deadline_risk: "DEADLINE RISK",
};

export function ConductFlagBadge({ kind }: { kind: string }) {
  return (
    <span className="inline-block rounded border border-red-300 bg-red-50 px-2 py-0.5 text-xs font-semibold uppercase text-red-700">
      {FLAG_LABEL[kind] ?? kind}
    </span>
  );
}
