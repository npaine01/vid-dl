let mode = "video";

const qualitySelect = document.getElementById("quality");
const subsCheckbox = document.getElementById("subs");
const subsRow = document.getElementById("subsRow");
const queueBlock = document.getElementById("queueBlock");
const queueList = document.getElementById("queueList");
const queueCount = document.getElementById("queueCount");
const stopBtn = document.getElementById("stopBtn");

document.querySelectorAll(".fmt-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".fmt-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    mode = btn.dataset.mode;
    qualitySelect.disabled = (mode === "audio");
    subsCheckbox.disabled = (mode === "audio");
    subsRow.classList.toggle("disabled", mode === "audio");
  });
});

fetch("/api/info").then(r => r.json()).then(info => {
  document.getElementById("saveLoc").textContent = "Saving to " + info.output_dir;
  if (info.default_quality) qualitySelect.value = info.default_quality;
  if (!info.ffmpeg_available) {
    const w = document.getElementById("ffmpegWarn");
    w.style.display = "block";
    w.innerHTML = "No working ffmpeg found — video quality will be limited and MP3 downloads won't work.<br>" +
      "In Terminal: <code>brew install ffmpeg</code> for downloads and MP3, or " +
      "<code>brew install ffmpeg-full</code> to also burn subtitles into video " +
      '(get Homebrew first at <a href="https://brew.sh" target="_blank" style="color:inherit;">brew.sh</a> if needed).';
  }
}).catch(() => {});

document.getElementById("openFolder").addEventListener("click", () => fetch("/api/open-folder"));
document.getElementById("goBtn").addEventListener("click", addToQueue);
document.getElementById("url").addEventListener("keydown", e => {
  if (e.key === "Enter") addToQueue();
});
stopBtn.addEventListener("click", () => {
  fetch("/api/stop", { method: "POST" }).then(refresh);
});

function addToQueue() {
  const urlInput = document.getElementById("url");
  const url = urlInput.value.trim();
  if (!url) return;

  fetch("/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url, mode,
      quality: qualitySelect.value,
      sub_lang: (mode === "video" && subsCheckbox.checked) ? "en" : null
    })
  }).then(r => r.json()).then(data => {
    if (data.error) return;
    urlInput.value = "";
    refresh();
  }).catch(() => {});
}

function cancel(id) {
  fetch("/api/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id })
  }).then(refresh);
}

const LABELS = {
  queued: "Queued", running: "Downloading", done: "Done",
  error: "Failed", cancelled: "Cancelled"
};

function describe(job) {
  if (job.status === "running") {
    return (job.stage === "downloading" ? "Downloading " : "Working ") +
           Math.round(job.percent) + "%";
  }
  return LABELS[job.status] || job.status;
}

function render(report) {
  const jobs = report.jobs || [];
  if (!jobs.length) {
    queueBlock.style.display = "none";
    return;
  }
  queueBlock.style.display = "block";

  const active = jobs.filter(j => j.status === "queued" || j.status === "running").length;
  queueCount.textContent = active ? `· ${active} active` : "· idle";
  stopBtn.disabled = report.pending === 0;
  stopBtn.textContent = report.stopping ? "Stopped" : "Stop after current";

  queueList.innerHTML = "";
  jobs.forEach(job => {
    const row = document.createElement("div");
    row.className = "job " + job.status;

    const stoppable = job.status === "queued" || job.status === "running";
    const name = job.filename || job.title || job.url;

    const head = document.createElement("div");
    head.className = "job-head";
    head.innerHTML =
      `<span class="job-name"></span><span class="job-state">${describe(job)}</span>`;
    head.querySelector(".job-name").textContent = name;

    if (stoppable) {
      const btn = document.createElement("button");
      btn.className = "job-cancel";
      btn.title = job.status === "running" ? "Cancel this download" : "Remove from queue";
      btn.textContent = "×";
      btn.addEventListener("click", () => cancel(job.id));
      head.appendChild(btn);
    }
    row.appendChild(head);

    if (job.status === "running") {
      const bar = document.createElement("div");
      bar.className = "progress-outer";
      bar.innerHTML = `<div class="progress-inner" style="width:${job.percent}%"></div>`;
      row.appendChild(bar);
    }

    const meta = [];
    if (job.size) meta.push("Total size: " + job.size);
    if (job.error) meta.push(`<span class="err">${job.error}</span>`);
    if (meta.length) {
      const line = document.createElement("div");
      line.className = "job-meta";
      line.innerHTML = meta.join(" · ");
      row.appendChild(line);
    }

    if (job.status === "running" && job.log && job.log.length) {
      const log = document.createElement("pre");
      log.className = "job-log";
      log.textContent = job.log.slice(-6).join("\n");
      row.appendChild(log);
    }

    queueList.appendChild(row);
  });
}

function refresh() {
  return fetch("/api/queue").then(r => r.json()).then(render).catch(() => {});
}

refresh();
setInterval(refresh, 800);
