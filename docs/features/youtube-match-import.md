# YouTube Match Import

The YouTube match importer discovers individual IBJJF match uploads, proposes
the bracket match represented by each video, and lets an administrator review
the proposals before applying video links.

## Main components

- `scripts/update_youtube_match_videos.py` fetches uploads from the configured
  YouTube source.
- `scripts/youtube_match_import_lib.py` parses titles and divisions, scores
  events and match candidates, assigns default review selections, and imports
  approved links.
- `admin/app.py` exposes the scan, source-update, and import routes.
- `admin/templates/youtube_match_videos_scan.html` renders the review form.
- `YoutubeMatchVideo` in `app/models.py` stores scraped metadata and the match
  ultimately linked to the upload.
- `app/tests/test_youtube_match_import_lib.py` covers parsing, matching,
  persistence, and the admin review flow.

## Review and import behavior

High-confidence matches are shown as checkboxes. Ambiguous videos are shown as
one radio group per video, with candidate matches and a `None` option. Selecting
`None` submits an empty value; the import route deliberately omits that video
from the selections passed to `import_youtube_match_video_links()`, so it is not
imported. The default candidate remains selected until an administrator chooses
another candidate or `None`.

The importer refuses to replace a different existing match video link and
prevents one match from being assigned to multiple selected YouTube videos in a
single import.

## Related behavior

Successful imports schedule a refresh of the cached homepage covered-match
count. See [Homepage Video Count](homepage-video-count.md).
