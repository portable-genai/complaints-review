import { ConfiguredEmptyError, readEnvSetting } from "./env-setting.mjs";
// Thin client for the B6 FastAPI backend. The base URL defaults to the local API
// (port 8095); override via NEXT_PUBLIC_API_BASE.

import type { ComplaintReview, ReviewRequest } from "./types";

// The API base is resolved in THREE states, not two.
//
// Reading `process.env.NEXT_PUBLIC_API_BASE?.replace(...) || "<loopback default>"`
// which hands a variable an operator DELIBERATELY EMPTIED the loopback default. That is a
// widening: the console then talks to a local API instead of the configured one, and
// `connect-src` is built from the same value, so the emptied deployment is byte-identical to one
// that never configured the variable. Next inlines NEXT_PUBLIC_* AT BUILD TIME, so the wrong
// value is frozen into the bundle and cannot be corrected at start-up.
const DEFAULT_API_BASE = "http://localhost:8095";
const API_BASE_SETTING = readEnvSetting(process.env, "NEXT_PUBLIC_API_BASE");
if (API_BASE_SETTING.isConfiguredEmpty) {
  throw new ConfiguredEmptyError(
    "NEXT_PUBLIC_API_BASE is set to an empty value. An emptied variable names nothing, " +
      "so it cannot inherit the unset default (" + DEFAULT_API_BASE + "), which points this " +
      "console at a loopback API and widens connect-src to match. Unset it to take that " +
      "default deliberately, or give it the API origin this deployment should call.",
  );
}
const API_BASE = (API_BASE_SETTING.hasValue ? API_BASE_SETTING.value : DEFAULT_API_BASE).replace(
  /\/+$/,
  "",
);

// Dev-only identity selection. In LOCAL mode the backend resolves identity from the
// X-Dev-Persona header (seeded personas, no IdP); in secure profiles this header is
// ignored (identity comes from the IAP assertion injected by the platform).
let devPersona = "";

export function setDevPersona(id: string): void {
  devPersona = id;
}

export function getDevPersona(): string {
  return devPersona;
}

function requestHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (devPersona) headers["X-Dev-Persona"] = devPersona;
  return headers;
}

export interface BlockedResponse {
  blocked: true;
  requires_human_review: true;
  detail: string;
  reason: string;
}

function isBlocked(body: unknown): body is BlockedResponse {
  return (
    typeof body === "object" &&
    body !== null &&
    (body as { blocked?: boolean }).blocked === true
  );
}

export async function reviewComplaint(
  request: ReviewRequest,
): Promise<ComplaintReview | BlockedResponse> {
  const response = await fetch(`${API_BASE}/v1/review`, {
    method: "POST",
    headers: requestHeaders(),
    body: JSON.stringify(request),
  });
  if (!response.ok && response.status !== 200) {
    throw new Error(`review failed: ${response.status} ${await response.text()}`);
  }
  const body = await response.json();
  return body as ComplaintReview | BlockedResponse;
}

export async function health(): Promise<{
  status: string;
  profile: string;
  region: string;
}> {
  const response = await fetch(`${API_BASE}/healthz`, { headers: requestHeaders() });
  if (!response.ok) throw new Error(`health failed: ${response.status}`);
  return response.json();
}

export async function listPersonas(): Promise<
  { id: string; subject: string; tenant: string; principals: string }[]
> {
  const response = await fetch(`${API_BASE}/v1/personas`, { headers: requestHeaders() });
  if (!response.ok) throw new Error(`personas failed: ${response.status}`);
  return response.json();
}

export { API_BASE, isBlocked };
