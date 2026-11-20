# Document review workspace

The document detail route (`frontend/app/routes/document.tsx`) prioritizes reviewing
an original against its editable metadata. It inherits the existing MUI theme;
this is a route-level hierarchy change, not a replacement design system.

## Layout and behavior

- Large screens show a sticky original viewer beside grouped review fields.
- Below the `lg` breakpoint, Original / Prüfdaten tabs show one working surface at
  a time. Switching views preserves field edits, page selection and zoom.
- The original image supports 100–250% zoom, fit-to-width and PDF page navigation.
  XML retains its structured preview. A failed image offers the original link.
- A fixed action bar exposes save and approval without scrolling to the form end.
  Its status distinguishes saved data, local edits, saving and excluded documents.
- Naming, exclusion, payment reconciliation and provenance remain available in
  collapsed sections. Reconciliation queries start when its section is first opened.
- Naming and exclusion are disabled while review fields have unsaved changes or
  a save is pending: those actions otherwise reload the document revision.
- Exclusion disables both the fields and the persistent save/approve buttons.
  Security quarantine still replaces the entire editor. Version checks and
  multi-month bank-period confirmation are unchanged.

## Verification

From `frontend/`:

```sh
npm ci
npx tsc --noEmit
npm test
npm run build
# With the frontend running on this example port:
BASE_URL=http://127.0.0.1:5173 npx playwright test tests/browser/document-view.spec.ts
```

The new browser suite intercepts API requests and uses explicitly synthetic
fixtures. It needs a running frontend, not a database or live login. It checks
both configured device projects, persistent actions, no page-level horizontal
overflow, zoom, page navigation, edit retention, revisioned saves, excluded
originals, advanced bank fields and quarantine. Existing backend browser workflows
were adapted to open the management section and switch preview tabs as needed;
those full backend workflows require their normal integration environment.

Live acceptance of the two requested documents remains outstanding: their URLs
require authentication. Synthetic browser tests are not evidence of their actual
content, permissions, backend writes or production deployment.
