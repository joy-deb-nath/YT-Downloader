"""
Personal-use video saver backend.
Only use for videos you own, or Creative Commons / public domain,
or where you have explicit permission. Respect YouTube ToS and copyright.
Requires: python, ffmpeg in PATH, pip install -r requirements.txt
Run: python server.py
"""
import os
import re
import uuid
import tempfile
import threading
import time
from pathlib import Path
from flask import Flask, request, jsonify, send_file, after_this_request
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

TMPDIR = Path(tempfile.gettempdir()) / "yt-personal-saver"
TMPDIR.mkdir(parents=True, exist_ok=True)

JOBS: dict[str, dict] = {}

# Allow node/deno/bun/quickjs for YouTube signature decipher.
# Install one to remove the "No supported JavaScript runtime" warning
# and get full highest-quality formats. Deno is recommended on Windows:
#   winget install DenoLand.Deno
JS_RUNTIMES = {"node": {}, "deno": {}, "bun": {}, "quickjs": {}}

BASE_OPTS = {
    "quiet": True,
    "noplaylist": True,
    "js_runtimes": JS_RUNTIMES,
    # yt-dlp 2025+: YouTube n-challenge needs remote EJS solver, else
    # "Some formats may be missing" and qualities list comes back empty.
    "remote_components": ["ejs:github"],
}

# Cleanup files older than 30 min in background
def cleanup_loop():
    while True:
        try:
            now = time.time()
            for f in TMPDIR.glob("*.*"):
                if now - f.stat().st_mtime > 1800:
                    try:
                        f.unlink()
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(600)

threading.Thread(target=cleanup_loop, daemon=True).start()

QUALITY_MAP = {
    "best": "bestvideo+bestaudio/best",
    "2160p": "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best",
    "1440p": "bestvideo[height<=1440]+bestaudio/best[height<=1440]/best",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
    "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
    "audio": "bestaudio/best",
}


def resolve_format(quality: str) -> str:
    if quality in QUALITY_MAP:
        return QUALITY_MAP[quality]
    # exact yt-dlp format id, e.g. f_22
    if quality.startswith("f_"):
        return quality[2:]
    return QUALITY_MAP["best"]


def fmt_bytes(n) -> str:
    # Decimal MB to match Chrome download bar / YouTube (1000-based, not 1024 MiB)
    if not n:
        return ""
    try:
        n = float(n)
    except Exception:
        return ""
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1000:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1000
    return f"{n:.1f} TB"


