// Talks to the YT Downloader helper app over native messaging and keeps the
// download list in chrome.storage.local, which the popup renders.
importScripts("common.js");

const IDLE_DISCONNECT_MS = 60 * 1000;   // let the helper quit when nothing is happening
const KEEP_JOBS = 30;

let port = null;
let idleTimer = null;
let jobs = {};
let helper = { state: "unknown" };
let loading = null;

// ---------------------------------------------------------------- storage

function load() {
  loading ??= chrome.storage.local.get(["jobs", "helper"]).then((saved) => {
    jobs = saved.jobs || {};
    helper = saved.helper || helper;
    // A fresh service worker has no helper connection, so anything still
    // "active" from before was interrupted (Chrome quit, helper crashed).
    let changed = false;
    for (const job of Object.values(jobs)) {
      if (ACTIVE.has(job.status)) {
        Object.assign(job, { status: "error", error: "Interrupted. Try again.", phase: null });
        changed = true;
      }
    }
    if (helper.state === "connecting" || helper.state === "installing" || helper.state === "updating") {
      helper = { ...helper, state: "idle" };
      changed = true;
    }
    if (changed) save();
    updateBadge();
  });
  return loading;
}

function save() {
  const kept = Object.values(jobs)
    .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
    .slice(0, KEEP_JOBS);
  jobs = Object.fromEntries(kept.map((j) => [j.id, j]));
  return chrome.storage.local.set({ jobs, helper });
}

function setHelper(changes) {
  helper = { ...helper, ...changes };
  save();
}

// ---------------------------------------------------------------- helper connection

function connect() {
  if (port) return port;
  setHelper({ state: "connecting", message: null });
  try {
    port = chrome.runtime.connectNative(HELPER_HOST);
  } catch (e) {
    setHelper({ state: "error", message: String(e) });
    return null;
  }
  port.onMessage.addListener(onHelperMessage);
  port.onDisconnect.addListener(() => {
    const reason = chrome.runtime.lastError?.message || "";
    port = null;
    clearTimeout(idleTimer);
    const hadActive = failActiveJobs(reason ? `Helper stopped: ${reason}` : "Helper stopped.");
    if (/not found/i.test(reason)) {
      setHelper({ state: "missing", message: reason });
    } else if (/forbidden/i.test(reason)) {
      setHelper({ state: "error", message: "The helper app doesn't recognise this extension. Re-run the YT Downloader app." });
    } else if (hadActive || (reason && !/exited/i.test(reason))) {
      setHelper({ state: "error", message: reason || "The helper app stopped." });
    } else {
      setHelper({ state: helper.version ? "idle" : "error", message: reason || null });
    }
  });
  port.postMessage({ type: "hello" });
  touch();
  return port;
}

function send(message) {
  const p = connect();
  if (!p) return false;
  p.postMessage(message);
  touch();
  return true;
}

function touch() {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(maybeDisconnect, IDLE_DISCONNECT_MS);
}

function maybeDisconnect() {
  const busy = Object.values(jobs).some((j) => ACTIVE.has(j.status))
    || ["installing", "updating", "connecting"].includes(helper.state);
  if (busy) return touch();
  if (port) {
    port.disconnect();   // the helper sees end-of-input and quits
    port = null;
  }
  setHelper({ state: "idle" });
}

function failActiveJobs(message) {
  let any = false;
  for (const job of Object.values(jobs)) {
    if (ACTIVE.has(job.status)) {
      Object.assign(job, { status: "error", error: message, phase: null });
      any = true;
    }
  }
  if (any) { save(); updateBadge(); }
  return any;
}

function onHelperMessage(msg) {
  touch();
  switch (msg.type) {
    case "hello":
    case "config":
      setHelper({
        state: msg.missing.length ? "needs-setup" : "ready",
        version: msg.version, tools: msg.tools, missing: msg.missing,
        downloadDir: msg.downloadDir, message: null,
      });
      break;
    case "setup_progress":
      setHelper({ state: "installing", install: { tool: msg.tool, received: msg.received, total: msg.total } });
      break;
    case "setup_done":
      setHelper({
        state: msg.ok ? "ready" : "needs-setup", install: null,
        version: msg.version, tools: msg.tools, missing: msg.missing, downloadDir: msg.downloadDir,
        message: msg.ok ? null : `Couldn't download: ${Object.keys(msg.failures).join(", ")}`,
      });
      break;
    case "update_done":
      setHelper({
        state: "ready",
        tools: msg.version ? { ...(helper.tools || {}), "yt-dlp": msg.version } : helper.tools,
        updateResult: msg.quiet ? helper.updateResult : { ok: msg.ok, text: msg.output, at: Date.now() },
      });
      break;
    case "job":
      onJob(msg.job);
      break;
    case "error":
      setHelper({ message: msg.message });
      break;
  }
}

