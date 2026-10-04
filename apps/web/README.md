# Haulbase dispatch sales workspace

React + TypeScript frontend for the trucking CRM pilot. Frontend and Python API deploy separately. All workspace data comes from the API; demo mode simulates communications in the backend, not in the browser.

## Develop

Start the backend on port 8787, then:

```sh
npm ci
npm run dev
```

Open http://127.0.0.1:5173 and enter the personal access key configured on the backend. The Vite development server proxies `/api` and `/health` to port 8787. Keys live only in React memory; refreshing signs you out. Never put an access key or Telnyx secret in a frontend environment variable.

```sh
npm test
npm run typecheck
npm run build
npm audit
```

## Cloudflare Pages

Build command `npm ci && npm run build`, output `dist`, root `apps/web`. Set `VITE_API_BASE_URL` to the HTTPS backend origin before the build (no trailing `/api`). Configure that exact frontend origin in the backend CORS allowlist. For same-origin API routing omit the variable. No paid frontend service is required.

The build emits security headers, including a Content Security Policy restricted to the configured API origin. Rebuild when the API origin changes. The dashboard uses Google Fonts with local system fallbacks. Real SMS/calls are only available when the backend reports readiness and the lead has the matching consent. Only administrators see automation controls and sequence authoring.

## Browser acceptance test

With the local demo backend running, set `E2E_ACCESS_KEY` to its administrator key and run `npm run test:e2e`. Install a Playwright Chromium browser with `npx playwright install chromium` first. The test uses the actual API, creates a synthetic consented lead, sends a demo SMS, enrolls a sequence, tests STOP opt-out, and captures desktop/mobile screenshots. No real communication is sent.

For the generated local demo keys, `npm run test:e2e:local` loads the administrator key directly from the ignored backend key file. Browser traces may contain request headers; keep `test-results/` private and out of version control. The test creates synthetic leads and sequences in the local demo database.

Coverage is enforced at 80% for statements, branches, and lines with `npm run test:coverage`. `npm run lint` checks TypeScript and formatting. The first local Python Worker request may need several seconds to initialize.
