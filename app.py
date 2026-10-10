import os
import re
import shutil
import tempfile
import time
from collections import defaultdict
from urllib.parse import urlparse

import yt_dlp
from flask import Flask, jsonify, request, send_file, send_from_directory, after_this_request

app = Flask(__name__, static_folder="static")

ALLOWED_HOSTS = (
    "youtube.com", "youtu.be", "tiktok.com", "facebook.com", "fb.watch",
)
MAX_DURATION = 30 * 60
MAX_REQUESTS_PER_MIN = 6
_hits = defaultdict(list)


def rate_limited(ip):
    now = time.time()
    _hits[ip] = [t for t in _hits[ip] if now - t < 60]
    if len(_hits[ip]) >= MAX_REQUESTS_PER_MIN:
        return True
    _hits[ip].append(now)
    return False


def valid_url(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if urlparse(url).scheme not in ("http", "https"):
        return False
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def base_opts():
    return {"quiet": True, "noplaylist": True, "no_warnings": True}


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/terms")
def terms():
    return send_from_directory("static", "terms.html")


@app.post("/api/info")
def info():
    if rate_limited(request.remote_addr):
        return jsonify(error="بہت زیادہ درخواستیں۔ ایک منٹ بعد دوبارہ کوشش کریں۔"), 429
    url = (request.get_json(silent=True) or {}).get("url", "").strip()
    if not valid_url(url):
        return jsonify(error="یہ لنک سپورٹڈ نہیں ہے۔ یوٹیوب، ٹک ٹاک یا فیس بک کا لنک دیں۔"), 400
    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            data = ydl.extract_info(url, download=False)
    except Exception:
        return jsonify(error="ویڈیو نہیں مل سکی۔ ہو سکتا ہے وہ نجی ہو یا ہٹا دی گئی ہو۔"), 400
    if (data.get("duration") or 0) > MAX_DURATION:
        return jsonify(error="ویڈیو 30 منٹ سے لمبی ہے۔"), 400
    return jsonify(
        title=data.get("title"),
        thumbnail=data.get("thumbnail"),
        duration=data.get("duration"),
        uploader=data.get("uploader"),
    )


@app.get("/api/download")
def download():
    if rate_limited(request.remote_addr):
        return jsonify(error="بہت زیادہ درخواستیں۔"), 429
    url = request.args.get("url", "").strip()
    kind = request.args.get("kind", "video")
    if not valid_url(url):
        return jsonify(error="غلط لنک"), 400

    tmp = tempfile.mkdtemp(prefix="vd_")
    opts = base_opts()
    opts["outtmpl"] = os.path.join(tmp, "%(id)s.%(ext)s")
    opts["max_filesize"] = 300 * 1024 * 1024
    opts["format"] = (
        "bestaudio[ext=m4a]/bestaudio" if kind == "audio" else "b[ext=mp4]/b"
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(data)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        return jsonify(error="ڈاؤن لوڈ ناکام رہا۔"), 400

    @after_this_request
    def cleanup(resp):
        shutil.rmtree(tmp, ignore_errors=True)
        return resp

    safe = re.sub(r'[\\/:*?"<>|]', "", data.get("title") or "video")[:80]
    ext = os.path.splitext(path)[1]
    return send_file(path, as_attachment=True, download_name=f"{safe}{ext}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
