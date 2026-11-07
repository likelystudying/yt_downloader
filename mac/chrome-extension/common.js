// Shared by background.js (importScripts) and popup.js (<script>).

const HELPER_HOST = "com.likelystudying.ytdownloader";
const RELEASES_URL = "https://github.com/likelystudying/yt_downloader/releases";
const ACTIVE = new Set(["sending", "queued", "preparing", "running", "processing"]);
const YT_HOSTS = new Set(["youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"]);

// Same rules as the helper (and the original yt-dlp-gui.py).
function isYouTubeVideoUrl(text) {
  let url;
  try { url = new URL(text); } catch { return false; }
  if (url.protocol !== "https:" && url.protocol !== "http:") return false;
  const host = url.hostname.toLowerCase().replace(/^www\./, "");
  if (!YT_HOSTS.has(host)) return false;
  const parts = url.pathname.split("/").filter(Boolean);
  let id = "";
  if (host === "youtu.be") id = parts[0] || "";
  else if (parts[0] === "watch") id = url.searchParams.get("v") || "";
  else if (["shorts", "embed", "live"].includes(parts[0])) id = parts[1] || "";
  return id.trim().length >= 6;
}

function cleanTabTitle(title) {
  return (title || "").replace(/^\(\d+\)\s*/, "").replace(/\s*-\s*YouTube( Music)?$/, "").trim();
}

function formatBytes(bytes) {
  if (!bytes || bytes < 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
  return `${bytes.toFixed(bytes >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatEta(seconds) {
  if (seconds == null || !isFinite(seconds)) return "";
  seconds = Math.max(0, Math.round(seconds));
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}
