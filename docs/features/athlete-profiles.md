# Athlete Profiles

## User-Facing Behavior

Athlete profiles are end-user pages at `/athlete/:id`. The route parameter can
be either the athlete UUID or the unique `athletes.slug`; most frontend links use
the slug.

The profile page shows identity and biography data, Instagram and BJJ Heroes
links, a profile photo, country flag/note, current rating and belt, rank rows,
upcoming registrations, media coverage, medals, team history, suspension
warnings, rating history, and paginated matches for the selected Gi/No-Gi tab.

Admins can search for athletes, edit per-athlete profile fields, upload profile
photos, manage media coverage links, edit medal places, find/import missing
historical medals, and update match video links. Instagram photo fetching is
implemented in shared photo helpers and the `scripts/get_all_photos.py` batch
script; the current admin edit form stores the Instagram handle and supports
manual photo upload.

## Main Code Paths

Frontend:

- `app/frontend/src/App.tsx` routes `/athlete/:id` to `Athlete`.
- `app/frontend/src/components/Athlete.tsx` owns the profile page. It fetches
  profile data, fetches paginated matches, renders header/profile-photo data,
  rank rows, upcoming registrations, media coverage, medal case, team history,
  suspensions, rating chart, and `DBTableRows` for matches.
- `app/frontend/src/components/Athlete.css` styles the profile header, photo,
  rank/registration blocks, media coverage list, medal case, and mobile layout.

Backend/end-user APIs:

- `app/routes/athletes.py`
  - `_resolve_athlete` accepts UUIDs and slugs.
  - `get_athlete_data` builds the large profile payload.
  - `GET /api/athlete/<id>` returns the profile payload.
  - `GET /api/athletes/ratings` and `POST /api/athletes/batch` expose related
    athlete rating/profile snippets to other screens.
- `app/routes/matches.py` serves `GET /api/matches`, which `Athlete.tsx` uses
  for the profile match table after the profile payload returns the canonical
  athlete UUID.
- `app/photos.py` handles S3 clients, Instagram profile-photo scraping,
  profile-photo upload validation, and one-hour presigned public photo URLs.
- `app/models.py` defines `Athlete`, `AthleteMediaCoverage`, `Medal`,
  `AthleteRating`, and related data used by the profile.

Admin:

- `admin/app.py`
  - `/athletes` searches athletes by tokenized normalized name/personal name.
  - `/athlete_edit` updates Instagram handle, personal name, country fields,
    nickname translation, BJJ Heroes link, hidden-name flag, and uploaded
    profile photo.
  - `/athlete_media` adds/updates/deletes athlete media coverage links.
  - `/api/media_title` fetches page titles for media links.
  - `/athlete_matches` and `/update_all_video_links` manage per-match videos.
  - `/athlete_medals`, `/update_all_medals`,
    `/athlete_medals/find_missing`, and
    `/athlete_medals/import_candidates` support medal review/import workflows.
- `admin/templates/athlete*.html` renders the athlete search/edit/matches/medals
  and media coverage admin pages.
- `scripts/get_all_photos.py` finds athletes with `instagram_profile` but no
  `profile_image_saved_at`, downloads Instagram profile photos, uploads them to
  S3, and logs failures to `get_all_photos_errors.log`.

## Frontend APIs

`Athlete.tsx` calls:

```text
GET /api/athlete/<id>?gi=<true|false>&all_medals=<true|false>
```

- `id` is the route param from `/athlete/:id`; the backend accepts UUID or slug.
- `gi` follows the active Gi/No-Gi tab.
- `all_medals=false` returns earned/valid medals only. `all_medals=true` powers
  the medal-case toggle and includes filtered-out medals too.
- A missing athlete returns `404` with `{ "error": "Athlete not found" }`.

The profile response shape is:

```ts
interface ResponseData {
  athlete: Athlete;
  eloHistory: Elo[];
  ranks: Rank[];
  registrations: Registration[];
  medals: Medal[];
  teamHistory: TeamHistoryEntry[];
  suspensions: Suspension[];
  mediaCoverage: MediaCoverage[];
}
```

After profile data loads, `Athlete.tsx` calls:

```text
GET /api/matches?gi=<true|false>&athlete_id=<uuid>&page=<page>
```

This returns the shared `DBResults` shape used by the Database view. The profile
match query intentionally uses `athlete_id`, not name, to avoid ambiguity.

Profile interactions can also navigate into other feature surfaces:

- Rank rows update app-context ranking filters.
- Upcoming registrations open bracket/registration context.
- Medal division links open archived brackets when the medal is not
  medals-only/historical and juvenile cutover rules allow it.
- Team history links navigate to `/team/<teamSlug>`.

Admin-only supporting API:

```text
POST /api/media_title
```

`admin/templates/athlete_media.html` calls this with `{ url }` to prefill media
coverage titles. The server limits title fetches with `MAX_MEDIA_TITLE_SCAN_BYTES`.

## Key Data Items

- `Athlete.id`: UUID primary key. Used for database joins, S3 photo keys, and
  profile match lookup.
- `Athlete.slug`: unique, non-null public identifier used in `/athlete/<slug>`
  links.
- `Athlete.name` / `normalized_name`: canonical imported/full name.
- `Athlete.personal_name` / `normalized_personal_name`: display/search name
  usually sourced from Instagram or admin edits.
- `Athlete.hide_full_name`: when true and `personal_name` exists, APIs expose
  the personal name as `name` and suppress `personal_name`.
- `Athlete.instagram_profile`: stored as a bare username. The admin edit route
  strips `https://www.instagram.com/`, trailing `/`, and leading `@`.
- `Athlete.profile_image_saved_at`: timestamp marker that a profile image exists
  in S3. Public URLs are generated per request by `get_public_photo_url`; the URL
  is not stored in the database.
