/* WhatsApp Export Viewer — panel frontend */
"use strict";

const $ = (id) => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then((r) => {
  if (!r.ok) throw new Error(r.status + " " + r.statusText);
  return r.json();
});

const state = {
  chats: [],
  activeChat: null,
  meName: null,          // which participant is treated as "you" (right side)
  msgOffset: 0,
  msgTotal: 0,
  msgLimit: 200,
  loadingMsgs: false,
  tab: "chat",
  senderColors: {},
};

const COLORS = ["#e542a3", "#1f7aec", "#e29d00", "#0aa884", "#a44ce5",
  "#e5533c", "#3fa34d", "#c7264a", "#7d5fff", "#0087a8"];

/* ------------------------------------------------------------------ utils */
function esc(s) {
  return (s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function initials(name) {
  const parts = (name || "?").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
function colorFor(name) {
  if (!state.senderColors[name]) {
    const idx = Object.keys(state.senderColors).length % COLORS.length;
    state.senderColors[name] = COLORS[idx];
  }
  return state.senderColors[name];
}
function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function fmtDay(iso) {
  if (!iso) return "Unknown date";
  const d = new Date(iso);
  const today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}
function fmtSize(b) {
  if (!b) return "";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return b.toFixed(b < 10 && i > 0 ? 1 : 0) + " " + u[i];
}
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(t._t); t._t = setTimeout(() => t.classList.add("hidden"), 3000);
}

/* ------------------------------------------------------------------ stats */
async function loadStats() {
  try {
    const s = await api("/api/stats");
    $("statChats").textContent = s.chats;
    $("statMsgs").textContent = s.messages.toLocaleString();
    $("statMedia").textContent = s.media.toLocaleString();
  } catch (e) { /* ignore */ }
}

/* ------------------------------------------------------------- chat list */
async function loadChats(q) {
  const url = "/api/chats" + (q ? "?q=" + encodeURIComponent(q) : "");
  state.chats = await api(url);
  renderChatList();
}
function renderChatList() {
  const list = $("chatList");
  if (!state.chats.length) {
    list.innerHTML = '<div class="empty-hint"><p>No chats yet.</p><p class="muted">Upload a WhatsApp export .zip to get started.</p></div>';
    return;
  }
  list.innerHTML = state.chats.map((c) => `
    <div class="chat-item ${state.activeChat && state.activeChat.id === c.id ? "active" : ""}" data-id="${c.id}">
      <div class="avatar" style="background:${colorFor(c.name)}">${esc(initials(c.name))}</div>
      <div class="info">
        <div class="row1">
          <span class="name">${esc(c.name)}</span>
          <span class="time">${c.last_timestamp ? fmtDay(c.last_timestamp).replace("Today", fmtTime(c.last_timestamp)) : ""}</span>
        </div>
        <div class="row2">
          <span class="preview">${c.is_group ? '<span class="tag-group">Group</span>' : ""}${esc(c.last_message_preview || "")}</span>
          ${c.media_count ? `<span class="badge">${c.media_count} media</span>` : ""}
        </div>
      </div>
    </div>`).join("");
  list.querySelectorAll(".chat-item").forEach((el) =>
    el.addEventListener("click", () => openChat(parseInt(el.dataset.id, 10))));
}

/* --------------------------------------------------------------- open chat */
async function openChat(id) {
  const chat = await api(`/api/chats/${id}`);
  state.activeChat = chat;
  state.msgOffset = 0;
  state.senderColors = {};
  // Decide which participant is "you" (right-hand bubbles).
  state.meName = detectMe(chat);
  $("placeholder").classList.add("hidden");
  $("conversation").classList.remove("hidden");
  document.querySelector(".layout").classList.add("show-chat");

  $("convName").textContent = chat.name;
  const subParts = [];
  if (chat.is_group) subParts.push((chat.participants || []).length + " participants");
  else if (chat.phone_number) subParts.push(chat.phone_number);
  subParts.push(chat.message_count.toLocaleString() + " messages");
  $("convSub").textContent = subParts.join(" · ");
  const av = $("convAvatar");
  av.textContent = initials(chat.name);
  av.style.background = colorFor(chat.name);

  renderChatList();
  switchTab("chat");
  await loadMessages(true);
}

function detectMe(chat) {
  const parts = chat.participants || [];
  // For a 1:1 chat the export is named after the OTHER person, so "me" is the
  // participant whose name differs from the chat name.
  if (!chat.is_group && parts.length === 2) {
    const notNamed = parts.find((p) => p.name !== chat.name);
    return notNamed ? notNamed.name : parts[1].name;
  }
  return null; // group or unknown -> everyone on left with colored names
}

/* --------------------------------------------------------------- messages */
async function loadMessages(reset) {
  if (state.loadingMsgs) return;
  state.loadingMsgs = true;
  const chatId = state.activeChat.id;
  const q = $("msgSearch").value.trim();
  const url = `/api/chats/${chatId}/messages?offset=${state.msgOffset}&limit=${state.msgLimit}` + (q ? "&q=" + encodeURIComponent(q) : "");
  const data = await api(url);
  state.msgTotal = data.total;
  if (reset) $("messages").innerHTML = "";
  renderMessages(data.messages, reset);
  state.msgOffset += data.messages.length;
  state.loadingMsgs = false;
}

function renderMessages(messages, reset) {
  const wrap = $("messages");
  const frag = document.createDocumentFragment();

  // "Load more" button when there are earlier messages not yet shown.
  if (reset && state.msgOffset === 0 && state.msgTotal > messages.length) {
    // handled after render via prepend button
  }

  let lastDay = wrap.dataset.lastDay || "";
  messages.forEach((m) => {
    const day = m.timestamp ? new Date(m.timestamp).toDateString() : "unknown";
    if (day !== lastDay) {
      const sep = document.createElement("div");
      sep.className = "day-sep";
      sep.textContent = fmtDay(m.timestamp);
      frag.appendChild(sep);
      lastDay = day;
    }
    frag.appendChild(buildMessage(m));
  });
  wrap.dataset.lastDay = lastDay;
  wrap.appendChild(frag);

  const mw = $("messagesWrap");
  if (reset) mw.scrollTop = 0; // messages load oldest-first; read top-to-bottom

  updateLoadMore();
}

function updateLoadMore() {
  let btn = $("loadMoreBtn");
  if (state.msgOffset < state.msgTotal) {
    if (!btn) {
      btn = document.createElement("button");
      btn.id = "loadMoreBtn"; btn.className = "load-more";
      btn.addEventListener("click", () => loadMessages(false));
    }
    btn.textContent = `Load ${Math.min(state.msgLimit, state.msgTotal - state.msgOffset).toLocaleString()} more (${(state.msgTotal - state.msgOffset).toLocaleString()} remaining)`;
    $("messages").appendChild(btn); // keep at bottom of the loaded set
  } else if (btn) {
    btn.remove();
  }
}

function buildMessage(m) {
  if (m.type === "system") {
    const el = document.createElement("div");
    el.className = "msg system";
    el.textContent = m.content;
    return el;
  }
  const out = state.meName && m.sender_name === state.meName;
  const el = document.createElement("div");
  el.className = "msg " + (out ? "out" : "in");

  const showSender = !out && (state.activeChat.is_group || !state.meName);
  let html = "";
  if (showSender && m.sender_name) {
    html += `<div class="sender" style="color:${colorFor(m.sender_name)}">${esc(m.sender_name)}${m.sender_number ? ' · ' + esc(m.sender_number) : ""}</div>`;
  }

  if (m.media) {
    html += mediaHtml(m.media);
  } else if (m.type === "media") {
    html += `<div class="missing-media">📎 Media not included in export</div>`;
  }
  if (m.content) {
    html += `<div class="body">${linkify(esc(m.content))}</div>`;
  }
  html += `<span class="meta">${fmtTime(m.timestamp)}${out ? ' <span style="color:var(--tick-blue)">✓✓</span>' : ""}</span>`;
  el.innerHTML = html;

  el.querySelectorAll("[data-lightbox]").forEach((n) =>
    n.addEventListener("click", () => openLightbox(n.dataset.lightbox, n.dataset.mime, n.dataset.dl)));
  return el;
}

function mediaHtml(md) {
  const url = md.url;
  if (md.type === "image") {
    return `<img class="media-img" src="${url}" loading="lazy" data-lightbox="${url}" data-mime="${md.mime}" data-dl="${url}?download=true" alt="${esc(md.filename)}">`;
  }
  if (md.type === "sticker") {
    return `<img class="media-sticker" src="${url}" loading="lazy" alt="sticker">`;
  }
  if (md.type === "video") {
    return `<video class="media-video" src="${url}" controls preload="metadata"></video>`;
  }
  if (md.type === "audio") {
    return `<audio src="${url}" controls preload="none"></audio>`;
  }
  const ext = (md.filename.split(".").pop() || "DOC").toUpperCase().slice(0, 4);
  return `<a class="doc" href="${url}?download=true" target="_blank" rel="noopener">
      <span class="doc-icon">${ext}</span>
      <span><span class="doc-name">${esc(md.filename)}</span><br><span class="muted">${fmtSize(md.size)}</span></span>
    </a>`;
}

function linkify(text) {
  return text.replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener" style="color:#027eb5">$1</a>');
}

/* ----------------------------------------------------------------- tabs */
function switchTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".conv-tabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
  $("messagesWrap").classList.toggle("hidden", tab !== "chat");
  $("galleryWrap").classList.toggle("hidden", tab !== "media");
  $("infoWrap").classList.toggle("hidden", tab !== "info");
  if (tab === "media") loadGallery("all");
  if (tab === "info") renderInfo();
}

/* --------------------------------------------------------------- gallery */
async function loadGallery(type) {
  const chatId = state.activeChat.id;
  const qs = type && type !== "all" ? "?type=" + type : "";
  const data = await api(`/api/chats/${chatId}/media${qs}`);
  renderGalleryFilters(data.counts, type);
  const g = $("gallery");
  if (!data.items.length) {
    g.innerHTML = '<p class="muted" style="grid-column:1/-1;text-align:center;padding:40px">No media in this category.</p>';
    return;
  }
  g.innerHTML = data.items.map((md) => galleryItem(md)).join("");
  g.querySelectorAll("[data-lightbox]").forEach((n) =>
    n.addEventListener("click", () => openLightbox(n.dataset.lightbox, n.dataset.mime, n.dataset.dl)));
}
function renderGalleryFilters(counts, active) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const order = [["all", "All", total], ["image", "Photos", counts.image || 0],
    ["video", "Videos", counts.video || 0], ["audio", "Audio", counts.audio || 0],
    ["sticker", "Stickers", counts.sticker || 0], ["document", "Docs", counts.document || 0]];
  $("galleryFilters").innerHTML = order.filter((o) => o[0] === "all" || o[2] > 0)
    .map((o) => `<button class="chip ${o[0] === active ? "active" : ""}" data-type="${o[0]}">${o[1]} <b>${o[2]}</b></button>`).join("");
  $("galleryFilters").querySelectorAll(".chip").forEach((c) =>
    c.addEventListener("click", () => loadGallery(c.dataset.type)));
}
function galleryItem(md) {
  if (md.type === "image" || md.type === "sticker") {
    return `<div class="g-item" data-lightbox="${md.url}" data-mime="${md.mime}" data-dl="${md.url}?download=true"><img src="${md.url}" loading="lazy"><span class="g-type">${md.type}</span></div>`;
  }
  if (md.type === "video") {
    return `<div class="g-item" data-lightbox="${md.url}" data-mime="${md.mime}" data-dl="${md.url}?download=true">
      <video src="${md.url}" preload="metadata"></video>
      <span class="g-play"><svg viewBox="0 0 24 24" width="46" height="46"><path fill="#fff" d="M8 5v14l11-7z"/></svg></span>
      <span class="g-type">video</span></div>`;
  }
  if (md.type === "audio") {
    return `<div class="g-item g-audio"><svg viewBox="0 0 24 24" width="40" height="40"><path fill="currentColor" d="M12 3v10.6A4 4 0 1014 17V7h4V3h-6z"/></svg>
      <span class="g-name">${esc(md.filename)}</span><audio src="${md.url}" controls preload="none" style="width:100%"></audio></div>`;
  }
  const ext = (md.filename.split(".").pop() || "DOC").toUpperCase().slice(0, 4);
  return `<a class="g-item g-doc" href="${md.url}?download=true" target="_blank" rel="noopener">
    <svg viewBox="0 0 24 24" width="40" height="40"><path fill="currentColor" d="M6 2h9l5 5v15H6z"/><path fill="#fff" d="M14 2v6h6"/></svg>
    <b>${ext}</b><span class="g-name">${esc(md.filename)}</span><span class="muted">${fmtSize(md.size)}</span></a>`;
}

