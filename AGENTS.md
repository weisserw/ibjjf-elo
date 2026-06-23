# AGENTS

## Testing
- Run Python unit tests from the repository root with:
  - `make test`
- Note that dependencies may be installed in a local pyenv; don't assume the global
  python3 will work, check the environment that would execute if one were running from a shell in the repository root.

## Frontend Build
- Do **not** run a frontend build as part of routine changes.
- `npm run build` in `app/frontend` rewrites generated SEO snippet files in `app/seo_snippets/`.
- Prefer leaving frontend build verification to the user unless explicitly requested.
