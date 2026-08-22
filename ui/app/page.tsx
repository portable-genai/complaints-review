"use client";

import { useEffect, useState } from "react";

import { ComplaintReviewView } from "../components/ComplaintReviewView";
import { Empty, Panel } from "../components/ui";
import { health, isBlocked, listPersonas, reviewComplaint, setDevPersona } from "../lib/api";
import type { BlockedResponse } from "../lib/api";
import type { ComplaintReview } from "../lib/types";

const SAMPLE_NARRATIVE =
  "I am a recently bereaved and vulnerable customer. The branch sold me a structured " +
  "investment product I did not understand and I want my money back.";

interface Persona {
  id: string;
  subject: string;
  tenant: string;
  principals: string;
}

export default function HomePage() {
  const [narrative, setNarrative] = useState(SAMPLE_NARRATIVE);
  const [product, setProduct] = useState("structured investment product");
  const [channel, setChannel] = useState("branch");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<ComplaintReview | null>(null);
  const [blocked, setBlocked] = useState<BlockedResponse | null>(null);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedPersona, setSelectedPersona] = useState("");

  // The persona picker is a LOCAL-mode-only demo affordance: it lets you pick a seeded dev
  // identity (sent as X-Dev-Persona) so per-user authorization is demoable offline. In
  // secure profiles /v1/personas returns an empty list, so the picker never renders.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await health();
        if (status.profile !== "local") return;
        const list = await listPersonas();
        if (cancelled || list.length === 0) return;
        setPersonas(list);
        setSelectedPersona(list[0].id);
        setDevPersona(list[0].id);
      } catch {
        // Persona picker is dev-only convenience; ignore lookup failures.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function onPersonaChange(id: string) {
    setSelectedPersona(id);
    setDevPersona(id);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setReview(null);
    setBlocked(null);
    try {
      const result = await reviewComplaint({
        file: {
          id: `CMP-${Date.now()}`,
          customer_ref: "CUST-FAKE-UI",
          product,
          channel,
          received_date: new Date().toISOString().slice(0, 10),
          documents: [],
          narrative,
        },
      });
      if (isBlocked(result)) {
        setBlocked(result);
      } else {
        setReview(result);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      {personas.length > 0 ? (
        <Panel title="Demo identity">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-ink-700">Persona</span>
            <select
              value={selectedPersona}
              onChange={(e) => onPersonaChange(e.target.value)}
              className="w-full rounded border border-ink-300 px-3 py-2 text-sm sm:w-96"
            >
              {personas.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.subject} · {p.tenant}
                </option>
              ))}
            </select>
          </label>
        </Panel>
      ) : null}

      <Panel title="Review a complaint file">
        <form onSubmit={onSubmit} className="space-y-3">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-ink-700">Narrative</span>
            <textarea
              value={narrative}
              onChange={(e) => setNarrative(e.target.value)}
              rows={4}
              className="w-full rounded border border-ink-300 px-3 py-2 text-sm"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-ink-700">Product</span>
              <input
                value={product}
                onChange={(e) => setProduct(e.target.value)}
                className="w-full rounded border border-ink-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-ink-700">Channel</span>
              <input
                value={channel}
                onChange={(e) => setChannel(e.target.value)}
                className="w-full rounded border border-ink-300 px-3 py-2 text-sm"
              />
            </label>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="rounded bg-regblue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {loading ? "Reviewing..." : "Review complaint"}
          </button>
        </form>
      </Panel>

      {error ? (
        <Panel title="Error">
          <Empty>{error}</Empty>
        </Panel>
      ) : null}

      {blocked ? (
        <Panel title="Blocked">
          <p className="text-sm text-amber-700">
            {blocked.detail} ({blocked.reason})
          </p>
        </Panel>
      ) : null}

      {review ? <ComplaintReviewView review={review} /> : null}
    </div>
  );
}
