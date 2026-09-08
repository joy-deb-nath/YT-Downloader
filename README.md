# YT-Downloader

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Chrome MV3](https://img.shields.io/badge/chrome-MV3-green.svg)](https://developer.chrome.com/docs/extensions/mv3/intro/)
[![yt-dlp](https://img.shields.io/badge/powered%20by-yt--dlp-red.svg)](https://github.com/yt-dlp/yt-dlp)
[![Flask](https://img.shields.io/badge/backend-flask-lightgrey.svg)](https://flask.palletsprojects.com/)
[![Platform](https://img.shields.io/badge/platform-windows-lightgrey.svg)](https://github.com/joy-deb-nath/YT-Downloader)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

Unpacked Chrome extension (MV3) + local Flask backend for saving videos you own — or Creative Commons / public-domain content, or anything you have explicit permission for — in the highest available merged quality (`bestvideo+bestaudio` via `yt-dlp` + `ffmpeg`).

> **Legal / ToS notice:** Only use this for your own videos, Creative Commons / public-domain content, or where you have explicit permission. Downloading other creators' videos violates YouTube ToS §4 and may infringe copyright. Do not publish this to the Chrome Web Store (YouTube downloaders are banned there). Keep the backend on `127.0.0.1` and private.

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [Tech stack](#tech-stack)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Auto-start](#auto-start)
- [API reference](#api-reference)
- [Project structure](#project-structure)
- [Configuration notes](#configuration-notes)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [Security / privacy](#security--privacy)
- [License](#license)
- [Acknowledgements](#acknowledgements)

## Features

- **Highest-quality merge** — `yt-dlp` (`bestvideo+bestaudio` → mp4, audio-only → mp3) + `ffmpeg`
- **Per-video quality picker** — `best, 2160p, 1440p, 1080p, 720p, 480p, 360p, audio` + dynamic `h{height}`, with decimal-MB estimates (`≈240.9 MB` = estimate, real size shown on Done)
- **Live progress in the popup** — `% • downloaded / total • MB/s • ETA`, polled every 600 ms, same numbers as the terminal
- **Cancel + Pause/Resume** — server-side jobs; resume reuses the same `job_id` outtmpl with `continuedl: True`. Pause keeps `.part` files, cancel deletes them
- **Server-free thumbnail + title preview** — HD thumbnail probed client-side directly from `i.ytimg.com` (`maxres → sd → hq → mq`, rejects 404s and ≤120px placeholders, no CORS needed), saved as `Thumbnail-{VideoID}.jpg` via `chrome.downloads.download()`; title/author via YouTube oEmbed (`noembed.com` fallback)
- **Modern popup UI** — thumbnail card, selectable quality cards, animated progress bar, `icons/graphic-style.svg` thumbnail button
- **Chrome range/resume (`206`) safe** — 30-minute file cache in `%TEMP%/yt-personal-saver`, `send_file(..., conditional=True, max_age=0)`

## How it works

```text
popup (active tab URL + quality)
  → POST localhost:8000/api/start {url, quality} → {job_id}
  → poll GET /api/progress?job_id= → {status, pct, downloaded, total, speed, eta}
  → done → chrome.downloads.download(GET /api/file?job_id=)

Thumbnail + title preview: fully client-side (i.ytimg.com probe + oEmbed, no server).
GET /api/thumbnail?url=&title=&json=1 → {thumb_url, filename} is fallback for non-YouTube URLs only.
Legacy: GET /api/download?url=&quality= (single-shot, no progress)
```

## Tech stack

| Layer | Technology |
|---|---|
| Extension | Chrome MV3 (unpacked/sideload), vanilla HTML/CSS/JS |
| Backend | Python 3.12, Flask, Flask-CORS |
| Download / merge | `yt-dlp`, `ffmpeg` |
| Signature decipher | Node.js / Deno / Bun / QuickJS (`js_runtimes`) + `remote_components: ["ejs:github"]` (YouTube n-challenge) |

## Requirements

- Windows + Python 3.12 (`python.exe` + `pythonw.exe`)
- `ffmpeg` in `PATH` (`ffmpeg -version`)
- Node.js **or** Deno — required as the `yt-dlp` JS runtime for signature decipher (Node 24 works; Deno recommended on Windows: `winget install DenoLand.Deno`)
- Chrome with Developer Mode enabled (for the unpacked extension)

## Installation

```powershell
# 1. Clone the repo
git clone https://github.com/joy-deb-nath/YT-Downloader.git
cd YT-Downloader

# 2. Install dependencies
pip install -r requirements.txt

# 3. Keep yt-dlp fresh (YouTube breaks old versions weekly)
pip install -U yt-dlp

# 4. Start the backend
python server.py  # → http://127.0.0.1:8000/ {"ok":true}
```

Verify the backend is up:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/
# → {"ok":true}
```

> Only run one `server.py` process at a time — two instances (e.g. terminal + `pythonw` background) conflict on port `8000`.

## Usage

### 1. Load the extension

1. Open `chrome://extensions/` → enable **Developer Mode** → **Load unpacked** → select the `extension/` folder.
2. Open one of your own / CC-licensed videos.

### 2. Download a video

1. Click the toolbar icon — video info and qualities auto-load via `GET /api/info`.
2. Pick a quality → **Download**.
3. Use **Pause/Resume** or **Cancel** as needed → the finished file lands in your Chrome Downloads folder.
4. Filenames are sanitized from the video title (`re.sub(r'[\\/*?:"<>|]', "", title)[:80]`).

### 3. Save a thumbnail (no server needed)

- Click the `🖼 Thumb` button or the preview image — even with the backend stopped.
- Thumbnails always save as `Thumbnail-{VideoID}.jpg` (best available of `maxres / sd / hq / mq`).

## Auto-start

The backend is idle-cheap (~40 MB RAM, 0% CPU), so running it in the background is fine.

| Action | How |
|---|---|
| Auto on login | `Startup\YT-Personal-Saver.bat` runs `pythonw.exe server.py` hidden on every logon (Startup-folder method — Task Scheduler creation is Access-denied in some environments) |
| Manual start | Double-click `start_server.bat` |
| Stop | Double-click `stop_server.bat` (stops `server.py` processes only) |

## API reference

All endpoints are local: `http://127.0.0.1:8000`

| Method | Endpoint | Notes |
|---|---|---|
| GET | `/` | `{ok:true}` health check |
| GET | `/api/info?url=` | `{title, duration, thumbnail (best), uploader, qualities[{key,label,height,size,size_bytes}]}`. Sizes are decimal-MB estimates; fallback static list when the n-challenge hides formats |
| POST | `/api/start` `{url, quality}` | `{job_id}` — starts a background `yt-dlp` thread (`JOBS[job_id]` with `cancelled`/`paused` flags, `progress_hook` raises `JobAbort`) |
| GET | `/api/progress?job_id=` | `{status, pct, downloaded, total, speed, eta, title, file_size, file_size_str}` — `status`: `queued / starting / downloading / merging / paused / done / cancelled / error` |
| GET | `/api/file?job_id=` | Final mp4/mp3, `Content-Disposition` = video title, range-capable |
| POST | `/api/cancel`, `/api/pause`, `/api/resume` `{job_id}` | Pause keeps `.part` for resume; cancel deletes `job_id.*` |
| GET | `/api/thumbnail?url=&title=&json=1` | Fallback for non-YouTube URLs only (YouTube thumbs download client-side). `{thumb_url (JPG), filename (Thumbnail-{id}.jpg)}`; without `json=1` it proxies JPG bytes |
| GET | `/api/download?url=&quality=` | Legacy single-shot download (no progress), cached 30 min |

## Project structure

```text
server.py            # Flask + yt-dlp + ffmpeg backend (port 8000)
requirements.txt     # flask, flask-cors, yt-dlp
start_server.bat     # manual launch (console)
stop_server.bat      # stop background server.py only
extension/
  manifest.json      # MV3, permissions, host_permissions (localhost:8000 + i.ytimg.com + youtube.com + noembed.com), icons
  popup.html         # modern UI
  popup.js           # info / qualities / progress / cancel / pause / thumbnail logic (polls /api/progress every 600 ms)
  icons/
    youtube-1.png    # toolbar + app icon (all sizes, referenced by manifest.json + popup.html)
    graphic-style.svg# thumbnail button icon
    youtube-2.png, copy-image.svg (unused spares)
```

## Configuration notes

- **JS runtimes (`BASE_OPTS.js_runtimes`)** — `node / deno / bun / quickjs` must include at least one installed runtime, otherwise YouTube signature decipher fails and formats go missing.
- **n-challenge (`BASE_OPTS.remote_components`)** — keep `["ejs:github"]`; without it yt-dlp logs `n challenge solving failed / Some formats may be missing` and the quality list can come back empty.
- **Units** — decimal MB everywhere (`/1000/1000`, `fmt_bytes` 1000-based) to match Chrome. Quality-list sizes are estimates → prefixed with `≈`; Done shows the real `file_size_str`.
- **Cache** — `%TEMP%/yt-personal-saver`, files older than 30 min are cleaned in the background; safe for Chrome `206` resume.
- **Icons** — do not rename `youtube-1.png` / `graphic-style.svg` without updating `manifest.json` + `popup.html` together.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `[youtube] n challenge solving failed / Some formats may be missing` | Install Node or Deno; `remote_components: ["ejs:github"]` is already in `BASE_OPTS` |
| Quality list says `≈240 MB` but Done shows `164 MB` | Expected — the list uses `filesize_approx` estimates, Done shows real disk size. All MB values are decimal (1000-based) to match Chrome |
| Port `8000` busy | Two `server.py` processes running (terminal + `pythonw`). Run `stop_server.bat`, keep one |
| `Merge failed - is ffmpeg installed?` | Install `ffmpeg`, add it to `PATH`, and re-open the terminal |
| `Maxres 404` on thumbnails | Normal for some videos — the client-side `sd → hq → mq` probe chain (+ yt-dlp fallback for non-YouTube URLs) covers it. Test direct thumbnails against `dQw4w9WgXcQ`, not truncated screenshot IDs |

Before reporting a format-related bug, run `pip install -U yt-dlp` and re-test — YouTube changes break old versions weekly. Verify with:

```powershell
python -m py_compile server.py
node --check extension/popup.js
python -c "import json; json.load(open('extension/manifest.json')); print('MANIFEST_OK')"
```

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repo and create a feature branch (`git checkout -b feat/my-change`).
2. Keep the conventions above (decimal MB, `Thumbnail-{VideoID}.jpg` naming, `continuedl` resume semantics, ToS disclaimer).
3. Run the verify commands above and test live (`python server.py` → `Invoke-WebRequest http://127.0.0.1:8000/` → `{"ok":true}`).
4. Open a pull request with a clear description and test notes.

Please report bugs via [GitHub Issues](https://github.com/joy-deb-nath/YT-Downloader/issues) with your `yt-dlp` version, quality key, and the relevant server log lines. Do not submit DRM/paywall bypasses, PO-token forgery, login-cookie exfiltration, or Web-Store publishing logic — those will be rejected.

## Security / privacy

- The backend binds to `127.0.0.1:8000` only — never expose it publicly without adding authentication.
- CORS is intentionally open for the local extension popup; do not loosen it further.
- No tracking, no accounts, no cookies — downloads stay on your machine.

## License

MIT — see [LICENSE](LICENSE) for details. If no `LICENSE` file is present yet, one will be added; until then all rights remain with the authors except as needed to use the code for lawful personal purposes described above.

## Acknowledgements

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for downloading and format handling
- [FFmpeg](https://ffmpeg.org/) for merging `bestvideo+bestaudio`
- [Flask](https://flask.palletsprojects.com/) for the local backend