/* ----------------------------------------------------------------- info */
function renderInfo() {
  const c = state.activeChat;
  const parts = c.participants || [];
  $("infoCard").innerHTML = `
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:8px">
      <div class="avatar" style="width:64px;height:64px;font-size:26px;background:${colorFor(c.name)}">${esc(initials(c.name))}</div>
      <div><h3>${esc(c.name)}</h3><span class="muted">${c.is_group ? "Group chat" : "Direct chat"}${c.phone_number ? " · " + esc(c.phone_number) : ""}</span></div>
    </div>
    <div class="info-grid">
      <div class="info-stat"><b>${c.message_count.toLocaleString()}</b><span>Messages</span></div>
      <div class="info-stat"><b>${c.media_count.toLocaleString()}</b><span>Media</span></div>
      <div class="info-stat"><b>${parts.length}</b><span>People</span></div>
    </div>
    <div class="muted" style="margin-bottom:6px">${c.first_timestamp ? "From " + fmtDay(c.first_timestamp) + " to " + fmtDay(c.last_timestamp) : ""}</div>
    <h4 style="margin:14px 0 4px">Participants</h4>
    ${parts.map((p) => `
      <div class="participant">
        <div class="avatar" style="background:${colorFor(p.name)}">${esc(initials(p.name))}</div>
        <div><div class="p-name">${esc(p.name)} ${p.name === state.meName ? '<span class="tag-group">You</span>' : ""}</div>
        ${p.phone_number ? `<div class="p-num">${esc(p.phone_number)}</div>` : ""}</div>
        <span class="p-count">${p.message_count.toLocaleString()} msgs</span>
        <button class="chip" style="padding:4px 10px;font-size:11px" data-me="${esc(p.name)}">Set as you</button>
      </div>`).join("")}
  `;
  $("infoCard").querySelectorAll("[data-me]").forEach((b) =>
    b.addEventListener("click", () => { state.meName = b.dataset.me; toast("Marked " + b.dataset.me + " as you"); state.msgOffset = 0; $("messages").dataset.lastDay = ""; loadMessages(true); switchTab("chat"); }));
}

