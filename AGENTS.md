# AGENTS

## Testing
- Run Python unit tests from the repository root with:
  - `make test`

## Frontend Build
- Do **not** run a frontend build as part of routine changes.
- `npm run build` in `app/frontend` rewrites generated SEO snippet files in `app/seo_snippets/`.
- Prefer leaving frontend build verification to the user unless explicitly requested.
