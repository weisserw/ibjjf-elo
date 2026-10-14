# YouTube archiver media 403 investigation

Investigated October 13, 2026. The supplied `worker.log` confirms the deployed
version and download failures. Validation of a rebuilt worker remains
outstanding; conclusions below combine production logs, repository code,
and upstream evidence.

## Main finding

Both supplied media URLs identify `c=ANDROID_VR`. The repository pinned
yt-dlp 2026.7.4, whose unauthenticated defaults are `android_vr,web_safari`
when a supported JavaScript runtime is available, or just `android_vr`
otherwise. The worker requests `web_embedded,default`.

Upstream removed Android VR from defaults after reporting widespread media
403 failures starting August 17, including format 18. That is the format in
the supplied ffmpeg command. The fix shipped in 2026.08.19, whose
unauthenticated defaults are `visionos,web` (or `visionos` without JS).
This is a strong explanation for the media failures, not proof that every
error has the same cause.

Sources:

- [Upstream Android VR failure and fix](https://github.com/yt-dlp/yt-dlp/pull/17461)
- [August stable release](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.08.19)
- [July client selection implementation](https://github.com/yt-dlp/yt-dlp/blob/2026.07.04/yt_dlp/extractor/youtube/_video.py)
- [August client selection implementation](https://github.com/yt-dlp/yt-dlp/blob/2026.08.19/yt_dlp/extractor/youtube/_video.py)

## Why embedding and cookies appear to matter

`web_embedded` only supports embeddable videos. Disabling embedding removes
that working option and exposes failures in the remaining clients. Reordering
to `default,web_embedded` changes request order but does not remove Android VR
from the July defaults or guarantee a different selected media source.

Authenticated cookies also change what `default` expands to. Thus the other
app's improvement after both adding Firefox cookies and changing order cannot
be attributed to order alone. Cookies are not necessary for the dependency
fix and are not the first recommended intervention.

See [upstream client restrictions and token guidance](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide).

## Three reported errors

- `Video unavailable` for `xlF6WMpUkcI` is an extraction failure. The message
  alone does not establish whether the cause is embedding, video availability,
  region/account restrictions, client behavior, or VPN/IP treatment.
- ffmpeg exit status 8 means extraction failed, but its stderr is needed for
  the actual reason. The URL is Android VR format 18, consistent with the
  upstream failure; the exit code alone does not prove an HTTP 403.
- The explicit DASH HTTP 403 for `xrGlt61mQpU`, format 135, is a media-server
  rejection of an Android VR URL. Changing the webpage Referer alone is not
  an established solution.

The follow-up logs show an occasional success using a different format and
protocol, detailed below. No channel-level correlation or embedding flag has
been independently verified.

## Follow-up: production worker.log

The supplied 500 log lines contain 39 segment attempts beginning between
10:00:33 and 10:32:17 p.m. EDT on October 13 (02:00:33–02:32:17 UTC October 14).
All probe configurations report yt-dlp 2026.07.04, Node at `/usr/bin/node`,
`ejs:github`, `web_embedded,default`, and no cookies. Node is configured and
present; these lines alone do not establish successful JS challenge solving.

| Outcome | Attempts | Evidence |
| --- | ---: | --- |
| ffmpeg media HTTP 403 | 21 | Android VR format 18; explicit input-open HTTP 403 in stderr |
| Extraction unavailable | 17 | `Video unavailable` before a successful probe |
| Uploaded successfully | 1 | Format 94, 854×480, `m3u8_native`; 3,600 sampled frames |

The successful attempt was `sIcjL2zcJbE`, range 7200–10800. It selected HLS
format 94 and uploaded all crops. Three subsequent attempts on that video's
next segment (10800–14400) selected direct HTTPS format 18 and failed with
Android VR HTTP 403. The successful request's client is not logged, so it
cannot be attributed specifically to the embedded or Safari client.

This establishes that at least one intermittent success used a different
format/protocol. It does not show the same Android VR request randomly
becoming valid. ffmpeg connection-reuse messages occurred during the
successful HLS download but did not prevent its completion.

All 21 media failures occurred when opening freshly probed inputs. Their
signed URL expiry timestamps were approximately six hours after the attempt,
so expired URLs do not explain these failures. There are no DASH download
attempts in this excerpt; the earlier supplied DASH 403 remains separate
evidence. The excerpt also contains no yt-dlp warnings, consistent with the
worker's warning suppression, so the 17 extraction failures remain unresolved.

The first intervention remains rebuilding and deploying the updated yt-dlp
pin without cookies. If extraction failures persist, enable yt-dlp warning
logging to reveal the per-client reasons before changing authentication or
egress. Retrying the old client repeatedly is demonstrably producing little
progress in this sample.

## Worker behavior that amplifies or obscures failures

- `probe_youtube_archive()` probes anew on each segment attempt. Its format
  fallback runs only for `Requested format is not available`; media download
  403s do not trigger an alternate-client/format attempt.
- `download_dash_fragment_section()` passes selected-format HTTP headers.
  ffmpeg's direct URL path does not. Header propagation is a separate
  improvement to consider if direct downloads still fail after the update;
  it cannot explain the DASH failure by itself.
- yt-dlp warnings are suppressed with `no_warnings=True`, hiding useful
  client, JS challenge, and missing-token diagnostics.
- ffmpeg stderr goes to worker logs, while the persisted error contains only
  the subprocess failure and command. Inspect the preceding worker log lines.
- Failed segments restart rather than checkpointing partial downloads.
  Archive failure backoff is normally 300–600 seconds; successful captures
  also impose a shared five-minute cooldown. These magnify slow progress but
  do not cause the underlying rejection.

## Change and validation

Updated `requirements.txt` to yt-dlp 2026.8.19. No cookies, client-order
changes, retry-policy changes, or production deployment were performed.

Repository validation: `make test` passed (724 tests, 4 skipped), and
`git diff --check` passed. Tests ran with the existing local environment;
dependencies were not reinstalled. These checks do not validate the new
package in a rebuilt image or real YouTube downloads through the cloud VPN.

1. Rebuild and redeploy the capture worker. Confirm its `yt-dlp probe config`
   reports 2026.08.19, Node, and the intended extractor arguments. Check for
   deployment overrides that explicitly request Android VR.
2. Retry one previously failing segment on the same VPN egress, without
   cookies. Verify actual download and crop upload; metadata probing alone
   is insufficient. Check both a direct media format and a DASH stream if
   available, plus an embeddable control video.
3. If failures persist, capture yt-dlp warnings and ffmpeg stderr in the same
   worker environment. Compare successful and failed attempts by client,
   protocol, format, and version. Do not share cookies or signed URLs.
4. For persistent failures on current non-embedded clients, evaluate the
   upstream-recommended `mweb` plus an automatic PO Token provider. This can
   avoid account-cookie management but introduces another service/plugin;
   it is a second step, not part of this patch. A VPN/IP rejection may still
   require an egress comparison, which local laptop testing cannot establish.

## Follow-up: slow format 135 after the version update

The rebuilt worker reports 2026.08.19 and successfully opens video
`J9Co8PiUyDI`. Its primary selector is unavailable, so it selects video-only
format 135: H.264, 854×480, 30 fps, approximately 497 kbit/s, direct HTTPS.
This is an ordinary YouTube video format, not evidence of unusual IBJJF
scoreboard layout or content encoding.

The supplied progress moves from 53 to 234 seconds in 90 wall-clock seconds,
about 2× playback speed (roughly 30 minutes per one-hour segment). The user
reports ffmpeg CPU at 5.3% and FFmpeg 7.1.5 in the container. Together these
support an I/O bottleneck, although they do not isolate YouTube throttling
from VPN/CDN bandwidth conditions.

The worker was dropping an extractor download instruction: yt-dlp attaches
`downloader_options.http_chunk_size = 10 << 20` to direct YouTube formats.
Passing just the URL to ffmpeg loses this setting and the selected HTTP
headers. FFmpeg 7.1 lacks the native `request_size` option available in 8.1.

Sources:

- [yt-dlp direct-format chunk setting](https://github.com/yt-dlp/yt-dlp/blob/2026.08.19/yt_dlp/extractor/youtube/_video.py)
- [yt-dlp bounded Range downloader](https://github.com/yt-dlp/yt-dlp/blob/2026.08.19/yt_dlp/downloader/http.py)
- [FFmpeg 7.1 HTTP options](https://github.com/FFmpeg/FFmpeg/blob/n7.1/libavformat/http.c)
- [FFmpeg 8.1 HTTP options](https://github.com/FFmpeg/FFmpeg/blob/n8.1/libavformat/http.c)

Added `scripts/livestream_media_source.py`: for direct HTTP formats that
specify a chunk size, ffmpeg reads a temporary loopback endpoint. Its seeks
are translated into bounded upstream byte-range requests using the selected
headers. No whole-video download or frame-sampling change is required.
Upstream responses are checked for matching offsets, sizes, and completeness;
failures are surfaced without printing signed URLs. Local DASH files and HLS
formats retain their existing paths.

Validation: `make test` passed, 731 tests with 4 skipped. Seven new tests cover
range reassembly, seeks, headers, upstream rejection, mid-download failure,
pass-through formats, and actual ffmpeg decoding compared with the same
local MP4. This establishes correctness, not a production speedup.

Rebuild/redeploy and compare the same video's progress over a few minutes.
Expect `Using bounded HTTP media requests: chunk_bytes=10485760` before
ffmpeg progress. If throughput stays near 2× playback, investigate VPN/CDN
throughput and client-specific throttling further rather than assuming the
format itself is slow.