- S3 photo key: `photos/<athlete.id>.jpg` in normal mode and
  `photos-dev/<athlete.id>.jpg` when `DEV=1`. Presigned URLs expire after one
  hour.
- `Athlete.country`, `country_note`, `country_note_pt`: country flag and tooltip
  metadata.
- `Athlete.nickname_translation` and `bjjheroes_link`: optional profile links
  and labels.
- `AthleteRating` / `AthleteRatingAverage`: rank rows and averages used for the
  profile rank table and percentile badges.
- `MatchParticipant`: source for profile Elo/rating history and latest-match
  fallback behavior.
- `RegistrationLinkCompetitor` plus `RegistrationLink`: upcoming event cards and
  provisional belt/team context.
- `ManualPromotions`: applied with registrations and latest match data to derive
  current belt/rating display.
- `Medal`: profile medal case rows. The default view excludes `default_gold`
  medals and only includes medals with a real won match or historical medals
  before December 1, 2024.
- `AthleteMediaCoverage`: media list rows. `coverage_type` is constrained to the
  allowed media coverage types in admin code/migrations, and URLs are unique per
  athlete.
- `Suspension`: matched by `Suspension.athlete_name == athlete.name`; medals
  during suspension windows are styled as forfeited.

## Photo Handling

`app/photos.py` has two write paths:

- `save_instagram_profile_photo_to_s3` reads Instagram `og:image`, downloads the
  image if requested, accepts JPEG/PNG content types, uploads via
  `save_profile_photo_to_s3`, and only fills `personal_name` from Instagram when
  it is currently empty.
- `save_profile_photo_to_s3` validates non-empty bytes, accepts JPEG/PNG magic
  bytes for manual uploads, writes to S3, and updates
  `athlete.profile_image_saved_at`.

Admin manual uploads are capped at 1 MB by `MAX_PROFILE_PHOTO_BYTES`. The admin
template currently advertises JPEG uploads, while the shared helper accepts JPEG
or PNG; check both places if changing allowed formats.

## Tests

Run Python tests from the repository root:

```sh
make test
```

Useful focused test files while editing this feature:

- `app/tests/test_athlete_profile_api.py` for `/api/athlete/<slug>`, profile
  payload shape, medals, media coverage, and not-found behavior.
- `app/tests/test_athlete_ratings_api.py` for `/api/athletes/ratings` profile
  rating snippets and slug behavior.
- `app/tests/test_athletes_search_api.py` for athlete search/autocomplete
  behavior.
- `app/tests/test_athletes_batch_api.py` for batch athlete lookups,
  hidden-name handling, Instagram profile exposure, and rating fallback logic.

Do not run `make test-ocr` for athlete-profile-only changes. It is reserved for
OCR/livestream text scan changes.

Frontend/admin visual changes do not have an obvious targeted automated test in
this scan. For those, pair `make test` with manual checks of `/athlete/<slug>`,
the Gi/No-Gi tab, medal toggle, paginated matches, and the relevant admin page.
Do not run the frontend build routinely; `npm run build` in `app/frontend`
rewrites generated SEO snippet files.

## Regression History

Issues that have already surfaced in git history:

- `45a4aac` added slugs to the frontend and backend resolver. Keep UUID fallback
  working, but prefer slug links.
- `ef79856` changed profile matches to use `athlete_id` instead of athlete name
  to avoid wrong match rows for duplicate names.
- `15a0654` added `hide_full_name`; display/search code must use
  `personal_name` carefully when full names are hidden.
- `a224b07` stopped Instagram fetches from automatically overwriting existing
  personal names.
- `291b50d` added manual profile-photo uploads with empty-file, size, format,
  and S3 error handling.
- `a408d45` fixed profile promotion rating bumps by making the bump
  age-aware and default-rating-aware.
- `52fceb7` changed team-name display so upcoming registration teams only
  override the current team in the intended stale/no-recent-competition cases.
- `adc3dfa` fixed registration list links going to the wrong athlete when two
  athletes with the same name had different belts; avoid name-only joins when an
  athlete id is available.
- `a1874db` fixed missing kids medals and an invalid "no matches" message by
  tightening earned-medal criteria around real won matches/no-show matches.
- `137cc19` changed earned medals to include older historical medals before the
  December 1, 2024 cutoff.
- `fb79580` added the all-medals toggle and `all_medals` API parameter.
- `255e873` fixed combined juvenile age divisions for medal bracket links.
- `221a55b` added athlete media coverage, including admin title fetching and
  profile rendering.
- `07776ef` expanded media coverage types and added the Portuguese flag; keep
  frontend union types, admin constants, and migrations in sync.

## Editing Notes

- Treat `app/routes/athletes.py:get_athlete_data` as the contract owner for the
  profile payload. Update `Athlete.tsx` interfaces and `test_athlete_profile_api`
  together when changing fields.
- Keep slug and UUID resolution compatible in `/api/athlete/<id>`.
- Prefer athlete UUIDs for backend lookups once the profile is resolved.
  Name-based joins are fragile with duplicate names, hidden names, and personal
  names.
- Profile photo display depends on `profile_image_saved_at`, not on S3 object
  discovery. If a photo upload/fetch succeeds, commit the DB session so the
  timestamp is persisted.
- Be careful with Gi/No-Gi state. The same profile component refetches profile
  payload, ratings, medals, and matches when `activeTab` changes.
- Medal display has product-specific filtering. Check earned medals,
  all-medals, historical medals, default-gold medals, no-show matches, juvenile
  archive link rules, and suspension styling when changing medal logic.
- Rating/belt display is shared conceptually with athlete rankings and bracket
  registration rows. Check `docs/features/athlete-rankings.md` before changing
  promotion/default-rating behavior.
