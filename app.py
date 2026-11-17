"""FastAPI backend for the YouTube Web Downloader powered by yt-dlp and ffmpeg."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

FROZEN = getattr(sys, "frozen", False)
BASE_DIR = Path(__file__).resolve().parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
STATIC_DIR = BUNDLE_DIR / "static"
DEFAULT_DOWNLOAD_DIR = (
    Path.home() / "Downloads" / "YouTubeDownloader" if FROZEN else BASE_DIR / "downloads"
)
DEFAULT_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def find_ffmpeg() -> Optional[str]:
    """Locate the ffmpeg binary from PATH, Homebrew, or bundled imageio-ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and os.path.isfile(bundled):
            return bundled
    except Exception:
        pass
    return None


class DownloadCancelled(Exception):
    """Raised inside a yt-dlp progress hook when a user cancels the job."""


class InspectRequest(BaseModel):
    """Payload for inspecting a YouTube video or playlist URL."""

    url: str = Field(..., min_length=1)
    cookies_from_browser: str = "none"


class DownloadRequest(BaseModel):
    """Payload for starting a new download job."""

    url: str = Field(..., min_length=1)
    mode: str = "video"  # "video" | "audio"
    quality: str = "best"  # "best" | "2160" | "1440" | "1080" | "720" | "480" | "360"
    codec_preference: str = "compat"  # "compat" (MP4 H.264+AAC) | "quality" (VP9/AV1)
    audio_format: str = "mp3"  # "mp3" | "m4a" | "opus" | "flac"
    audio_quality: str = "192"  # "320" | "192" | "128"
    download_subtitles: bool = False
    subtitle_langs: str = "zh-TW,zh-Hant,en"
    include_auto_subs: bool = True
    embed_subs: bool = False
    playlist_mode: str = "single"  # "single" | "playlist"
    playlist_items: str = ""
    cookies_from_browser: str = "none"
    output_dir: str = ""


