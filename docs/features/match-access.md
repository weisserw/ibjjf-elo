# Match API Access

Anonymous visitors verify with Cloudflare Turnstile before using `/api/matches`
or `/api/matches/<id>/detail-events`. No account is required. All other APIs,
including highlights, are outside this protection.

## Implementation

- `app/match_access.py`: public runtime configuration, server-side Siteverify,
  signed anonymous cookies, database session counters, and the access guard.
- `app/routes/matches.py`: runs the access guard before the existing IP limiter
  and before match queries.
- `app/frontend/src/matchAccess.ts`: a dedicated Axios client. A
  `403 match_access_required` for a missing, expired, or quota-exhausted session
  starts one shared verification attempt, then retries each waiting request
  once with its original parameters. A burst-limit `429` does not trigger
  verification or an automatic retry.
  Requests are queued through verification and retry, so concurrent
  requests cannot exhaust a session during renewal and expose
  a second verification error. Athlete history is fetched directly without a
  frontend response cache or in-flight request cache.
- `app/frontend/src/components/MatchAccessVerification.tsx`: loads Turnstile
  on demand, uses Managed mode with `interaction-only` appearance, and provides
  retry/cancel controls on failure. Mounted globally in `main.tsx` so Database,
  Athlete, Research, and bracket score details share the flow.
- Migration `a3b5c7d9e1f2`: creates `match_access_sessions`.

The browser submits a Turnstile token to `POST /api/access/verify`. The backend
validates it using Cloudflare's Siteverify API and checks both `hostname` and
the `match_access` action. Failures, malformed responses, and service outages
never grant access. The secret is never exposed in configuration responses.

Successful verification creates a random database session and a signed,
one-hour `match_access` cookie with `Secure`, `HttpOnly`, `SameSite=Lax`, and
`Path=/api/`. The cookie is host-only: the apex and www hosts each verify
independently unless the site redirects visitors to a canonical host.

## Usage limits

Each session allows 15 requests per fixed 10-second bucket and reserves up to
200 match-row units before fresh verification is required. Cookies expire
after one hour even if their allowance remains unused. A match-list request
costs 12 units, including athlete history and two-athlete comparisons. The
comparison response still allows up to 100 matches; lowering its quota cost
does not change its results or introduce frontend pagination. Detail requests
cost one unit. Empty or invalid queries can still consume units. This is a
request budget, not an exact count or upper bound on rows downloaded.

An atomic conditional database update reserves units before the main query.
Counters work across processes and persist across restarts and IP changes.
Quota exhaustion returns `403 match_access_required` with
`reason: quota_exhausted`. The frontend obtains a fresh Turnstile token and
retries automatically; no reload or quota error is needed. Cloudflare may
still require a checkbox. If verification fails, the existing retry/cancel UI
remains available rather than leaving the request silently stuck.

Every verification POST requires a fresh valid Turnstile token, even if its
cookie is still valid. Successful verification issues a new random session ID
and cookie, atomically replacing the old session ID in the database.
The old cookie remains invalid after renewal; a copied cookie cannot benefit
from the real browser renewing. Invalid or unavailable verification leaves
the old session and counters unchanged. The replacement carries forward the
old session's burst bucket/counter so renewal does not reset that limit.

`429 match_access_limited` with `Retry-After` is reserved for the short burst
limit. The frontend does not renew in response to it. Expired or deleted
sessions require verification again. The existing per-process IP limiter also
continues to provide an additional burst check. The 200-unit allowance is per
verification, not a hard hourly data cap: a browser can keep browsing by
passing fresh checks. All match-list requests cost 12 units
(16 requests per allowance), including two-athlete comparisons.
Repeated Gi/No-Gi switches fetch fresh history from the API. History
pages cost 12, so the allowance covers 16 fresh history fetches. A handled
`403` can appear in browser network tools
before the successful verification/retry; this should not appear as a user-facing
error. Browser tabs have independent request queues.

## Challenge network diagnostics

