import type { Metadata } from "next";
import type { ReactNode } from "react";
import { ProvenanceBanner } from "./ProvenanceBanner";
import "./globals.css";

// REQUIRED by the nonce CSP, not a performance preference. `proxy.ts` mints a per-request
// script nonce, and Next can only stamp it onto the script tags of a DYNAMICALLY rendered
// route. A statically prerendered page was built before the nonce existed, so it ships bare
// script tags while the header advertises one, and `'strict-dynamic'` switches off the
// `'self'` fallback that had at least been loading the chunks: the half-configured state
// blocks strictly MORE than no CSP at all. `next.config.mjs` refuses to build without this
// line, and `ui/scripts/assert-hydratable.mjs` proves it against the served bytes.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Complaints & Conduct File Review",
  description:
    "Demo console for the service: a cited summary, categorisation with conduct flags, and a draft regulator/customer response from a complaint file.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  // EMBED mode: the host page owns the chrome, so drop our header/branding and the outer
  // max-w-4xl wrapper when NEXT_PUBLIC_EMBED === "1".
  const embed = process.env.NEXT_PUBLIC_EMBED === "1";
  return (
    <html lang="en">
      <body>
        <ProvenanceBanner />
        {embed ? (
          <main className="p-4">{children}</main>
        ) : (
          <>
            <header className="border-b border-ink-200 bg-white">
              <div className="mx-auto max-w-4xl px-6 py-4">
                <h1 className="text-lg font-semibold text-ink-900">
                  Complaints &amp; Conduct File Review
                </h1>
                <p className="text-sm text-ink-500">
                  Cited reviews · draft responses are never auto-sent · region
                  asia-southeast1 · synthetic data is fictional
                </p>
              </div>
            </header>
            <main className="mx-auto max-w-4xl px-6 py-6">{children}</main>
          </>
        )}
      </body>
    </html>
  );
}