/* -------------------------------------------------------------- lightbox */
function openLightbox(url, mime, dl) {
  const c = $("lightboxContent");
  if ((mime || "").startsWith("video")) {
    c.innerHTML = `<video src="${url}" controls autoplay></video>`;
  } else {
    c.innerHTML = `<img src="${url}">`;
  }
  $("lightboxDownload").href = dl || url;
  $("lightbox").classList.remove("hidden");
}
function closeLightbox() {
  $("lightbox").classList.add("hidden");
  $("lightboxContent").innerHTML = "";
}

/* ---------------------------------------------------------------- upload */
function uploadFile(file) {
  if (!file) return;
  $("dropzone").classList.add("hidden");
  $("uploadProgress").classList.remove("hidden");
  $("upFileName").textContent = file.name + " (" + fmtSize(file.size) + ")";
  const xhr = new XMLHttpRequest();
  xhr.open("POST", `/api/upload?filename=${encodeURIComponent(file.name)}&size=${file.size}`);
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      const pct = Math.round((e.loaded / e.total) * 100);
      $("upBar").style.width = pct + "%";
      $("upStatus").textContent = `Uploading… ${pct}% (${fmtSize(e.loaded)} / ${fmtSize(e.total)})`;
    }
  };
  xhr.onload = () => {
    if (xhr.status >= 200 && xhr.status < 300) {
      const res = JSON.parse(xhr.responseText);
      $("upStatus").textContent = "Uploaded. Processing…";
      pollJob(res.job_id);
    } else {
      $("upStatus").textContent = "Upload failed (" + xhr.status + ")";
    }
  };
  xhr.onerror = () => { $("upStatus").textContent = "Network error during upload."; };
  xhr.send(file);
}

