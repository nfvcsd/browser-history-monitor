---
paths:
  - "frontend/**"
---
# Frontend

Use React/TypeScript and existing components, API helpers, and CSS conventions.
Keep routes directly navigable and preserve filters, pagination, loading states,
and actionable errors. Use `src/api.ts` for authenticated requests and `src/time.ts`
for time presentation. Render URLs/titles as untrusted text; avoid raw HTML.

Production builds set `VITE_API_BASE` to empty for same-origin API requests.
Relative API paths must resolve against `window.location.origin`. Local development
retains its localhost API default. Never bake credentials into Vite variables.
Preserve sign-out and expired-session behavior; do not introduce persistent token
storage or relax OAuth checks as a convenience fix.

Reports and UI display browser-local times while API/storage retain UTC semantics.
Preserve both titles and URLs in history/reports and use server-side summaries.
Keep the UI understandable to school administrators, including empty states and
confirmation for actions such as revoking enrollment or changing retention.

Validation: run `npm run build` from `frontend/`. For meaningful UI changes, inspect
desktop and narrow layouts plus direct route loading. Use synthetic data for any
screenshots intended for public sharing.
