# vidarch

Paste a raw browser Network-tab URL dump, get the videos on disk.

Built for HLS sources where the player fetches a signed multivariant manifest.
The parser keeps one `playlist.m3u8` per video and drops the `st=video`
renditions, segment requests, and duplicate captures.

## Capture

1. DevTools → Network, check **Preserve log**, filter on `m3u8`
2. Scroll or click through the videos so each player initialises
3. Right-click any row → **Copy all listed URLs**
4. Paste into the left box

Signed links carry roughly a one-hour expiry from capture, so work in batches
rather than harvesting everything up front.

## Filenames

Without titles you get UUIDs. Paste titles into the right box, one per line, in
the same order you scrolled — the app matches them positionally and refuses to
use them unless the counts line up. Check the parsed list before starting.

Already-downloaded files are skipped, so a re-paste of an overlapping batch is
harmless.

## Deploy

Push to GitHub; Actions builds and pushes to
`ghcr.io/blakdav/vidarch:latest`. Then on the Docker VM:

```
docker compose pull && docker compose up -d
```

Point a proxy host at port 8080. Output lands in the mounted `/downloads`.

## Environment

| Variable | Default | Notes |
| --- | --- | --- |
| `OUTPUT_DIR` | `/downloads` | Where finished files land |
| `WORKERS` | `3` | Parallel downloads |
| `YTDLP_FORMAT` | `bv*+ba/b` | Best video plus best audio, else combined |

## Local run

```
pip install flask yt-dlp
OUTPUT_DIR=./out python app.py
```

Needs `ffmpeg` on PATH to mux the separate audio and video streams.
