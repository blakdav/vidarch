# vidarch

A self-hosted queue for archiving video. Paste links, get files on a volume.

Wraps yt-dlp with a web UI, parallel workers, and a resumable archive file, so
batches survive a closed laptop and land next to everything else on the server.

## Input

One textarea takes three line shapes, mixed freely:

```
https://host.example/video/123
-o "01 - First Video.%(ext)s" https://host.example/video/456
https://cdn.example/.../playlist.m3u8?...
```

Plain URLs are handed straight to yt-dlp, which names files from the source's
metadata. The `-o` form overrides that — useful when the host's stored titles
are internal slugs rather than the names you want, and the numeric prefix is
what preserves ordering, since files sort by name and not by completion time.

Manifest URLs are filtered on the way in: video-only renditions, segment
requests, and duplicate captures of the same media are dropped, so a raw
network-panel dump can be pasted without cleaning it first.

**Check links** previews what was parsed and what already exists on disk.
Nothing downloads until **Start downloads**.

## Referer and subfolder

Some hosts serve video only when the request claims to come from the embedding
site. Put that page URL in the referer field; one value usually covers every
video on the same site.

The subfolder field groups a batch into its own directory under the volume.

## Building a link list

Expand *Building a link list* in the UI. It walks through locating the site's
content JSON in the network panel, checking it carries both a video identifier
and a title, copying the response body and request URL, and handing those to an
assistant with a prompt that specifies the exact output format. The result is a
console script that prints ready-to-paste `-o` lines.

That script is per-site by necessity, since field names and route patterns
differ. Enumeration also has to run in a logged-in browser, because same-origin
requests are what carry the session.

Manifest capture is documented as a last resort for players whose URLs can't be
reproduced outside the browser.

## Deploy

Push to GitHub; Actions builds and pushes to `ghcr.io/blakdav/vidarch:latest`.
On the Docker host:

```
docker compose pull && docker compose up -d
```

Point a proxy host at port 8080. Adjust the volume path in
`docker-compose.yml` before first run.

## Environment

| Variable | Default | Notes |
| --- | --- | --- |
| `OUTPUT_DIR` | `/downloads` | Where finished files land |
| `WORKERS` | `3` | Parallel downloads |
| `YTDLP_FORMAT` | `bv*+ba/b` | Best video plus best audio, else combined |

Completed downloads are recorded in `.vidarch-archive` on the volume, keyed by
source and video id. Re-pasting an overlapping batch is harmless; delete that
file to force a redownload.

## Local run

```
pip install flask yt-dlp
OUTPUT_DIR=./out python app.py
```

Needs `ffmpeg` on PATH to merge separate audio and video streams.

## Limits

- Enumeration is not automated. Finding every video on a site is site-specific
  and generally needs a logged-in browser session, so collecting the links
  stays a manual step.
- Signed manifest links expire, typically about an hour from capture. Work in
  batches when using that route.
- DRM-protected sources are out of scope.