async function pollJob(jobId) {
  try {
    const j = await api(`/api/jobs/${jobId}`);
    renderJobsSoon();
    if (j.status === "processing") {
      $("upBar").style.width = j.progress + "%";
      $("upStatus").textContent = `${j.stage}… ${j.progress}% · ${j.messages_found} msgs, ${j.media_found} media`;
      setTimeout(() => pollJob(jobId), 1000);
    } else if (j.status === "uploaded") {
      $("upStatus").textContent = "Queued for processing…";
      setTimeout(() => pollJob(jobId), 800);
    } else if (j.status === "done") {
      $("upBar").style.width = "100%";
      $("upStatus").textContent = `Done! ${j.chats_found} chat(s), ${j.messages_found} messages, ${j.media_found} media.`;
      toast("Export processed successfully");
      loadStats(); loadChats();
      setTimeout(resetUploadForm, 1500);
    } else if (j.status === "error") {
      $("upStatus").textContent = "Error: " + j.error;
    }
  } catch (e) {
    $("upStatus").textContent = "Lost track of job.";
  }
}
function resetUploadForm() {
  $("dropzone").classList.remove("hidden");
  $("uploadProgress").classList.add("hidden");
  $("upBar").style.width = "0";
  $("fileInput").value = "";
}

let jobsTimer = null;
function renderJobsSoon() { clearTimeout(jobsTimer); jobsTimer = setTimeout(renderJobs, 200); }
async function renderJobs() {
  try {
    const jobs = await api("/api/jobs");
    $("jobs").innerHTML = jobs.length ? "<h4 style='margin-bottom:8px'>Recent uploads</h4>" + jobs.map((j) => `
      <div class="job-row">
        <span class="j-name">${esc(j.original_filename)}</span>
        <span class="job-status js-${j.status}">${j.status}${j.status === "processing" ? " " + j.progress + "%" : ""}</span>
        <button class="j-del" data-job="${j.id}" title="Delete">🗑</button>
      </div>`).join("") : "";
    $("jobs").querySelectorAll(".j-del").forEach((b) =>
      b.addEventListener("click", async () => {
        if (!confirm("Delete this upload and all its chats/media?")) return;
        await fetch(`/api/jobs/${b.dataset.job}`, { method: "DELETE" });
        renderJobs(); loadStats(); loadChats();
        toast("Deleted");
      }));
  } catch (e) { /* ignore */ }
}

