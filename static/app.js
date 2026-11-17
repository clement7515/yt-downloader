const urlInput = document.getElementById("urlInput");
const inspectBtn = document.getElementById("inspectBtn");
const downloadBtn = document.getElementById("downloadBtn");
const inspectError = document.getElementById("inspectError");
const envBadge = document.getElementById("envBadge");

const previewBox = document.getElementById("previewBox");
const previewThumb = document.getElementById("previewThumb");
const previewTypeBadge = document.getElementById("previewTypeBadge");
const previewDuration = document.getElementById("previewDuration");
const previewTitle = document.getElementById("previewTitle");
const previewUploader = document.getElementById("previewUploader");
const previewPlaylistList = document.getElementById("previewPlaylistList");

const modeSelect = document.getElementById("modeSelect");
const qualitySelect = document.getElementById("qualitySelect");
const codecSelect = document.getElementById("codecSelect");
const audioFormatSelect = document.getElementById("audioFormatSelect");
const audioQualitySelect = document.getElementById("audioQualitySelect");
const playlistModeSelect = document.getElementById("playlistModeSelect");
const playlistItemsInput = document.getElementById("playlistItemsInput");
const cookiesSelect = document.getElementById("cookiesSelect");
const outputDirInput = document.getElementById("outputDirInput");

const subtitlesCheck = document.getElementById("subtitlesCheck");
const subtitlesOptions = document.getElementById("subtitlesOptions");
const subtitleLangsInput = document.getElementById("subtitleLangsInput");
const autoSubsCheck = document.getElementById("autoSubsCheck");
const embedSubsCheck = document.getElementById("embedSubsCheck");

const jobsList = document.getElementById("jobsList");
const jobCountBadge = document.getElementById("jobCountBadge");

const jobsMap = new Map();
const eventSources = new Map();

const STATUS_LABELS = {
  queued: { text: "排隊中", cls: "badge-muted" },
  downloading: { text: "下載中", cls: "badge-accent" },
  postprocessing: { text: "合併轉檔中", cls: "badge-warning" },
  completed: { text: "已完成", cls: "badge-success" },
  error: { text: "失敗", cls: "badge-danger" },
  cancelled: { text: "已取消", cls: "badge-muted" },
};

function syncOptionVisibility() {
  const isAudio = modeSelect.value === "audio";
  document.querySelectorAll(".video-only").forEach((el) => el.classList.toggle("hidden", isAudio));
  document.querySelectorAll(".audio-only").forEach((el) => el.classList.toggle("hidden", !isAudio));

  const isPlaylist = playlistModeSelect.value === "playlist";
  document.querySelectorAll(".playlist-only").forEach((el) => el.classList.toggle("hidden", !isPlaylist));

  subtitlesOptions.classList.toggle("hidden", !subtitlesCheck.checked);
}

modeSelect.addEventListener("change", syncOptionVisibility);
playlistModeSelect.addEventListener("change", syncOptionVisibility);
subtitlesCheck.addEventListener("change", syncOptionVisibility);

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    outputDirInput.placeholder = `預設：${data.default_output_dir}`;
    if (data.ffmpeg_available) {
      envBadge.textContent = `ffmpeg 就緒 · yt-dlp ${data.yt_dlp_version}`;
      envBadge.className = "badge badge-success";
    } else {
      envBadge.textContent = "未偵測到 ffmpeg（1080p+ 合併需安裝）";
      envBadge.className = "badge badge-warning";
    }
  } catch {
    envBadge.textContent = "後端連線異常";
    envBadge.className = "badge badge-danger";
  }
}

async function inspectUrl() {
  const url = urlInput.value.trim();
  if (!url) {
    showInspectError("請先貼上 YouTube 網址。");
    return;
  }

  inspectError.classList.add("hidden");
  inspectBtn.disabled = true;
  inspectBtn.textContent = "解析中...";

  try {
    const res = await fetch("/api/inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        cookies_from_browser: cookiesSelect.value,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "解析失敗");
    }
    renderPreview(data);
  } catch (err) {
    previewBox.classList.add("hidden");
    showInspectError(err.message);
  } finally {
    inspectBtn.disabled = false;
    inspectBtn.textContent = "解析預覽";
  }
}

function showInspectError(msg) {
  inspectError.textContent = msg;
  inspectError.classList.remove("hidden");
}

function renderPreview(data) {
  previewBox.classList.remove("hidden");
  previewThumb.src = data.thumbnail || "";
  previewThumb.classList.toggle("hidden", !data.thumbnail);
  previewTitle.textContent = data.title || "未知標題";
  previewUploader.textContent = data.uploader ? `頻道：${data.uploader}` : "";

  if (data.is_playlist) {
    previewTypeBadge.textContent = `播放清單（共 ${data.entry_count} 部）`;
    previewDuration.textContent = "";
    playlistModeSelect.value = "playlist";
    previewPlaylistList.classList.remove("hidden");
    previewPlaylistList.innerHTML = data.entries
      .map((item) => `<div>#${item.index} ${escapeHtml(item.title)} ${item.duration ? `(${item.duration})` : ""}</div>`)
      .join("");
  } else {
    previewTypeBadge.textContent = "單支影片";
    previewDuration.textContent = data.duration ? `片長 ${data.duration}` : "";
    playlistModeSelect.value = "single";
    previewPlaylistList.classList.add("hidden");
    previewPlaylistList.innerHTML = "";
    if (Array.isArray(data.resolutions) && data.resolutions.length > 0) {
      const topRes = data.resolutions.filter((h) => h >= 360);
      if (topRes.length > 0) {
        previewDuration.textContent += ` · 可用畫質最高 ${topRes[0]}p`;
      }
    }
  }
  syncOptionVisibility();
}

