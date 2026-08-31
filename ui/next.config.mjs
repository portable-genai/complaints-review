/** @type {import('next').NextConfig} */
// This file emits only the headers a STATIC table can express. The Content-Security-Policy is
// not one of them: it carries a per-request script nonce, so it is built in `lib/csp.mjs` and
// set in `proxy.ts`. Emitting it here as a lone `frame-ancestors` directive, or
// leaving any CSP in this table alongside the proxy's would hand the browser two policies to
// INTERSECT, where the stricter one wins per directive: that is exactly how a nonce-less
// `script-src` would come back and block Next's inline hydration bootstrap.
//
// `assertHydratableCsp` runs at module scope, and both `next build` and `next start` evaluate
// this file, so the half-configured combination (a nonce in the CSP, a statically prerendered
// route) is refused before it can be shipped rather than discovered in a browser.
import { readFileSync } from "node:fs";

import { assertHydratableCsp } from "./lib/csp.mjs";

assertHydratableCsp(readFileSync(new URL("./app/layout.tsx", import.meta.url), "utf8"));

// Mount the UI (and its assets) under a reverse-proxy sub-path via NEXT_PUBLIC_BASE_PATH
// (e.g. "/agent"); blank keeps the standalone build unchanged.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig = {
  reactStrictMode: true,
  // `next dev` writes AGENTS.md and CLAUDE.md into this directory unless this is false; the
  // writer is node_modules/next/dist/server/lib/generate-agent-files.js. This repo's working
  // agreement is the AGENTS.md at its root and there is no tool-specific alias of it, so a
  // second one here is a second agreement to keep in step and CLAUDE.md is precisely the alias
  // the convention forbids. The generated prose also carries an em-dash, which the catalog's
  // house style forbids in shipped markdown. tests/unit/test_ui_agent_documents.py fails the
  // gate if this line goes away or if either file turns up on disk anyway.
  agentRules: false,
  ...(basePath ? { basePath, assetPrefix: basePath } : {}),
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