@dataclass
class DownloadJob:
    """Represents a single download task and its live progress state."""

    job_id: str
    url: str
    title: str = "準備中..."
    status: str = "queued"  # queued | downloading | postprocessing | completed | error | cancelled
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    playlist_index: Optional[int] = None
    playlist_count: Optional[int] = None
    output_dir: str = str(DEFAULT_DOWNLOAD_DIR)
    output_files: list[str] = field(default_factory=list)
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    cancel_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize job fields for API and SSE responses."""
        data = asdict(self)
        data.pop("cancel_requested", None)
        return data


class JobManager:
    """Thread-safe manager for background yt-dlp download jobs and SSE subscribers."""

    def __init__(self, max_workers: int = 2) -> None:
        self._jobs: dict[str, DownloadJob] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}

    def create_job(self, req: DownloadRequest) -> DownloadJob:
        """Register a new job and submit it to the worker pool."""
        job_id = uuid.uuid4().hex[:10]
        target_dir = resolve_output_dir(req.output_dir)
        job = DownloadJob(job_id=job_id, url=req.url.strip(), output_dir=str(target_dir))
        with self._lock:
            self._jobs[job_id] = job
        self._executor.submit(self._run_download, job_id, req, target_dir)
        return job

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return all jobs sorted newest-first."""
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [j.to_dict() for j in jobs]

    def get_job(self, job_id: str) -> Optional[DownloadJob]:
        """Retrieve a job by ID."""
        with self._lock:
            return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Mark an active job as cancelled."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            job.cancel_requested = True
            if job.status == "queued":
                job.status = "cancelled"
        self._notify(job_id)
        return True

    def subscribe(self, job_id: str, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        """Subscribe an asyncio queue to job state updates."""
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subscribers.setdefault(job_id, []).append((loop, queue))
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        """Remove an SSE subscriber queue."""
        with self._lock:
            subs = self._subscribers.get(job_id, [])
            self._subscribers[job_id] = [(lp, q) for lp, q in subs if q is not queue]

    def _notify(self, job_id: str) -> None:
        """Push the current job snapshot to all active SSE subscribers."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            payload = job.to_dict()
            subs = list(self._subscribers.get(job_id, []))
        for loop, queue in subs:
            if not loop.is_closed():
                loop.call_soon_threadsafe(queue.put_nowait, payload)

    def _update_job(self, job_id: str, **fields: Any) -> None:
        """Update job fields under lock and notify subscribers."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for key, value in fields.items():
                setattr(job, key, value)
        self._notify(job_id)

    def _run_download(self, job_id: str, req: DownloadRequest, target_dir: Path) -> None:
        """Execute yt-dlp download in a worker thread."""
        job = self.get_job(job_id)
        if not job or job.cancel_requested:
            self._update_job(job_id, status="cancelled")
            return

        recorded_files: list[str] = []

        def progress_hook(d: dict[str, Any]) -> None:
            current = self.get_job(job_id)
            if current and current.cancel_requested:
                raise DownloadCancelled("使用者已取消下載")

            info = d.get("info_dict") or {}
            title = info.get("title") or current.title if current else "下載中..."
            p_idx = info.get("playlist_index")
            p_cnt = info.get("n_entries") or info.get("playlist_count")

            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                percent = round((downloaded / total) * 100, 1) if total > 0 else 0.0
                speed_val = d.get("speed")
                speed_str = format_speed(speed_val)
                eta_str = format_eta(d.get("eta"))
                self._update_job(
                    job_id,
                    status="downloading",
                    title=title,
                    percent=min(percent, 99.9),
                    speed=speed_str,
                    eta=eta_str,
                    playlist_index=p_idx,
                    playlist_count=p_cnt,
                )
            elif status == "finished":
                filename = d.get("filename")
                if filename and filename not in recorded_files:
                    recorded_files.append(filename)
                self._update_job(
                    job_id,
                    status="postprocessing",
                    title=title,
                    percent=99.9,
                    speed="",
                    eta="處理合併/轉檔中...",
                    playlist_index=p_idx,
                    playlist_count=p_cnt,
                )

        def postprocessor_hook(d: dict[str, Any]) -> None:
            if d.get("status") == "finished":
                filepath = (d.get("info_dict") or {}).get("filepath")
                if filepath and filepath not in recorded_files:
                    recorded_files.append(filepath)

        try:
            self._update_job(job_id, status="downloading", percent=0.0)
            ydl_opts = build_ydl_options(req, target_dir, progress_hook, postprocessor_hook)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(req.url.strip(), download=True)
                final_files = collect_final_files(ydl, info, recorded_files)
                title = (info or {}).get("title") or job.title
                self._update_job(
                    job_id,
                    status="completed",
                    title=title,
                    percent=100.0,
                    speed="",
                    eta="完成",
                    output_files=final_files,
                )
        except DownloadCancelled:
            self._update_job(job_id, status="cancelled", speed="", eta="已取消")
        except Exception as exc:
            self._update_job(
                job_id,
                status="error",
                speed="",
                eta="",
                error=str(exc),
            )


def resolve_output_dir(raw_dir: str) -> Path:
    """Resolve and ensure the target download directory exists."""
    cleaned = raw_dir.strip()
    if not cleaned:
        DEFAULT_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        return DEFAULT_DOWNLOAD_DIR
    path = Path(os.path.expanduser(cleaned)).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def format_speed(speed: Optional[float]) -> str:
    """Format download speed in bytes/sec to a human-readable string."""
    if not speed or speed <= 0:
        return ""
    if speed >= 1024 * 1024:
        return f"{speed / (1024 * 1024):.2f} MB/s"
    return f"{speed / 1024:.0f} KB/s"


def format_eta(eta: Optional[int]) -> str:
    """Format remaining seconds into MM:SS."""
    if eta is None or eta < 0:
        return ""
    mins, secs = divmod(int(eta), 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def build_format_selector(req: DownloadRequest) -> tuple[str, Optional[str]]:
    """Build yt-dlp format string and optional merge output format."""
    if req.mode == "audio":
        return "bestaudio/best", None

    height_filter = f"[height<={req.quality}]" if req.quality != "best" else ""

    if req.codec_preference == "compat":
        fmt = (
            f"bestvideo{height_filter}[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            f"bestvideo{height_filter}[ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo{height_filter}+bestaudio/best{height_filter}/best"
        )
        return fmt, "mp4"

    fmt = f"bestvideo{height_filter}+bestaudio/best{height_filter}/best"
    return fmt, None


def build_ydl_options(
    req: DownloadRequest,
    target_dir: Path,
    progress_hook: Any,
    postprocessor_hook: Any,
) -> dict[str, Any]:
    """Construct the yt-dlp options dictionary from a DownloadRequest."""
    fmt, merge_fmt = build_format_selector(req)
    is_playlist = req.playlist_mode == "playlist"

    outtmpl = (
        str(target_dir / "%(playlist_title)s" / "%(playlist_index)02d - %(title)s.%(ext)s")
        if is_playlist
        else str(target_dir / "%(title)s.%(ext)s")
    )

    opts: dict[str, Any] = {
        "format": fmt,
        "outtmpl": outtmpl,
        "noplaylist": not is_playlist,
        "ignoreerrors": is_playlist,
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
        "quiet": True,
        "no_warnings": True,
    }

    ffmpeg_path = find_ffmpeg()
    if ffmpeg_path:
        opts["ffmpeg_location"] = ffmpeg_path

    if merge_fmt:
        opts["merge_output_format"] = merge_fmt

    postprocessors: list[dict[str, Any]] = []
    if req.mode == "audio":
        postprocessors.append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": req.audio_format,
                "preferredquality": req.audio_quality,
            }
        )

    if req.download_subtitles:
        langs = [lang.strip() for lang in req.subtitle_langs.split(",") if lang.strip()]
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = req.include_auto_subs
        opts["subtitleslangs"] = langs or ["zh-TW", "en"]
        opts["subtitlesformat"] = "srt/vtt/best"
        if req.embed_subs and req.mode == "video":
            postprocessors.append({"key": "FFmpegEmbedSubtitle"})

    if postprocessors:
        opts["postprocessors"] = postprocessors

    if is_playlist and req.playlist_items.strip():
        opts["playlist_items"] = req.playlist_items.strip()

    if req.cookies_from_browser != "none":
        opts["cookiesfrombrowser"] = (req.cookies_from_browser,)

    return opts


def collect_final_files(
    ydl: yt_dlp.YoutubeDL,
    info: Optional[dict[str, Any]],
    recorded: list[str],
) -> list[str]:
    """Collect existing output file paths after download and postprocessing."""
    candidates: list[str] = []
    if info:
        entries = info.get("entries") if "entries" in info else [info]
        for entry in entries or []:
            if not entry:
                continue
            requested = entry.get("requested_downloads") or []
            for item in requested:
                fp = item.get("filepath")
                if fp:
                    candidates.append(fp)
            prepared = ydl.prepare_filename(entry)
            if prepared:
                candidates.append(prepared)

    for fp in reversed(recorded):
        if fp not in candidates:
            candidates.append(fp)

    existing: list[str] = []
    for path_str in candidates:
        if os.path.isfile(path_str) and path_str not in existing:
            existing.append(path_str)
    return existing


app = FastAPI(title="YouTube Web Downloader", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
job_manager = JobManager(max_workers=2)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the single-page Web UI."""
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/health")
async def health() -> dict[str, Any]:
    """Return environment status including ffmpeg availability and default download dir."""
    ffmpeg_path = find_ffmpeg()
    return {
        "ok": True,
        "ffmpeg_available": ffmpeg_path is not None,
        "ffmpeg_path": ffmpeg_path,
        "default_output_dir": str(DEFAULT_DOWNLOAD_DIR),
        "yt_dlp_version": yt_dlp.version.__version__,
    }


@app.post("/api/inspect")
async def inspect_url(req: InspectRequest) -> dict[str, Any]:
    """Inspect a YouTube video or playlist URL without downloading."""
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
    }
    if req.cookies_from_browser != "none":
        opts["cookiesfrombrowser"] = (req.cookies_from_browser,)

    def _extract() -> dict[str, Any]:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(req.url.strip(), download=False)
        if not info:
            raise ValueError("無法解析此網址")

        is_playlist = info.get("_type") == "playlist" or "entries" in info
        if is_playlist:
            raw_entries = [e for e in (info.get("entries") or []) if e]
            preview_entries = [
                {
                    "index": idx + 1,
                    "title": e.get("title") or f"影片 {idx + 1}",
                    "duration": format_eta(e.get("duration")),
                    "url": e.get("url") or "",
                }
                for idx, e in enumerate(raw_entries[:50])
            ]
            return {
                "is_playlist": True,
                "title": info.get("title") or "播放清單",
                "uploader": info.get("uploader") or info.get("channel") or "",
                "thumbnail": (info.get("thumbnails") or [{}])[-1].get("url", ""),
                "entry_count": len(raw_entries),
                "entries": preview_entries,
                "resolutions": [2160, 1440, 1080, 720, 480, 360],
                "subtitles": [],
            }

        heights = sorted(
            {
                int(f["height"])
                for f in (info.get("formats") or [])
                if f.get("height") and f.get("vcodec") != "none"
            },
            reverse=True,
        )
        manual_subs = sorted((info.get("subtitles") or {}).keys())
        return {
            "is_playlist": False,
            "title": info.get("title") or "未知標題",
            "uploader": info.get("uploader") or info.get("channel") or "",
            "duration": format_eta(info.get("duration")),
            "thumbnail": info.get("thumbnail") or "",
            "resolutions": heights,
            "subtitles": manual_subs[:20],
            "entry_count": 1,
            "entries": [],
        }

    try:
        return await asyncio.to_thread(_extract)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"解析失敗：{exc}") from exc


@app.post("/api/download")
async def start_download(req: DownloadRequest) -> dict[str, Any]:
    """Queue a new download job."""
    job = job_manager.create_job(req)
    return job.to_dict()


@app.get("/api/jobs")
async def list_jobs() -> list[dict[str, Any]]:
    """List all queued, active, and completed jobs."""
    return job_manager.list_jobs()


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, Any]:
    """Cancel a queued or running job."""
    if not job_manager.cancel_job(job_id):
        raise HTTPException(status_code=404, detail="找不到該下載任務")
    return {"ok": True, "job_id": job_id}


@app.get("/api/jobs/{job_id}/file")
async def download_job_file(job_id: str, index: int = 0) -> FileResponse:
    """Serve a completed file directly to the browser."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="找不到該下載任務")
    if index < 0 or index >= len(job.output_files):
        raise HTTPException(status_code=404, detail="找不到對應的輸出檔案")
    file_path = Path(job.output_files[index])
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="檔案已不存在於磁碟中")
    return FileResponse(path=str(file_path), filename=file_path.name)


@app.get("/api/jobs/{job_id}/events")
async def stream_job_events(job_id: str) -> StreamingResponse:
    """Stream real-time download progress for a job using Server-Sent Events."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="找不到該下載任務")

    loop = asyncio.get_running_loop()
    queue = job_manager.subscribe(job_id, loop)

    async def event_generator():
        try:
            initial = job_manager.get_job(job_id)
            if initial:
                yield f"data: {json.dumps(initial.to_dict(), ensure_ascii=False)}\n\n"
                if initial.status in ("completed", "error", "cancelled"):
                    return

            while True:
                payload = await queue.get()
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if payload.get("status") in ("completed", "error", "cancelled"):
                    break
        finally:
            job_manager.unsubscribe(job_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
