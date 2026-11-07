const $ = (id) => document.getElementById(id);
const els = {
  dot: $("status-dot"), banner: $("banner"), tabTitle: $("tab-title"), url: $("url"),
  video: $("btn-video"), audio: $("btn-audio"), hint: $("url-hint"), jobs: $("jobs"), empty: $("empty"),
  clear: $("clear"), folder: $("folder"), openFolder: $("open-folder"), changeFolder: $("change-folder"),
  versions: $("versions"), update: $("update"), updateResult: $("update-result"),
};

let state = { helper: {}, jobs: {} };
let tab = null;

const ask = (cmd, extra = {}) => chrome.runtime.sendMessage({ cmd, ...extra });

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) if (child != null) node.append(child);
  return node;
}

// ---------------------------------------------------------------- render

function render() {
  renderHelper();
  renderForm();
  renderJobs();
}

function renderHelper() {
  const h = state.helper || {};
  const s = h.state || "unknown";
  els.dot.className = "dot " + ({ ready: "ok", idle: "ok", missing: "bad", error: "bad" }[s] || "busy");
  els.dot.title = { ready: "Helper connected", idle: "Helper ready", missing: "Helper not installed",
                    error: "Helper problem" }[s] || "Working…";

  els.banner.replaceChildren();
  els.banner.className = "banner";
  let show = true;
  if (s === "missing") {
    els.banner.append(
      el("h3", {}, "Install the helper app (one time)"),
      el("p", {}, "The extension needs its small Mac app to save files."),
      el("ol", {},
        el("li", {}, "Download “YT Downloader for Mac” and unzip it."),
        el("li", {}, "Drag YT Downloader into Applications and open it."),
        el("li", {}, "Come back here.")),
      el("div", { class: "buttons" },
        el("button", { class: "primary", onclick: () => chrome.tabs.create({ url: RELEASES_URL }) }, "Download the helper"),
        el("button", { onclick: () => ask("status") }, "Check again")));
  } else if (s === "error") {
    els.banner.classList.add("bad");
    els.banner.append(
      el("h3", {}, "The helper app had a problem"),
      el("p", {}, h.message || "It stopped unexpectedly."),
      el("div", { class: "buttons" }, el("button", { onclick: () => ask("status") }, "Try again")));
  } else if (s === "needs-setup") {
    els.banner.append(
      el("h3", {}, "Some components are missing"),
      el("p", {}, `${(h.missing || []).join(", ")}. ${h.message || "They download automatically, or install them now."}`),
      el("div", { class: "buttons" }, el("button", { class: "primary", onclick: () => ask("setup") }, "Install now")));
  } else if (s === "installing") {
    const i = h.install || {};
    const pct = i.total ? Math.round((i.received / i.total) * 100) : null;
    const bar = el("div", { class: pct == null ? "bar indeterminate" : "bar" }, el("div"));
    if (pct != null) bar.firstChild.style.width = `${pct}%`;
    els.banner.append(
      el("h3", {}, "Installing components…"),
      el("p", {}, i.tool ? `${i.tool}${pct != null ? ` · ${pct}%` : ""}` : "Starting…"), bar);
  } else if (s === "updating") {
    els.banner.append(el("h3", {}, "Updating yt-dlp…"), el("div", { class: "bar indeterminate" }, el("div")));
  } else if (s === "connecting" && !h.version) {
    els.banner.append(el("p", {}, "Connecting to the helper app…"));
  } else {
    show = false;
  }
  els.banner.hidden = !show;

  els.folder.textContent = h.downloadDir ? h.downloadDir.replace(/^\/Users\/[^/]+/, "~") : "—";
  els.folder.title = h.downloadDir || "";
  const t = h.tools || {};
  els.versions.textContent = t["yt-dlp"] ? `yt-dlp ${t["yt-dlp"]}` : (h.version ? "yt-dlp not installed" : "");
  els.versions.title = Object.entries(t).map(([k, v]) => `${k} ${v || "missing"}`).join("\n");
  els.update.disabled = s === "updating" || s === "installing" || s === "missing";
  els.openFolder.disabled = els.changeFolder.disabled = s === "missing";
  const r = h.updateResult;
  els.updateResult.hidden = !r || Date.now() - r.at > 10 * 60 * 1000;
  if (r) els.updateResult.textContent = (r.ok ? "" : "Update failed: ") + (r.text || "");
}

