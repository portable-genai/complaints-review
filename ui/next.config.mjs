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