function onJob(update) {
  const before = jobs[update.id];
  const job = { createdAt: Date.now(), ...before, ...update };
  if (before?.title && update.title === update.url) job.title = before.title;  // keep the nicer tab title
  jobs[update.id] = job;
  save();
  updateBadge();
  if (before?.status !== job.status) {
    if (job.status === "done") {
      notify(`done:${job.id}`, "Download complete", job.title, [{ title: SHOW_IN_FOLDER }]);
    } else if (job.status === "error" && before) {
      notify(`error:${job.id}`, "Download failed", `${job.title}\n${job.error || ""}`);
    }
  }
}

// ---------------------------------------------------------------- actions

function startDownload(url, mode, title) {
  const id = crypto.randomUUID();
  jobs[id] = { id, url, mode, title: title || url, status: "sending", percent: null, createdAt: Date.now() };
  save();
  updateBadge();
  if (!send({ type: "download", id, url, mode, title })) {
    Object.assign(jobs[id], { status: "error", error: "Couldn't reach the helper app." });
    save();
  }
  return id;
}

function updateBadge() {
  const active = Object.values(jobs).filter((j) => ACTIVE.has(j.status));
  let text = "";
  if (active.length === 1 && active[0].percent != null && active[0].status === "running") {
    text = `${Math.floor(active[0].percent)}%`;
  } else if (active.length) {
    text = String(active.length);
  }
  chrome.action.setBadgeBackgroundColor({ color: "#1f7a5c" });
  chrome.action.setBadgeText({ text });
}

function notify(id, title, message, buttons) {
  chrome.notifications.create(id, {
    type: "basic", iconUrl: "icons/icon128.png", title, message: message || "",
    ...(buttons ? { buttons } : {}),
  });
}

function revealJob(notificationId) {
  const [kind, id] = notificationId.split(/:(.*)/s);
  const job = jobs[id];
  if (kind === "done" && job?.file) send({ type: "reveal", path: job.file });
  chrome.notifications.clear(notificationId);
}

chrome.notifications.onClicked.addListener((nid) => load().then(() => revealJob(nid)));
chrome.notifications.onButtonClicked.addListener((nid) => load().then(() => revealJob(nid)));

// ---------------------------------------------------------------- right-click menu

const YT_PAGES = ["*://*.youtube.com/*", "*://youtu.be/*"];
const YT_VIDEO_LINKS = [
  "*://*.youtube.com/watch*", "*://*.youtube.com/shorts/*", "*://*.youtube.com/live/*", "*://youtu.be/*",
];

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    const page = { contexts: ["page", "video"], documentUrlPatterns: YT_PAGES };
    const link = { contexts: ["link"], targetUrlPatterns: YT_VIDEO_LINKS };
    chrome.contextMenus.create({ id: "page:video", title: "Download video (MP4)", ...page });
    chrome.contextMenus.create({ id: "page:audio", title: "Download audio (MP3)", ...page });
    chrome.contextMenus.create({ id: "link:video", title: "Download linked video (MP4)", ...link });
    chrome.contextMenus.create({ id: "link:audio", title: "Download linked audio (MP3)", ...link });
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  await load();
  const [source, mode] = String(info.menuItemId).split(":");
  const url = source === "link" ? info.linkUrl : info.pageUrl;
  if (!isYouTubeVideoUrl(url)) {
    notify(`hint:${Date.now()}`, "Not a video", "Open a YouTube video (or right-click a video link) and try again.");
    return;
  }
  const title = source === "link" ? (info.linkText || "").trim() : cleanTabTitle(tab?.title);
  startDownload(url, mode, title || url);
});

// ---------------------------------------------------------------- popup requests

chrome.runtime.onMessage.addListener((request, _sender, reply) => {
  load().then(() => handle(request)).then(reply, (e) => reply({ error: String(e) }));
  return true;  // reply asynchronously
});

async function handle(req) {
  switch (req.cmd) {
    case "status":
      if (port) send({ type: "hello" }); else connect();   // refresh versions/status
      return { helper, jobs };
    case "download":
      if (!isYouTubeVideoUrl(req.url)) return { error: "Not a YouTube video link." };
      return { id: startDownload(req.url, req.mode === "audio" ? "audio" : "video", req.title) };
    case "cancel":
      send({ type: "cancel", id: req.id });
      return { ok: true };
    case "retry": {
      const job = jobs[req.id];
      if (job) { delete jobs[req.id]; startDownload(job.url, job.mode, job.title); }
      return { ok: true };
    }
    case "reveal":
      send({ type: "reveal", path: req.path });
      return { ok: true };
    case "openFolder":
      send({ type: "open_folder" });
      return { ok: true };
    case "chooseFolder":
      send({ type: "choose_folder" });
      return { ok: true };
    case "update":
      setHelper({ state: "updating", updateResult: null });
      send({ type: "update" });
      return { ok: true };
    case "setup":
      setHelper({ state: "installing", install: null });
      send({ type: "setup" });
      return { ok: true };
    case "clearFinished":
      for (const [id, job] of Object.entries(jobs)) if (!ACTIVE.has(job.status)) delete jobs[id];
      await save();
      return { ok: true };
    default:
      return { error: `Unknown command ${req.cmd}` };
  }
}

load();
