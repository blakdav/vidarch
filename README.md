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

## Capture instructions

Built into the UI — expand *Getting links out of a browser* on the page. Covers
finding stable page URLs, the network-panel workflow for manifest capture, and
the expiry window on signed links.

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
