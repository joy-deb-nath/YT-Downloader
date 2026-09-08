# AGENTS.md — AI agent guide for YT-Downloader

## What this is

Personal-use only: MV3 unpacked Chrome extension (`extension/`) + local Flask backend
(`server.py`, port `127.0.0.1:8000`) using `yt-dlp` + `ffmpeg` to merge
`bestvideo+bestaudio`. Not for Chrome Web Store. Only own / CC / public-domain content.

## Key files

- `server.py` — Flask app. `BASE_OPTS` must keep `js_runtimes` (node/deno/bun/quickjs)
  and `remote_components: ["ejs:github"]` (YouTube n-challenge). Temp/cache:
  `%TEMP%/yt-personal-saver`, 30-min reuse (Chrome `206` resume safe).
- `extension/manifest.json` — MV3, `host_permissions` localhost + `i.ytimg.com`
  (direct thumbs) + `youtube.com` (oEmbed title) + `noembed.com` (oEmbed fallback);
  icons all point to `icons/youtube-1.png`.
- `extension/popup.html` / `popup.js` — auto-loads `/api/info` on open; starts jobs via
  `POST /api/start`, polls `/api/progress` every 600 ms. Server-free preview:
  thumbnail via direct `i.ytimg.com` probe (`<img>` load, no CORS needed) +
  title/author via YouTube oEmbed (`noembed.com` fallback); `GET /api/thumbnail?json=1`
  is fallback for non-YouTube URLs only. Thumb download = direct
  `chrome.downloads.download()`, no server needed.
- `extension/icons/graphic-style.svg` — thumbnail button icon. `youtube-1.png` — app icon.
- `start_server.bat` / `stop_server.bat` — manual launch / targeted kill (only `server.py`
  processes). Autostart lives in Windows Startup folder (`YT-Personal-Saver.bat` → `pythonw.exe`),
  **not** Task Scheduler (creation is Access-denied in this env).

## Conventions (keep them)

- Units: decimal MB everywhere (`/1000/1000`, `fmt_bytes` 1000-based) to match Chrome.
  Quality-list sizes are estimates → prefix `≈`. Done shows real `file_size_str`.
- Filenames: videos `re.sub(r'[\\/*?:"<>|]', "", title)[:80]`; thumbnails always
  `Thumbnail-{VideoID}.jpg`.
- Thumbnails: prefer direct `https://i.ytimg.com/vi/{id}/{maxres,sd,hq,mq}default.jpg`
  probed client-side via `<img>` load (reject 404s + ≤120px-wide placeholders, no CORS
  needed); title/author via oEmbed. yt-dlp `pick_best_thumbnail()` + `/api/thumbnail`
  are fallback for non-YouTube URLs only.
- Jobs: `JOBS[job_id]` with `cancelled/paused` flags; `progress_hook` raises `JobAbort`;
  resume reuses same `job_id` outtmpl with `continuedl: True`; never delete `.part` on pause,
  only on cancel. `send_file(..., conditional=True, max_age=0)` for range support.
- Keep the personal-use/ToS disclaimer in user-facing docs and `server.py` header.

## Do / don't

- DO keep backend on `127.0.0.1:8000`, CORS open only as-is; never add public hosting
  without auth.
- DO NOT add DRM/paywall/PO-token forgery, login-cookie exfiltration, or Web-Store
  publishing logic.
- DO NOT rename `youtube-1.png` / `graphic-style.svg` without updating
  `manifest.json` + `popup.html` together.
- DO NOT create new `.md` docs unless the user asks.

## Verify (run from `C:\Xtra\cursor\YT-Downloader`)

```powershell
python -m py_compile server.py
node --check extension/popup.js
python -c "import json; json.load(open('extension/manifest.json')); print('MANIFEST_OK')"
pip install -U yt-dlp   # before any format-related test; YouTube breaks weekly
```

Live check: `python server.py`, then `Invoke-WebRequest http://127.0.0.1:8000/`
→ `{"ok":true}`. Only one `server.py` process at a time (port conflict otherwise).

## Common pitfalls

- `Maxres 404` is normal for some videos; the client-side `sd → hq → mq` probe chain
  (+ yt-dlp fallback for non-YouTube URLs) covers it. Test direct thumbs against
  `dQw4w9WgXcQ`, not truncated screenshot IDs.
- `schtasks /create` and `Register-ScheduledTask` fail here (Access denied) — use the
  Startup-folder `.bat` + `pythonw.exe` pattern instead.
