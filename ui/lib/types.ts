// TypeScript mirrors of the B6 API response shapes (api/schemas.py). Field names match
// the JSON the FastAPI backend returns one-for-one (enums are their string .value).

export interface Citation {
  source_id: string;
  source_type: string;
  title: string;
  url: string;
  page: number | null;
  snippet: string;
  score: number | null;
}

export interface TimelineEvent {
  date: string;
  event: string;
}

export interface ComplaintSummary {
  issue: string;
  products: string[];
  channel: string;
  timeline: TimelineEvent[];
  parties: string[];
  citations: Citation[];
}

export interface RootCause {
  description: string;
  systemic: boolean;
}

export interface Categorization {
  category: string;
  root_cause: RootCause;
  severity: string;
  regulatory_relevance: string[];
  citations: Citation[];
}

export interface ConductFlag {
  kind: string;
  severity: string;
  detail: string;
  citations: Citation[];
}

export interface DraftResponse {
  body: string;
  tone: string;
  citations: Citation[];
  requires_human_review: boolean;
  is_draft: boolean;
}

export interface ComplaintReview {
  file_id: string;
  summary: ComplaintSummary;
  categorization: Categorization;
  conduct_flags: ConductFlag[];
  draft_response: DraftResponse | null;
  requires_human_review: boolean;
  generated_at: string;
}

export interface ComplaintFileInput {
  id: string;
  customer_ref: string;
  product: string;
  channel: string;
  received_date: string;
  documents: string[];
  narrative: string;
}

// No `actor` field: identity is resolved server-side from the verified Principal (an IAP
// assertion in secure mode, or a seeded dev persona selected via X-Dev-Persona in local
// mode). Any client-asserted actor would be ignored by the backend.
export interface ReviewRequest {
  file: ComplaintFileInput;
}