def extract_youtube_id(url: str) -> str:
    import urllib.parse
    try:
        p = urllib.parse.urlparse(url)
        if "youtu.be" in p.netloc:
            return p.path.strip("/").split("/")[0].split("?")[0]
        q = urllib.parse.parse_qs(p.query)
        if "v" in q and q["v"]:
            return q["v"][0]
        m = re.search(r"(?:v=|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{6,})", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def youtube_thumb_jpg_urls(video_id: str) -> list[str]:
    base = f"https://i.ytimg.com/vi/{video_id}"
    # highest first, all JPG, no expiry, no signing
    return [f"{base}/maxresdefault.jpg", f"{base}/sddefault.jpg",
            f"{base}/hqdefault.jpg", f"{base}/mqdefault.jpg"]


def pick_best_thumbnail(info: dict) -> str:
    thumbs = info.get("thumbnails") or []
    best = ""
    best_score = -1
    for t in thumbs:
        u = t.get("url")
        if not u:
            continue
        w = t.get("width") or 0
        h = t.get("height") or 0
        score = (w * h, w)
        if score > (best_score, 0):
            # unpack: compare area first
            best_score = w * h
            best = u
    return best or info.get("thumbnail") or ""


class JobAbort(Exception):
    pass

YOUTUBE_RE = re.compile(r"^(https?://)?(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/")

def is_supported_url(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    # Keep generic to allow own/CC content, but popup is optimized for YouTube
    return True

@app.route("/api/info")
def api_info():
    url = request.args.get("url", "").strip()
    if not is_supported_url(url):
        return jsonify({"error": "Invalid URL"}), 400
    try:
        with yt_dlp.YoutubeDL({**BASE_OPTS}) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get("formats", []) or []
        # best audio size for merged estimate
        audio_sizes = [
            f.get("filesize") or f.get("filesize_approx") or 0
            for f in formats
            if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")
        ]
        best_audio = max(audio_sizes) if audio_sizes else 0

        # group video-only + progressive by height
        by_height: dict[int, dict] = {}
        for f in formats:
            h = f.get("height")
            if not h:
                continue
            vcodec = f.get("vcodec")
            if vcodec in (None, "none"):
                continue
            size = f.get("filesize") or f.get("filesize_approx") or 0
            prev = by_height.get(h)
            # prefer mp4 / larger size
            score = (1 if f.get("ext") == "mp4" else 0, size)
            prev_score = (0, 0) if not prev else prev["_score"]
            if not prev or score > prev_score:
                by_height[h] = {
                    "height": h,
                    "ext": f.get("ext"),
                    "format_id": f.get("format_id"),
                    "vcodec": vcodec,
                    "fps": f.get("fps"),
                    "video_size": size,
                    "_score": score,
                }

        qualities = []
        for h in sorted(by_height.keys(), reverse=True):
            v = by_height[h]
            merged = (v["video_size"] or 0) + (best_audio or 0)
            key = f"{h}p" if f"{h}p" in QUALITY_MAP else f"h{h}"
            # ensure dynamic heights still downloadable
            if key.startswith("h"):
                QUALITY_MAP[key] = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
            qualities.append({
                "key": key,
                "label": f"{h}p{'60' if (v.get('fps') or 0) >= 50 else ''} • {v.get('ext','mp4')}",
                "height": h,
                "format_id": v["format_id"],
                "size_bytes": merged or v["video_size"] or None,
                "size": fmt_bytes(merged or v["video_size"]),
            })

        # Always add Best + Audio options on top/bottom
        if qualities:
            top_size = qualities[0].get("size_bytes")
            qualities.insert(0, {
                "key": "best",
                "label": "Best • auto merge",
                "height": qualities[0]["height"],
                "format_id": None,
                "size_bytes": top_size,
                "size": fmt_bytes(top_size),
            })
        else:
            # Fallback when YouTube challenge fails and formats are hidden:
            # still allow download, sizes unknown until download starts.
            for key, label in [
                ("best", "Best • auto merge"),
                ("2160p", "2160p • mp4"),
                ("1440p", "1440p • mp4"),
                ("1080p", "1080p • mp4"),
                ("720p", "720p • mp4"),
                ("480p", "480p • mp4"),
                ("360p", "360p • mp4"),
            ]:
                qualities.append({"key": key, "label": label, "height": 0,
                                  "format_id": None, "size_bytes": None, "size": ""})
        audio_only_size = best_audio or None
        qualities.append({
            "key": "audio",
            "label": "Audio only • mp3",
            "height": 0,
            "format_id": None,
            "size_bytes": audio_only_size,
            "size": fmt_bytes(audio_only_size),
        })

        return jsonify({
            "title": info.get("title"),
            "duration": info.get("duration"),
            "thumbnail": pick_best_thumbnail(info),
            "uploader": info.get("uploader"),
            "qualities": qualities,
        })
    except Exception as e:
        return jsonify({"error": str(e)[:500]}), 500


@app.route("/api/thumbnail")
def api_thumbnail():
    """Always JPG named as video. ?json=1 returns {thumb_url, filename} for direct download."""
    import urllib.request
    import urllib.error
    url = request.args.get("url", "").strip()
    title_hint = request.args.get("title", "").strip()
    want_json = request.args.get("json") == "1"
    if not is_supported_url(url):
        return jsonify({"error": "Invalid URL"}), 400
    try:
        vid = extract_youtube_id(url)
        # Get clean video title (prefer hint from popup which already has info)
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title_hint)[:80]
        if not safe_title:
            try:
                with yt_dlp.YoutubeDL({**BASE_OPTS}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    safe_title = re.sub(r'[\\/*?:"<>|]', "", info.get("title", ""))[:80]
                    if not vid:
                        vid = info.get("id", "")
            except Exception:
                pass
        if not safe_title:
            safe_title = vid or "thumbnail"
        filename = f"{safe_title}.jpg"

        # 1. Direct YouTube JPGs - highest first, always JPG, no expiry
        direct_urls = youtube_thumb_jpg_urls(vid) if vid else []
        best_direct = ""
        if want_json:
            # Probe first reachable JPG to avoid downloading 120x90 placeholder?
            # maxres returns 404 when missing, so check quickly.
            for u in direct_urls:
                try:
                    req = urllib.request.Request(u, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=10) as r:
                        if r.status == 200 and int(r.headers.get("Content-Length", "1000")) > 5000:
                            best_direct = u
                            break
                except Exception:
                    continue
            if not best_direct and direct_urls:
                best_direct = direct_urls[1] if len(direct_urls) > 1 else direct_urls[0]
            if best_direct:
                return jsonify({"thumb_url": best_direct, "filename": filename})
            # fallback to yt-dlp pick below
        else:
            for u in direct_urls:
                try:
                    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        if resp.status != 200:
                            continue
                        data = resp.read()
                        # skip tiny placeholder (no maxresikator -> 120px image)
                        if len(data) < 5000:
                            continue
                        thumb_path = TMPDIR / f"{vid}_thumb.jpg"
                        thumb_path.write_bytes(data)
                        return send_file(str(thumb_path), as_attachment=True,
                                         download_name=filename,
                                         mimetype="image/jpeg", conditional=True, max_age=0)
                except (urllib.error.HTTPError, Exception):
                    continue

        # 2. Fallback: yt-dlp best thumbnail (may be webp) -> serve as-is but named .jpg only if jpg
        with yt_dlp.YoutubeDL({**BASE_OPTS}) as ydl:
            info = ydl.extract_info(url, download=False)
            best = pick_best_thumbnail(info)
        if not best:
            return jsonify({"error": "No thumbnail found"}), 404
        if want_json:
            return jsonify({"thumb_url": best, "filename": filename})
        req = urllib.request.Request(best, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        thumb_path = TMPDIR / f"{vid or 'thumb'}_thumb.jpg"
        thumb_path.write_bytes(data)
        return send_file(str(thumb_path), as_attachment=True,
                         download_name=filename,
                         mimetype="image/jpeg", conditional=True, max_age=0)
    except Exception as e:
        return jsonify({"error": str(e)[:500]}), 500

@app.route("/api/download")
def api_download():
    url = request.args.get("url", "").strip()
    quality = request.args.get("quality", "best")
    if not is_supported_url(url):
        return jsonify({"error": "Invalid URL"}), 400
    fmt = resolve_format(quality)

    is_audio = quality == "audio"
    ext = "mp3" if is_audio else "mp4"

    # 1. Resolve video id first without downloading, to enable cache reuse.
    # This prevents Chrome's range/resume requests (206) from triggering
    # a full re-download via yt-dlp every time.
    try:
        with yt_dlp.YoutubeDL({**BASE_OPTS}) as ydl:
            pre = ydl.extract_info(url, download=False)
            vid = pre.get("id", uuid.uuid4().hex[:12])
            safe_title = re.sub(r'[\\/*?:"<>|]', "", pre.get("title", "video"))[:80] or "video"
    except Exception:
        vid = uuid.uuid4().hex[:12]
        safe_title = "video"

    cached = TMPDIR / f"{vid}_{quality}.{ext}"
    # Reuse cache if fresh (<30 min) - fixes 206 double-hit
    if cached.exists() and (time.time() - cached.stat().st_mtime < 1800):
        dl_name = f"{safe_title}.{ext}"
        return send_file(str(cached), as_attachment=True, download_name=dl_name,
                         conditional=True, max_age=0)

    file_id = uuid.uuid4().hex
    out_tmpl = str(TMPDIR / f"{file_id}.%(ext)s")

    ydl_opts = {
        **BASE_OPTS,
        "format": fmt,
        "outtmpl": out_tmpl,
        "merge_output_format": "mp3" if is_audio else "mp4",
        "continuedl": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
        }] if is_audio else [],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Resolve final filename
            if is_audio:
                final_tmp = TMPDIR / f"{file_id}.mp3"
            else:
                # yt-dlp merges to mp4, but ext may vary; find newest file with our id
                candidates = list(TMPDIR.glob(f"{file_id}.*"))
                final_tmp = max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None
                if final_tmp is None:
                    raise FileNotFoundError("Merge failed - is ffmpeg installed?")
            safe_title = re.sub(r'[\\/*?:"<>|]', "", info.get("title", safe_title))[:80] or "video"
            dl_name = f"{safe_title}.{ext}"
            # Promote to cache name for resume / 206 reuse
            try:
                if cached.exists():
                    cached.unlink()
                final_tmp.rename(cached)
            except Exception:
                cached = final_tmp

            return send_file(str(cached), as_attachment=True, download_name=dl_name,
                             conditional=True, max_age=0)
    except Exception as e:
        return jsonify({"error": str(e)[:1000]}), 500

def _cleanup_job_files(job_id: str):
    for p in TMPDIR.glob(f"{job_id}.*"):
        try:
            p.unlink()
        except Exception:
            pass


def _run_job(job_id: str, url: str, quality: str):
    job = JOBS[job_id]
    is_audio = quality == "audio"
    ext = "mp3" if is_audio else "mp4"
    fmt = resolve_format(quality)

    def hook(d):
        if job.get("cancelled"):
            raise JobAbort("Cancelled by user")
        if job.get("paused"):
            raise JobAbort("Paused by user")
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            pct = (downloaded / total * 100) if total else 0
            job.update({
                "status": "downloading",
                "pct": round(pct, 1),
                "downloaded": downloaded,
                "total": total,
                "speed": d.get("speed"),
                "eta": d.get("eta"),
                "filename": d.get("filename", ""),
            })
        elif d.get("status") == "finished":
            job.update({"status": "merging", "pct": 100})

    # If resuming, don't reset progress
    if job.get("status") != "paused":
        job.update({"status": "starting", "pct": 0, "cancelled": False, "paused": False})

    try:
        # Resolve id/title for cache name
        with yt_dlp.YoutubeDL({**BASE_OPTS}) as ydl:
            pre = ydl.extract_info(url, download=False)
            vid = pre.get("id", job_id[:12])
            job["title"] = pre.get("title", "") or job.get("title", "")
            job["thumbnail"] = pre.get("thumbnail", "") or job.get("thumbnail", "")
            job["duration"] = pre.get("duration", 0)
    except Exception:
        vid = job_id[:12]

    cached = TMPDIR / f"{vid}_{quality}.{ext}"
    if cached.exists() and (time.time() - cached.stat().st_mtime < 1800):
        try:
            sz = cached.stat().st_size
        except Exception:
            sz = 0
        job.update({"status": "done", "pct": 100, "file": str(cached),
                    "title": job.get("title") or cached.stem, "paused": False,
                    "file_size": sz, "file_size_str": fmt_bytes(sz)})
        return

    file_id = job_id
    out_tmpl = str(TMPDIR / f"{file_id}.%(ext)s")
    ydl_opts = {
        **BASE_OPTS,
        "format": fmt,
        "outtmpl": out_tmpl,
        "merge_output_format": "mp3" if is_audio else "mp4",
        "continuedl": True,
        "progress_hooks": [hook],
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
        }] if is_audio else [],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            job["title"] = info.get("title", job.get("title", "video"))
            if is_audio:
                final_tmp = TMPDIR / f"{file_id}.mp3"
            else:
                cands = [p for p in TMPDIR.glob(f"{file_id}.*") if p.suffix not in (".part", ".ytdl", ".temp")]
                final_tmp = max(cands, key=lambda p: p.stat().st_mtime) if cands else None
                if final_tmp is None:
                    raise FileNotFoundError("Merge failed - is ffmpeg installed?")
            try:
                if cached.exists():
                    cached.unlink()
                final_tmp.rename(cached)
            except Exception:
                cached = final_tmp
            try:
                sz = Path(cached).stat().st_size
            except Exception:
                sz = 0
            job.update({"status": "done", "pct": 100, "file": str(cached), "paused": False,
                        "file_size": sz, "file_size_str": fmt_bytes(sz)})
    except JobAbort as e:
        msg = str(e)
        if job.get("cancelled"):
            _cleanup_job_files(job_id)
            job.update({"status": "cancelled", "error": "Cancelled"})
        elif job.get("paused") or "Paused" in msg:
            job.update({"status": "paused"})
        else:
            job.update({"status": "error", "error": msg[:1000]})
    except Exception as e:
        # yt-dlp wraps our abort, detect pause/cancel
        m = str(e)[:1000]
        if job.get("cancelled"):
            _cleanup_job_files(job_id)
            job.update({"status": "cancelled", "error": "Cancelled"})
        elif job.get("paused"):
            job.update({"status": "paused"})
        else:
            job.update({"status": "error", "error": m})


@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or request.args.get("url", "")).strip()
    quality = data.get("quality") or request.args.get("quality", "best")
    if not is_supported_url(url):
        return jsonify({"error": "Invalid URL"}), 400
    # allow dynamic hXXX keys created by /api/info
    if quality not in QUALITY_MAP and not quality.startswith(("f_", "h")):
        quality = "best"
    if quality.startswith("h"):
        try:
            h = int(quality[1:])
            QUALITY_MAP[quality] = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
        except Exception:
            quality = "best"
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "queued", "pct": 0, "url": url,
                    "quality": quality, "title": "", "error": "",
                    "cancelled": False, "paused": False}
    threading.Thread(target=_run_job, args=(job_id, url, quality), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/cancel", methods=["POST"])
def api_cancel():
    data = request.get_json(force=True, silent=True) or {}
    job_id = data.get("job_id") or request.args.get("job_id", "")
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job"}), 404
    if job.get("status") in ("done", "cancelled", "error"):
        _cleanup_job_files(job_id)
        job.update({"status": "cancelled"})
        return jsonify({"status": "cancelled"})
    job["cancelled"] = True
    job["paused"] = False
    job.update({"status": "cancelling"})
    return jsonify({"status": "cancelling"})


@app.route("/api/pause", methods=["POST"])
def api_pause():
    data = request.get_json(force=True, silent=True) or {}
    job_id = data.get("job_id") or request.args.get("job_id", "")
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job"}), 404
    if job.get("status") not in ("downloading", "starting", "queued", "merging"):
        return jsonify({"error": f"Cannot pause from {job.get('status')}"}), 400
    job["paused"] = True
    # status flips to paused on next hook; force it for snappy UI
    if job.get("status") == "queued":
        job.update({"status": "paused"})
    return jsonify({"status": "pausing"})


@app.route("/api/resume", methods=["POST"])
def api_resume():
    data = request.get_json(force=True, silent=True) or {}
    job_id = data.get("job_id") or request.args.get("job_id", "")
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job"}), 404
    if job.get("status") != "paused":
        return jsonify({"error": f"Cannot resume from {job.get('status')}"}), 400
    job["paused"] = False
    job["cancelled"] = False
    job.update({"status": "queued"})
    threading.Thread(target=_run_job, args=(job_id, job["url"], job["quality"]), daemon=True).start()
    return jsonify({"status": "queued"})


@app.route("/api/progress")
def api_progress():
    job_id = request.args.get("job_id", "")
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job"}), 404
    # Don't leak full path
    out = {k: v for k, v in job.items() if k != "file"}
    out["job_id"] = job_id
    if job.get("status") == "done":
        out["file_url"] = f"/api/file?job_id={job_id}"
    return jsonify(out)


@app.route("/api/file")
def api_file():
    job_id = request.args.get("job_id", "")
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        return jsonify({"error": "Not ready"}), 400
    path = Path(job["file"])
    if not path.exists():
        return jsonify({"error": "File expired"}), 410
    ext = "mp3" if job.get("quality") == "audio" else "mp4"
    safe_title = re.sub(r'[\\/*?:"<>|]', "", job.get("title", "video"))[:80] or "video"
    return send_file(str(path), as_attachment=True, download_name=f"{safe_title}.{ext}",
                     conditional=True, max_age=0)


@app.route("/")
def index():
    return jsonify({"ok": True, "msg": "Run extension popup to download. Use only own/CC content."})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