Cloudflare documents DNS lookup failures for some subdomains under
`challenges.cloudflare.com` and `dnstest.dev` as expected, non-fatal parts of
challenge execution. A failed subdomain request alone does not indicate that
Siteverify failed. Our code loads the documented `challenges.cloudflare.com`
script and posts tokens to our backend; it does not configure a `brunhild`
hostname. Judge success by the widget callback, `/api/access/verify`, and the
retried match response, rather than treating every internal network failure
as a fatal error.

See https://developers.cloudflare.com/cloudflare-challenges/troubleshooting/challenge-solve-issues/#failed-subdomain-network-requests-during-turnstile-challenges.

An attacker can discard cookies and solve another challenge to obtain a new
session. This raises the cost of scraping; it does not prevent collection by
determined browser automation. Apply edge limits to the verification endpoint
as well. Do not put interstitial WAF challenges directly on JSON API requests
without a corresponding browser clearance flow.

## Deployment, one step at a time

1. Create a Managed Turnstile widget for `jiujitsu.net` and `www.jiujitsu.net`
   (literal hostnames, no backslashes or URL schemes). Leave pre-clearance off.
   The default public site key is `0x4AAAAAAGDvwrAtybkRVXKi`.
2. Set these **backend runtime** environment variables in the hosting service:
   - `TURNSTILE_SECRET_KEY`: widget's secret key.
   - `MATCH_ACCESS_SIGNING_KEY`: a separate randomly generated secret of at
     least 32 characters, identical across all web workers/instances.
   - `MATCH_ACCESS_ENABLED=false` during the initial rollout.
   - Optional `TURNSTILE_SITE_KEY` to override the public key.
   - Optional `TURNSTILE_HOSTNAMES`, a comma-separated allowlist; defaults to
     `jiujitsu.net,www.jiujitsu.net`.
   Never use Vite's `VITE_` prefix for either secret.
3. Apply migrations with `flask db upgrade` from `app/`, and deploy backend
   and the newly built frontend through the normal deployment process.
   The frontend obtains its site key at runtime; no frontend environment
   variable is needed. The initial disabled rollout lets older cached clients
   continue working while the new frontend is deployed.
4. Set `MATCH_ACCESS_ENABLED=true` and redeploy/restart all web workers. Startup
   rejects enabled configurations with missing secrets or a short signing key.
5. In a fresh browser session, check Database pagination, athlete match
   history, Research comparisons, and bracket score details. Direct requests
   without a cookie should return `403` JSON. Verify cookie flags, automatic
   renewal on expiry/quota exhaustion, retry after blocked scripts, old-cookie
   revocation after renewal, and burst-limit `429` behavior. No new migration
   or environment variable is required for the 200-unit renewal behavior.
6. Schedule `flask purge-expired-match-access` daily from `app/` to remove
   expired session rows. Set an edge rate limit on `/api/access/verify`, tune
   against real traffic, and check that the origin cannot bypass edge rules.

All API responses remain `no-store`. Ensure Cloudflare cache rules do not
override this for protected endpoints or verification responses. If CSP is
enabled, allow Turnstile's script/frame origins as documented by Cloudflare.
No live Cloudflare verification can be tested until the private secret is
installed on the deployment host. Do not paste it into chat or commit it.

## Local development and tests

Protection is disabled unless explicitly enabled; existing local development
requires no Cloudflare keys. To test real integration locally, use Cloudflare's
test keys, add `localhost` to `TURNSTILE_HOSTNAMES`, and use a browser setup
that accepts the Secure cookie on localhost (or local HTTPS). Never deploy
Cloudflare's always-pass test keys in production.

Run from the repository root:

```sh
make test
```

Frontend checks from `app/frontend/`:

```sh
npx tsc --noEmit -p tsconfig.app.json
node --test scripts/match-access.test.mjs
```

Backend tests in `test_match_access.py` mock Siteverify and cover successful
verification, cookie flags, malformed/failed verification, outages, forged and
expired sessions, shared limits, weighted quotas, renewal requiring fresh
proof, old-cookie revocation, preserved burst limits, and disabled configuration.
Frontend tests cover concurrent callers, transparent quota renewal, retry
bounds, queued requests across renewal, rate-limit
responses, verification failure/retry, and cancellation.
Do not run a routine frontend
build because it rewrites generated SEO snippets.

References:

- https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
- https://developers.cloudflare.com/turnstile/concepts/appearance-modes/