/* ------------------------------------------------------------------ init */
function bindEvents() {
  $("openUpload").addEventListener("click", () => { $("uploadModal").classList.remove("hidden"); renderJobs(); });
  $("closeUpload").addEventListener("click", () => $("uploadModal").classList.add("hidden"));
  $("uploadModal").addEventListener("click", (e) => { if (e.target === $("uploadModal")) $("uploadModal").classList.add("hidden"); });

  const dz = $("dropzone");
  dz.addEventListener("click", () => $("fileInput").click());
  $("fileInput").addEventListener("change", (e) => uploadFile(e.target.files[0]));
  ["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => { if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]); });

  document.querySelectorAll(".conv-tabs .tab").forEach((t) =>
    t.addEventListener("click", () => switchTab(t.dataset.tab)));

  $("backBtn").addEventListener("click", () => document.querySelector(".layout").classList.remove("show-chat"));

  let searchTimer;
  $("chatSearch").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadChats(e.target.value.trim()), 250);
  });
  let msgTimer;
  $("msgSearch").addEventListener("input", () => {
    clearTimeout(msgTimer);
    msgTimer = setTimeout(() => { state.msgOffset = 0; $("messages").dataset.lastDay = ""; loadMessages(true); }, 300);
  });

  $("lightboxClose").addEventListener("click", closeLightbox);
  $("lightbox").addEventListener("click", (e) => { if (e.target === $("lightbox")) closeLightbox(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeLightbox(); });
}

bindEvents();
loadStats();
loadChats();
