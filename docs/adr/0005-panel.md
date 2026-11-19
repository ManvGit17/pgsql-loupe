# ADR 0005: The panel

Date: 2026-11-19. Built with React 19.3, Vite 8.3, TypeScript 7.0, Tailwind 4.3.

## Decisions

1. **Source in `panel-src/`, build committed** to `src/pgsql_loupe/panel/` (`panel.js`,
   `panel.css`). Users get the panel from `pip install` with no Node. CI rebuilds it and fails
   if the result differs from what is committed; the build is deterministic (same hash twice).
2. **Few dependencies**: React, React DOM and lucide icons. The tuple-beat drawer also used
   motion, Radix and sonner; animations, tooltips (`title`) and toasts (`aria-live` text) are
   done without them. Fonts are the system's. Output: 246 KB JS (78 KB gzipped), 12 KB CSS.
3. **Served by the middleware** at `{prefix}/` with the same authorisation as the API, and a
   strict Content-Security-Policy: scripts, styles and requests only from the same origin. That
   enforces "works with no network access" and blocks anything injected into the page.
4. **Optional toggle button** (`inject_toggle=True`, off by default): a link to the panel added
   before `</body>` of traced, uncompressed HTML responses; `Content-Length` is recomputed.
5. **Browser test** with Playwright for Python against the example app under uvicorn. It is
   marked `e2e`, left out of the default run (the 15-job matrix does not need a browser) and
   run in its own CI job.

## Consequences

- A change to `panel-src/` must be followed by `npm run build` and a commit of the output.
- The toggle has inline styles, which an app with a strict CSP of its own may block. It is
  off by default for that reason.
