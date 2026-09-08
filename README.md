# YT-Downloader (Personal Video Saver)

Personal-use Chrome extension (MV3, unpacked/sideload only) + local Python backend
for saving videos you own — or Creative Commons / public domain / explicit permission —
in highest available merged quality.

> **Legal / ToS notice:** Downloading other creators' videos violates YouTube ToS §4
> and may infringe copyright. This project is for your own/CC content only.
> Do not publish it to the Chrome Web Store (YouTube downloaders are banned there).
> Keep the backend on `127.0.0.1` and private.

## Features

- Highest-quality merge via `yt-dlp` (`bestvideo+bestaudio` → mp4, audio-only → mp3) + `ffmpeg`
- Per-video quality list with decimal-MB estimates (`≈240.9 MB` = estimate, actual shown on Done)
- Live progress in popup (`% • downloaded / total • MB/s • ETA`), same numbers as terminal
- Cancel + Pause/Resume (server-side, resumes `.part` files via `continuedl`)
- HD thumbnail button — works **without the server** (direct `i.ytimg.com`,
  `maxres → sd → hq → mq` probe), saved as `Thumbnail-{VideoID}.jpg`, icon `icons/graphic-style.svg`
- Title/author preview without the server (YouTube oEmbed, `noembed.com` fallback);
  only the quality list + video download need `server.py`
- Modern popup UI (thumbnail card, selectable quality cards, animated progress bar)
- Extension icon: `extension/icons/youtube-1.png`
- Chrome range/resume (`206`) safe: 30-min file cache in `%TEMP%/yt-personal-saver`

## Architecture

```text
popup (tab URL + quality)
  → POST localhost:8000/api/start {url, quality} → {job_id}
  → poll GET /api/progress?job_id= → {status, pct, downloaded, total, speed, eta}
  → done → chrome.downloads.download(GET /api/file?job_id=)
Thumbnail + title preview: fully client-side (i.ytimg.com probe + oEmbed, no server).
Server GET /api/thumbnail?url=&title=&json=1 → {thumb_url, filename} is fallback for non-YouTube URLs only.
Legacy: GET /api/download?url=&quality= (single-shot, no progress)
```

## Requirements

- Windows + Python 3.12 (`python.exe` + `pythonw.exe`)
- `ffmpeg` in PATH (`ffmpeg -version`)
- Node.js **or** Deno (yt-dlp JS runtime for signature decipher; Node 24 works)
- Chrome with Developer Mode for unpacked extension

## Quickstart

```powershell
cd C:\Xtra\cursor\YT-Downloader
pip install -r requirements.txt
pip install -U yt-dlp          # YouTube breaks old versions weekly
python server.py               # → http://127.0.0.1:8000/ {"ok":true}
```

Load extension:

1. `chrome://extensions/` → Developer Mode → Load unpacked → select `extension/`
2. Open an own/CC video → click toolbar icon → qualities auto-load
3. Pick quality → Download → Pause/Cancel if needed → file lands in Downloads
4. `🖼 Thumb` button or click preview image = HD JPG named `Thumbnail-{VideoID}.jpg` (works even with the server stopped)

## Auto-start (no terminal every time)

Idle cost is ~40 MB RAM, 0% CPU, so background run is fine.

- Auto on login: `Startup\YT-Personal-Saver.bat` runs
  `pythonw.exe server.py` hidden on every logon (no-admin Startup-folder method;
  Task Scheduler was denied in this environment).
- Manual: double-click `start_server.bat`
- Stop: double-click `stop_server.bat` (ends task + kills `server.py` python only)

## API (all local, `http://127.0.0.1:8000`)

| Method | Endpoint | Notes |
|---|---|---|
| GET | `/` | `{ok:true}` health check |
| GET | `/api/info?url=` | `{title, duration, thumbnail (best), uploader, qualities[{key,label,height,size,size_bytes}]}`. Sizes decimal MB estimates; fallback static list when n-challenge hides formats |
| POST | `/api/start {url, quality}` | `{job_id}`, starts background yt-dlp thread |
| GET | `/api/progress?job_id=` | `{status, pct, downloaded, total, speed, eta, title, file_size, file_size_str}`; `status`: queued/starting/downloading/merging/paused/done/cancelled/error |
| GET | `/api/file?job_id=` | Final mp4/mp3, `Content-Disposition` = video title, range-capable |
| POST | `/api/cancel|/api/pause|/api/resume {job_id}` | Pause keeps `.part` for resume; cancel deletes `job_id.*` |
| GET | `/api/thumbnail?url=&title=&json=1` | Fallback for non-YouTube URLs only (YouTube thumbs download client-side, no server). `{thumb_url (JPG), filename (Thumbnail-{id}.jpg)}`; without `json=1` proxies JPG bytes |
| GET | `/api/download?url=&quality=` | Legacy single-shot (no progress), cached 30 min |

Quality keys: `best, 2160p, 1440p, 1080p, 720p, 480p, 360p, audio` + dynamic `h{height}`.

## Project structure

```text
server.py            # Flask + yt-dlp + ffmpeg backend (port 8000)
requirements.txt     # flask, flask-cors, yt-dlp
start_server.bat     # manual launch (console)
stop_server.bat      # stop bg server.py only
extension/
  manifest.json      # MV3, permissions, host_permissions (localhost:8000 + i.ytimg.com + youtube.com + noembed.com), icons
  popup.html         # modern UI
  popup.js           # info/qualities/progress/cancel/pause/thumb logic
  icons/
    youtube-1.png    # toolbar + store icon (all sizes)
    graphic-style.svg# thumbnail button icon
    youtube-2.png, copy-image.svg (unused spares)
```

## Troubleshooting

- `[youtube] n challenge solving failed / Some formats may be missing` → needs JS runtime + `remote_components: ["ejs:github"]` (already in `BASE_OPTS`); install Node/Deno.
- List `≈240 MB` vs Done `164 MB` → list is `filesize_approx` estimate; Done shows real disk size. MB everywhere is decimal (1000-based) to match Chrome.
- Port `8000` busy → two `server.py` running (terminal + `pythonw`). Run `stop_server.bat`, keep one.
- `Merge failed - is ffmpeg installed?` → install ffmpeg and re-open terminal.
