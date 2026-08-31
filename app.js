let mode = "video";
let pollTimer = null;
const qualitySelect = document.getElementById("quality");
const subsCheckbox = document.getElementById("subs");
const subsRow = document.getElementById("subsRow");

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
  if (info.default_quality) {
    qualitySelect.value = info.default_quality;
  }
  if (!info.ffmpeg_available) {
    const w = document.getElementById("ffmpegWarn");
    w.style.display = "block";
    w.innerHTML = "ffmpeg isn't installed — video quality will be limited and MP3 downloads won't work.<br>" +
      "Install it in Terminal with <code>brew install ffmpeg</code> (get Homebrew first at " +
      '<a href="https://brew.sh" target="_blank" style="color:inherit;">brew.sh</a> if needed) — ' +
      "no manual file placement needed, it goes on your PATH automatically.";
  }
}).catch(() => {});

document.getElementById("openFolder").addEventListener("click", () => {
  fetch("/api/open-folder");
});

document.getElementById("goBtn").addEventListener("click", startDownload);
document.getElementById("url").addEventListener("keydown", e => {
  if (e.key === "Enter") startDownload();
});

function startDownload() {
  const url = document.getElementById("url").value.trim();
  if (!url) return;
  const btn = document.getElementById("goBtn");
  btn.disabled = true;
  btn.textContent = "Working…";
  document.getElementById("statusBlock").style.display = "block";
  setState("starting", 0, [], null, null, null);

  fetch("/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url, mode,
      quality: qualitySelect.value,
      sub_lang: (mode === "video" && subsCheckbox.checked) ? "en" : null
    })
  }).then(r => r.json()).then(data => {
    if (data.error) {
      setState("error", 0, [data.error], data.error);
      resetBtn();
      return;
    }
    poll(data.id);
  }).catch(err => {
    setState("error", 0, [String(err)],
      "Couldn't reach the downloader server. Try quitting and relaunching " +
      "'Start YouTube Downloader.command', then reload this page.");
    resetBtn();
  });
}

let pollFailCount = 0;
let stalledSince = null;

function poll(id) {
  clearInterval(pollTimer);
  pollFailCount = 0;
  stalledSince = Date.now();
  pollTimer = setInterval(() => {
    fetch("/api/status?id=" + id).then(r => r.json()).then(job => {
      pollFailCount = 0;
      if (job.status !== "starting") stalledSince = Date.now();
      let log = job.log || [];
      if (job.status === "starting" && Date.now() - stalledSince > 15000) {
        log = log.concat(["(Still starting after 15s — the URL may be invalid, " +
          "or the server may need a restart. Feel free to try again or relaunch " +
          "'Start YouTube Downloader.command'.)"]);
      }
      setState(job.status, job.percent || 0, log, job.error, job.filename, job.size);
      if (job.status === "done" || job.status === "error") {
        clearInterval(pollTimer);
        resetBtn();
      }
    }).catch(() => {
      pollFailCount += 1;
      if (pollFailCount >= 3) {
        clearInterval(pollTimer);
        setState("error", 0, ["Lost connection to the downloader server."],
          "Lost connection to the server. Try relaunching 'Start YouTube Downloader.command'.");
        resetBtn();
      }
    });
  }, 800);
}

function setState(status, percent, log, error, filename, size) {
  document.getElementById("progressInner").style.width = percent + "%";
  document.getElementById("percentText").textContent = Math.round(percent) + "%";
  const stateEl = document.getElementById("stateText");
  stateEl.classList.remove("done", "error");
  if (status === "done") {
    stateEl.textContent = "Done" + (filename ? ": " + filename : "");
    stateEl.classList.add("done");
  } else if (status === "error") {
    stateEl.textContent = "Error: " + (error || "something went wrong");
    stateEl.classList.add("error");
  } else if (status === "running") {
    stateEl.textContent = "Downloading…";
  } else {
    stateEl.textContent = "Starting…";
  }
  document.getElementById("logBox").textContent = (log || []).join("\n");
  const sizeEl = document.getElementById("sizeText");
  sizeEl.textContent = size ? "Total size: " + size : "";
}

function resetBtn() {
  const btn = document.getElementById("goBtn");
  btn.disabled = false;
  btn.textContent = "Download";
}