function renderForm() {
  const url = els.url.value.trim();
  const valid = isYouTubeVideoUrl(url);
  const sameAsTab = tab && url === tab.url;
  els.tabTitle.hidden = !(sameAsTab && valid);
  els.tabTitle.textContent = sameAsTab ? cleanTabTitle(tab.title) : "";
  const blocked = state.helper?.state === "missing";
  els.video.disabled = els.audio.disabled = !valid || blocked;
  if (url && !valid) {
    els.hint.hidden = false;
    els.hint.textContent = "That isn't a single YouTube video link.";
  } else if (!url) {
    els.hint.hidden = false;
    els.hint.textContent = "Open a YouTube video, or paste its link here.";
  } else {
    els.hint.hidden = true;
  }
}

function statusLine(job) {
  switch (job.status) {
    case "sending": return "Sending to helper…";
    case "queued": return "Waiting";
    case "preparing": return job.phase || "Installing components…";
    case "processing": return job.phase || "Converting…";
    case "running": {
      const bits = [job.phase || "Downloading"];
      if (job.percent != null) bits.push(`${Math.floor(job.percent)}%`);
      if (job.speed) bits.push(`${formatBytes(job.speed)}/s`);
      if (job.eta != null) bits.push(`${formatEta(job.eta)} left`);
      return bits.join(" · ");
    }
    case "done": return "Saved";
    case "cancelled": return "Cancelled";
    case "error": return job.error || "Failed";
    default: return job.status;
  }
}

function renderJobs() {
  const list = Object.values(state.jobs || {}).sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));
  els.empty.hidden = list.length > 0;
  els.clear.hidden = !list.some((j) => !ACTIVE.has(j.status));
  els.jobs.replaceChildren(...list.map(renderJob));
}

function renderJob(job) {
  const active = ACTIVE.has(job.status);
  const top = el("div", { class: "job-top" },
    el("span", { class: "badge" }, job.mode === "audio" ? "MP3" : "MP4"),
    el("span", { class: "job-title", title: job.title || job.url }, job.title || job.url),
    active ? el("button", { class: "icon-btn", title: "Cancel", onclick: () => ask("cancel", { id: job.id }) }, "✕") : null);

  let bar = null;
  if (active) {
    const indeterminate = job.percent == null || job.status !== "running";
    bar = el("div", { class: indeterminate ? "bar indeterminate" : "bar" }, el("div"));
    if (!indeterminate) bar.firstChild.style.width = `${job.percent}%`;
  }
  const meta = el("div", { class: "job-meta" }, el("span", { class: "grow", title: statusLine(job) }, statusLine(job)));
  if (job.status === "done" && job.file) {
    meta.append(el("button", { class: "link", onclick: () => ask("reveal", { path: job.file }) }, "Show in Finder"));
  }
  if (job.status === "error" || job.status === "cancelled") {
    meta.append(el("button", { class: "link", onclick: () => ask("retry", { id: job.id }) }, "Retry"));
  }
  return el("li", { class: `job ${job.status}` }, top, bar, meta);
}

// ---------------------------------------------------------------- actions

async function download(mode) {
  const url = els.url.value.trim();
  if (!isYouTubeVideoUrl(url)) return;
  const title = tab && url === tab.url ? cleanTabTitle(tab.title) : "";
  const button = mode === "audio" ? els.audio : els.video;
  button.disabled = true;
  const result = await ask("download", { url, mode, title });
  if (result?.error) {
    els.hint.hidden = false;
    els.hint.textContent = result.error;
  }
  setTimeout(renderForm, 600);
}

async function init() {
  try {
    [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  } catch { tab = null; }
  if (tab?.url && isYouTubeVideoUrl(tab.url)) els.url.value = tab.url;

  els.url.addEventListener("input", renderForm);
  els.url.addEventListener("keydown", (e) => { if (e.key === "Enter" && !els.video.disabled) download("video"); });
  els.video.addEventListener("click", () => download("video"));
  els.audio.addEventListener("click", () => download("audio"));
  els.clear.addEventListener("click", () => ask("clearFinished"));
  els.openFolder.addEventListener("click", () => ask("openFolder"));
  els.changeFolder.addEventListener("click", () => ask("chooseFolder"));
  els.update.addEventListener("click", () => ask("update"));

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    if (changes.jobs) state.jobs = changes.jobs.newValue || {};
    if (changes.helper) state.helper = changes.helper.newValue || {};
    render();
  });

  render();
  const status = await ask("status");
  if (status && !status.error) state = status;
  render();
}

init();
