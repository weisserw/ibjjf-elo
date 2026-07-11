# AGENTS

## Documentation
- Feature guides should be indexed from `docs/FEATURE_INDEX.md`.
- Workflow and investigation notes live in `docs/workflows/`.

## Feature Work
- Before investigating or changing an existing feature, consult
`docs/FEATURE_INDEX.md` and read the relevant feature guide.
- Use the guide to locate the relevant code and tests, then verify its claims against the current implementation.
- Update the guide when relevant changes are made to a feature. Not every change needs to be documented, only bugs / regressions and changes that impact documentation correctness or comprehensiveness.

## Testing
- Run Python unit tests from the repository root with:
  - `make test`
- Run OCR/livestream text scan tests from the repository root with:
  - `make test-ocr`
- OCR tests are computationally expensive. Do not run OCR tests unless OCR/livestream text scan changes are being made.
- Note that dependencies may be installed in a local pyenv; don't assume the global python3 will work, check the environment that would execute if one were running from a shell in the repository root.

## Frontend Build
- Do **not** run a frontend build as part of routine changes.
- `npm run build` in `app/frontend` rewrites generated SEO snippet files in `app/seo_snippets/`.
- Prefer leaving frontend build verification to the user unless explicitly requested.
