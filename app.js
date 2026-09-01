let mode = "video";

const qualitySelect = document.getElementById("quality");
const subMode = document.getElementById("subMode");
const subLang = document.getElementById("subLang");
const subSize = document.getElementById("subSize");
const subOptions = document.getElementById("subOptions");
const sizeField = document.getElementById("sizeField");
const subNote = document.getElementById("subNote");
let canBurn = true;

const picker = document.getElementById("picker");
const pickerTitle = document.getElementById("pickerTitle");
const pickerList = document.getElementById("pickerList");
const probeBtn = document.getElementById("probeBtn");
const probeNote = document.getElementById("probeNote");
const goBtn = document.getElementById("goBtn");
let items = [];
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
    subMode.disabled = (mode === "audio");
    updateSubtitleOptions();
  });
});

const NOTES = {
  none: "",
  sidecar: "Saved as a .srt beside the video. Auto-generated captions are " +
           "repaired automatically; the original is kept as .raw.srt.",
  soft: "Embedded as a track your player can switch on or off. Instant — " +
        "the video is not re-encoded.",
  burn: "Painted permanently into the picture, visible in any player. " +
        "This re-encodes the video, so it takes a few minutes per item."
};

function updateSubtitleOptions() {
  const chosen = mode === "audio" ? "none" : subMode.value;
  subOptions.style.display = chosen === "none" ? "none" : "flex";
  sizeField.style.display = chosen === "burn" ? "block" : "none";
  subNote.textContent = mode === "audio" ? "" : (NOTES[chosen] || "");
  subNote.classList.remove("warn-text");

  if (!canBurn) {
    const burnOption = subMode.querySelector('option[value="burn"]');
    burnOption.disabled = true;
    burnOption.textContent = "Burn permanently into the picture (needs ffmpeg-full)";
    if (chosen === "burn") subMode.value = "none";
  }
}

subMode.addEventListener("change", () => { updateSubtitleOptions(); updateButton(); });

fetch("/api/info").then(r => r.json()).then(info => {
  document.getElementById("saveLoc").textContent = "Saving to " + info.output_dir;
  if (info.default_quality) qualitySelect.value = info.default_quality;
  canBurn = info.can_burn;
  updateSubtitleOptions();
  if (info.ffmpeg_available && !info.can_burn) {
    subNote.classList.add("warn-text");
    subNote.innerHTML = "Burning is unavailable: this ffmpeg was built without " +
      "libass. Install <code>brew install ffmpeg-full</code> to enable it. " +
      "Everything else works.";
  }
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
goBtn.addEventListener("click", addToQueue);
document.getElementById("selectAll").addEventListener("click", () => setAll(true));
document.getElementById("selectNone").addEventListener("click", () => setAll(false));
document.getElementById("pickerClose").addEventListener("click", closePicker);
probeBtn.addEventListener("click", probeLanguages);
document.getElementById("url").addEventListener("keydown", e => {
  if (e.key === "Enter") addToQueue();
});
stopBtn.addEventListener("click", () => {
  fetch("/api/stop", { method: "POST" }).then(refresh);
});

function options() {
  return {
    mode,
    quality: qualitySelect.value,
    sub_mode: mode === "video" ? subMode.value : "none",
    sub_lang: (mode === "video" && subMode.value !== "none") ? subLang.value : null,
    sub_size: subSize.value
  };
}

function showError(message) {
  subNote.classList.add("warn-text");
  subNote.textContent = message;
}

function formatDuration(seconds) {
  if (!seconds) return "";
  const m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
  return m >= 60
    ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

function selected() {
  return [...pickerList.querySelectorAll("input:checked")]
    .map(box => items[Number(box.dataset.index)]);
}

function setAll(checked) {
  pickerList.querySelectorAll("input").forEach(box => { box.checked = checked; });
  updateButton();
}

function updateButton() {
  const count = selected().length;
  goBtn.textContent = picker.style.display === "none"
    ? "Add to queue"
    : (count ? `Add ${count} to queue` : "Nothing selected");
  goBtn.disabled = picker.style.display !== "none" && count === 0;
  probeBtn.disabled = count === 0 || subMode.value === "none";
  probeBtn.style.display = subMode.value === "none" ? "none" : "block";
}

function closePicker() {
  picker.style.display = "none";
  items = [];
  probeNote.textContent = "";
  updateButton();
}

function showPicker(result) {
  items = result.items;
  pickerTitle.textContent = `${result.title} — ${items.length} videos`;
  pickerList.innerHTML = "";

  items.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "picker-row";

    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = true;
    box.dataset.index = index;
    box.id = "pick" + index;
    box.addEventListener("change", updateButton);

    const label = document.createElement("label");
    label.htmlFor = box.id;
    label.textContent = item.title;

    const duration = document.createElement("span");
    duration.className = "dur";
    duration.textContent = formatDuration(item.duration);

    row.append(box, label, duration);
    pickerList.appendChild(row);
  });

  picker.style.display = "block";
  updateButton();
}

function addToQueue() {
  if (picker.style.display !== "none") return queueSelected();

  const urlInput = document.getElementById("url");
  const url = urlInput.value.trim();
  if (!url) return;

  goBtn.disabled = true;
  goBtn.textContent = "Looking up…";
  subNote.classList.remove("warn-text");

  fetch("/api/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url })
  }).then(r => r.json()).then(result => {
    goBtn.disabled = false;
    goBtn.textContent = "Add to queue";
    if (result.error) return showError(result.error);

    if (result.kind === "playlist" && result.items.length > 1) {
      showPicker(result);
      return;
    }
    queue([{ url, title: result.items.length ? result.items[0].title : null }]);
  }).catch(() => {
    goBtn.disabled = false;
    goBtn.textContent = "Add to queue";
    showError("Could not reach the downloader.");
  });
}