async function startDownload() {
  const url = urlInput.value.trim();
  if (!url) {
    showInspectError("請先貼上 YouTube 網址。");
    return;
  }
  inspectError.classList.add("hidden");
  downloadBtn.disabled = true;

  const payload = {
    url,
    mode: modeSelect.value,
    quality: qualitySelect.value,
    codec_preference: codecSelect.value,
    audio_format: audioFormatSelect.value,
    audio_quality: audioQualitySelect.value,
    download_subtitles: subtitlesCheck.checked,
    subtitle_langs: subtitleLangsInput.value,
    include_auto_subs: autoSubsCheck.checked,
    embed_subs: embedSubsCheck.checked,
    playlist_mode: playlistModeSelect.value,
    playlist_items: playlistItemsInput.value,
    cookies_from_browser: cookiesSelect.value,
    output_dir: outputDirInput.value,
  };

  try {
    const res = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const job = await res.json();
    if (!res.ok) {
      throw new Error(job.detail || "建立任務失敗");
    }
    upsertJob(job);
    subscribeJobEvents(job.job_id);
  } catch (err) {
    showInspectError(err.message);
  } finally {
    downloadBtn.disabled = false;
  }
}

function subscribeJobEvents(jobId) {
  if (eventSources.has(jobId)) {
    return;
  }
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  eventSources.set(jobId, source);

  source.onmessage = (event) => {
    const job = JSON.parse(event.data);
    upsertJob(job);
    if (["completed", "error", "cancelled"].includes(job.status)) {
      source.close();
      eventSources.delete(jobId);
    }
  };

  source.onerror = () => {
    source.close();
    eventSources.delete(jobId);
  };
}

async function cancelJob(jobId) {
  await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
}

function upsertJob(job) {
  jobsMap.set(job.job_id, job);
  renderJobs();
}

function renderJobs() {
  const jobs = Array.from(jobsMap.values()).sort((a, b) => b.created_at - a.created_at);
  jobCountBadge.textContent = `${jobs.length} 個任務`;

  if (jobs.length === 0) {
    jobsList.innerHTML = '<p class="empty-state">尚未建立下載任務，貼上網址並點擊「開始下載」。</p>';
    return;
  }

  jobsList.innerHTML = jobs
    .map((job) => {
      const badge = STATUS_LABELS[job.status] || STATUS_LABELS.queued;
      const pct = Math.max(0, Math.min(100, Number(job.percent || 0)));
      const playlistProgress =
        job.playlist_count && job.playlist_index ? ` · 清單第 ${job.playlist_index}/${job.playlist_count} 部` : "";
      const canCancel = ["queued", "downloading", "postprocessing"].includes(job.status);

      const fileLinks =
        job.status === "completed" && Array.isArray(job.output_files)
          ? job.output_files
              .map((fp, idx) => {
                const name = fp.split(/[\\/]/).pop();
                return `<a class="file-link" href="/api/jobs/${job.job_id}/file?index=${idx}">下載：${escapeHtml(name)}</a>`;
              })
              .join("")
          : "";

      const errorBlock = job.error ? `<p class="error-text">${escapeHtml(job.error)}</p>` : "";

      return `
        <div class="job-item">
          <div class="job-top">
            <div class="job-title">${escapeHtml(job.title || job.url)}${playlistProgress}</div>
            <span class="badge ${badge.cls}">${badge.text}</span>
          </div>
          <div class="progress-track">
            <div class="progress-fill ${job.status}" style="width: ${pct}%"></div>
          </div>
          <div class="job-stats">
            <span>進度：${pct.toFixed(1)}%${job.speed ? ` · ${escapeHtml(job.speed)}` : ""}${job.eta ? ` · ${escapeHtml(job.eta)}` : ""}</span>
            <span>儲存目錄：${escapeHtml(job.output_dir)}</span>
          </div>
          ${errorBlock}
          <div class="job-actions">
            ${canCancel ? `<button class="btn btn-secondary btn-small" onclick="cancelJob('${job.job_id}')">取消下載</button>` : ""}
            ${fileLinks}
          </div>
        </div>
      `;
    })
    .join("");
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text ?? "");
  return div.innerHTML;
}

async function loadExistingJobs() {
  try {
    const res = await fetch("/api/jobs");
    const jobs = await res.json();
    jobs.forEach((job) => {
      jobsMap.set(job.job_id, job);
      if (!["completed", "error", "cancelled"].includes(job.status)) {
        subscribeJobEvents(job.job_id);
      }
    });
    renderJobs();
  } catch {
    // Ignore initial load error
  }
}

inspectBtn.addEventListener("click", inspectUrl);
downloadBtn.addEventListener("click", startDownload);
urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    inspectUrl();
  }
});

syncOptionVisibility();
checkHealth();
loadExistingJobs();