function queueSelected() {
  queue(selected().map(item => ({ url: item.url, title: item.title })));
}

function queue(chosen) {
  if (!chosen.length) return;
  fetch("/api/enqueue", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...options(), items: chosen })
  }).then(r => r.json()).then(data => {
    if (data.error) return showError(data.error);
    document.getElementById("url").value = "";
    closePicker();
    refresh();
  }).catch(() => showError("Could not reach the downloader."));
}

function probeLanguages() {
  const chosen = selected();
  if (!chosen.length) return;
  probeBtn.disabled = true;
  probeNote.textContent =
    `Checking ${chosen.length} video${chosen.length > 1 ? "s" : ""}… ` +
    "this needs one lookup per video, so it can take a few seconds each.";

  fetch("/api/probe-subs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls: chosen.map(item => item.url) })
  }).then(r => r.json()).then(data => {
    probeBtn.disabled = false;
    const languages = data.languages || [];
    if (!languages.length) {
      probeNote.textContent = "No subtitles found on the selected videos.";
      return;
    }
    const KINDS = { captions: "captions", original: "auto-generated",
                    translated: "machine-translated" };
    subLang.innerHTML = "";
    languages.forEach(track => {
      const option = document.createElement("option");
      option.value = track.code;
      const partial = track.count < track.total ? ` — ${track.count} of ${track.total}` : "";
      option.textContent = `${track.name} (${KINDS[track.kind]})${partial}`;
      subLang.appendChild(option);
    });
    probeNote.textContent =
      "Machine-translated tracks are translations of the automatic transcript, " +
      "so they carry both transcription and translation errors.";
  }).catch(() => {
    probeBtn.disabled = false;
    probeNote.textContent = "Could not check languages.";
  });
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
    const STAGES = { downloading: "Downloading", burning: "Burning subtitles",
                     embedding: "Embedding subtitles" };
    return (STAGES[job.stage] || "Working") + " " + Math.round(job.percent) + "%";
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
    if (job.subtitle_stats && job.subtitle_stats.rolling) {
      meta.push(`Captions repaired: ${job.subtitle_stats.cues_in} → ${job.subtitle_stats.cues_out} cues`);
    }
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
