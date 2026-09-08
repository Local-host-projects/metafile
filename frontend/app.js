/* Metafile Studio — auth -> dashboard -> multi-artifact metafiles. */
const API = window.location.origin;
const AGENT = "studio-ui";

/* ================= icons (24px, 1.8 stroke, round) ================= */

const P = (d, extra = "") =>
  `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}${extra}</svg>`;

const ICONS = {
  facts: P('<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>'),
  spreadsheet: P('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M9 4v16M15 4v16"/>'),
  html: P('<path d="M8 6l-6 6 6 6M16 6l6 6-6 6"/>'),
  canvas: P('<rect x="4" y="4" width="8" height="8" rx="1.5"/><circle cx="16.5" cy="16.5" r="4.5"/>'),
  calendar: P('<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/>'),
  timer: P('<circle cx="12" cy="13" r="8"/><path d="M12 9v4l3 2M9 2h6"/>'),
  media: P('<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M4 18l5-5 3 3 3-3 5 5"/>'),
  plus: P('<path d="M12 5v14M5 12h14"/>'),
  search: P('<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>'),
  x: P('<path d="M6 6l12 12M18 6L6 18"/>'),
  check: P('<path d="M5 12l5 5 9-11"/>'),
  trash: P('<path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13M10 11v6M14 11v6"/>'),
  pencil: P('<path d="M17 3l4 4L8 20l-5 1 1-5L17 3z"/>'),
  link: P('<path d="M10 14a5 5 0 007 0l3-3a5 5 0 00-7-7l-1.5 1.5M14 10a5 5 0 00-7 0l-3 3a5 5 0 007 7l1.5-1.5"/>'),
  card: P('<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/>'),
  bank: P('<path d="M3 10l9-6 9 6M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18"/>'),
  logout: P('<path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/>'),
  back: P('<path d="M19 12H5M11 18l-6-6 6-6"/>'),
  bolt: P('<path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z"/>'),
  users: P('<circle cx="9" cy="8" r="3.5"/><path d="M3.5 20c.5-3.5 2.8-5.5 5.5-5.5s5 2 5.5 5.5"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14.7c2.3.3 3.9 2 4.3 4.8"/>'),
  folder: P('<path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/>'),
  history: P('<path d="M3 12a9 9 0 109-9 9.5 9.5 0 00-7 3.3L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>'),
};

const TYPE_META = {
  facts: { label: "Memory", desc: "Searchable facts — the portable memory layer." },
  spreadsheet: { label: "Spreadsheet", desc: "Live cells and formulas agents compute on." },
  html: { label: "Page", desc: "A rendered HTML page in a sandbox." },
  canvas: { label: "Canvas", desc: "A shared drawing surface for strokes." },
  calendar: { label: "Calendar", desc: "Events any agent can read or add." },
  timer: { label: "Timer", desc: "Countdowns computed live on fetch." },
  media: { label: "Media", desc: "Images, audio and video, stored inline." },
};

/* ================= stores ================= */

const Auth = {
  get token() { return localStorage.getItem("mf_auth_token"); },
  set token(v) { v ? localStorage.setItem("mf_auth_token", v) : localStorage.removeItem("mf_auth_token"); },
};

const tokenStore = {
  all() { try { return JSON.parse(localStorage.getItem("metafile_tokens") || "{}"); } catch (e) { return {}; } },
  save(id, rw, ro) { const t = this.all(); t[id] = { rw, ro }; localStorage.setItem("metafile_tokens", JSON.stringify(t)); },
  get(id) { return this.all()[id] || null; },
};

const sessionStore = {
  all() { try { return JSON.parse(localStorage.getItem("metafile_sessions") || "{}"); } catch (e) { return {}; } },
  save(id, owner, collab, name) { const s = this.all(); s[id] = { owner, collab, name }; localStorage.setItem("metafile_sessions", JSON.stringify(s)); },
  get(id) { return this.all()[id] || null; },
};

/* ================= api client ================= */

async function api(method, path, { body, auth = true, query = "" } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth && Auth.token) headers["Authorization"] = `Bearer ${Auth.token}`;
  const res = await fetch(`${API}${path}${query}`, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401 && auth) { showAuth(); throw new Error("Signed out — please sign in again."); }
  let data = {};
  try { data = await res.json(); } catch (e) { /* empty */ }
  if (!res.ok) {
    const err = new Error(typeof data.detail === "string" ? data.detail : "Request failed");
    err.status = res.status;
    err.data = data.detail;
    throw err;
  }
  return data;
}

const capQuery = (id) => {
  const t = tokenStore.get(id);
  return t ? `?token=${encodeURIComponent(t.rw)}` : "";
};

/* ================= toast ================= */

function toast(msg, isErr = false) {
  const root = document.getElementById("toast-root");
  const t = document.createElement("div");
  t.className = "toast" + (isErr ? " err" : "");
  t.textContent = msg;
  root.appendChild(t);
  setTimeout(() => t.remove(), 2800);
}

/* ================= modal system (no more prompt()) ================= */

function openModal({ title, sub = "", body = "", actions = [], wide = false }) {
  const root = document.getElementById("modal-root");
  root.innerHTML = `
    <div class="modal-backdrop">
      <div class="modal${wide ? " wide" : ""}" role="dialog" aria-label="${escapeHtml(title)}">
        <div class="modal-head"><h3>${escapeHtml(title)}</h3><button class="icon-btn" data-close>${ICONS.x}</button></div>
        ${sub ? `<p class="modal-sub">${sub}</p>` : ""}
        <div class="modal-body"></div>
        <div class="modal-foot"></div>
      </div>
    </div>`;
  const backdrop = root.firstElementChild;
  const modalEl = backdrop.firstElementChild;
  const bodyEl = modalEl.querySelector(".modal-body");
  const footEl = modalEl.querySelector(".modal-foot");
  if (typeof body === "string") bodyEl.innerHTML = body; else if (body) bodyEl.appendChild(body);

  let closed = false;
  const close = () => { if (closed) return; closed = true; root.innerHTML = ""; document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  modalEl.querySelector("[data-close]").addEventListener("click", close);
  backdrop.addEventListener("mousedown", (e) => { if (e.target === backdrop) close(); });

  actions.forEach((a) => {
    const b = document.createElement("button");
    b.className = `btn ${a.kind === "primary" ? "btn-primary" : a.kind === "danger" ? "btn-danger-ghost" : "btn-ghost"}`;
    b.innerHTML = a.label;
    b.addEventListener("click", () => a.onClick && a.onClick(close, modalEl));
    footEl.appendChild(b);
  });
  if (!actions.length) footEl.remove();
  const first = modalEl.querySelector("input");
  if (first) setTimeout(() => first.focus(), 60);
  return { close, el: modalEl, body: bodyEl };
}

function confirmModal({ title, message, ok = "Delete", danger = true }) {
  return new Promise((resolve) => {
    const { close, body } = openModal({
      title,
      body: `<p style="margin:0 0 4px;font-size:14px;color:var(--ink-2);">${message}</p>`,
      actions: [
        { label: "Cancel", onClick: (c) => { c(); resolve(false); } },
        { label: ok, kind: danger ? "danger" : "primary", onClick: (c) => { c(); resolve(true); } },
      ],
    });
    void body;
  });
}

function promptModal({ title, sub = "", value = "", placeholder = "", ok = "Save" }) {
  return new Promise((resolve) => {
    const { close, body } = openModal({
      title, sub,
      body: `<div class="field"><input id="promptInput" value="${escapeAttr(value)}" placeholder="${escapeAttr(placeholder)}"></div>`,
      actions: [
        { label: "Cancel", onClick: (c) => { c(); resolve(null); } },
        { label: ok, kind: "primary", onClick: (c, el) => { const v = el.querySelector("#promptInput").value.trim(); c(); resolve(v || null); } },
      ],
    });
    body.querySelector("#promptInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const v = e.target.value.trim();
        close(); resolve(v || null);
      }
    });
  });
}

/* ================= views ================= */

function show(name) {
  ["auth", "dash", "doc"].forEach((v) => {
    document.getElementById(`view-${v}`).classList.toggle("active", v === name);
  });
  if (name !== "doc") stopWatch();
  document.getElementById("mainNav").style.display = name === "auth" ? "none" : "flex";
  document.querySelectorAll("#mainNav .nav-btn").forEach((b) => b.classList.remove("active"));
  if (name === "dash") document.getElementById("navDash").classList.add("active");
}

/* ================= auth ================= */

let authMode = "signin";

function showAuth() {
  Auth.token = null;
  state.user = null;
  document.getElementById("userChip").style.display = "none";
  show("auth");
}

function setAuthMode(mode) {
  authMode = mode;
  document.getElementById("tabSignin").classList.toggle("active", mode === "signin");
  document.getElementById("tabSignup").classList.toggle("active", mode === "signup");
  document.getElementById("nameField").style.display = mode === "signup" ? "block" : "none";
  document.getElementById("authSubmit").textContent = mode === "signup" ? "Create account" : "Sign in";
  authError("");
}

function authError(msg) {
  const el = document.getElementById("authError");
  el.textContent = msg;
  el.classList.toggle("show", !!msg);
}

async function submitAuth() {
  const email = document.getElementById("authEmail").value.trim();
  const password = document.getElementById("authPassword").value;
  const name = document.getElementById("authName").value.trim() || "Untitled";
  if (!email || !password) return authError("Email and password are required.");
  try {
    const data = await api("POST", authMode === "signup" ? "/auth/register" : "/auth/login", {
      body: authMode === "signup" ? { name, email, password } : { email, password },
      auth: false,
    });
    Auth.token = data.token;
    await bootAfterLogin();
    toast(`Welcome${data.user.name ? ", " + data.user.name : ""}.`);
  } catch (e) {
    authError(e.message);
  }
}

async function bootAfterLogin() {
  const me = await api("GET", "/auth/me");
  state.user = me.user;
  document.getElementById("userEmail").textContent = me.user.email;
  document.getElementById("avatarTx").textContent = (me.user.name || me.user.email || "?")[0].toUpperCase();
  document.getElementById("userChip").style.display = "flex";
  show("dash");
  await loadDashboard();
  await checkPaidCallback();
}

/* ================= dashboard ================= */

let state = { user: null, files: [], currentId: null, current: null, activeAid: null };

async function loadDashboard() {
  state.files = await api("GET", "/metafiles");
  renderDashboard();
  const unclaimed = state.files.filter((f) => !f.claimed);
  if (unclaimed.length && !sessionStorage.getItem("claim_nag")) {
    sessionStorage.setItem("claim_nag", "1");
    toast(`${unclaimed.length} legacy file${unclaimed.length > 1 ? "s" : ""} ready to claim.`);
  }
}

function renderDashboard() {
  const q = document.getElementById("dashSearch").value.trim().toLowerCase();
  const rows = state.files.filter((f) => !q || f.name.toLowerCase().includes(q));
  const grid = document.getElementById("fileGrid");
  document.getElementById("dashEmpty").style.display = state.files.length ? "none" : "block";
  grid.style.display = state.files.length ? "grid" : "none";
  const totalBytes = state.files.reduce((s, f) => s + f.bytes_used, 0);
  document.getElementById("dashSub").textContent =
    `${state.files.length} metafile${state.files.length === 1 ? "" : "s"} · ${fmtBytes(totalBytes)} stored`;

  grid.innerHTML = rows.map((f) => {
    const icons = f.artifacts.slice(0, 4).map((a) => `<span class="stack-ic">${ICONS[a.type] || ICONS.folder}</span>`).join("");
    const more = f.artifacts.length > 4 ? `<span class="stack-more">+${f.artifacts.length - 4}</span>` : "";
    const pct = Math.min(100, (f.bytes_used / f.byte_limit) * 100);
    const tier = !f.claimed
      ? `<span class="tier-chip unclaimed">Unclaimed</span>`
      : f.tier === "paid" ? `<span class="tier-chip paid">Paid</span>` : `<span class="tier-chip">Free</span>`;
    return `
    <div class="file-card" data-id="${f.id}">
      <div class="file-card-top">
        <div class="icon-stack">${icons || `<span class="stack-ic">${ICONS.folder}</span>`}${more}</div>
        ${tier}
      </div>
      <div class="file-name">${escapeHtml(f.name)}</div>
      <div class="file-meta">${f.artifact_count} block${f.artifact_count === 1 ? "" : "s"} · ${fmtBytes(f.bytes_used)} / ${fmtBytes(f.byte_limit)} · ${timeAgo(f.updated_at)}</div>
      <div class="meter"><div class="${pct > 90 ? "full" : pct > 60 ? "warn" : ""}" style="width:${pct}%"></div></div>
      <div class="file-actions">
        ${!f.claimed
          ? `<button class="btn btn-primary btn-sm" data-act="claim">Claim</button>`
          : `<button class="btn btn-primary btn-sm" data-act="open">Open</button>`}
        <button class="icon-btn" data-act="rename" title="Rename">${ICONS.pencil}</button>
        ${f.claimed && f.tier === "free" ? `<button class="icon-btn" data-act="upgrade" title="Upgrade to paid">${ICONS.bolt}</button>` : ""}
        <button class="icon-btn danger" data-act="delete" title="Delete">${ICONS.trash}</button>
      </div>
    </div>`;
  }).join("") || `<div style="grid-column:1/-1;color:var(--faint);font-size:14px;">No matches.</div>`;

  grid.querySelectorAll(".file-card").forEach((card) => {
    const id = card.dataset.id;
    card.querySelectorAll("[data-act]").forEach((btn) => {
      btn.addEventListener("click", (e) => { e.stopPropagation(); fileAction(id, btn.dataset.act); });
    });
    card.addEventListener("click", () => {
      const f = state.files.find((x) => x.id === id);
      if (f && f.claimed) openFile(id);
      else if (f) fileAction(id, "claim");
    });
  });
}

async function fileAction(id, act) {
  const f = state.files.find((x) => x.id === id);
  if (!f) return;
  if (act === "open") return openFile(id);
  if (act === "claim") {
    try {
      await api("POST", `/metafiles/${id}/claim`);
      toast("Claimed to your account.");
      await loadDashboard();
    } catch (e) { toast(e.message, true); }
    return;
  }
  if (act === "rename") {
    const name = await promptModal({ title: "Rename metafile", value: f.name, ok: "Rename" });
    if (name === null) return;
    try {
      await api("PATCH", `/metafiles/${id}${capQuery(id).replace("?", "&").replace("&", "?")}`, { body: { name } });
      await loadDashboard();
    } catch (e) { toast(e.message, true); }
    return;
  }
  if (act === "upgrade") {
    openFile(id, () => openPayModal());
    return;
  }
  if (act === "delete") {
    const ok = await confirmModal({
      title: "Delete metafile?",
      message: `“${escapeHtml(f.name)}” and its ${f.artifact_count} block(s) will be permanently deleted. Share links stop working.`,
      ok: "Delete forever",
    });
    if (!ok) return;
    try {
      await api("DELETE", `/metafiles/${id}`);
      toast("Deleted.");
      await loadDashboard();
    } catch (e) { toast(e.message, true); }
  }
}

async function createFileFlow() {
  const name = await promptModal({ title: "New metafile", sub: "A container for blocks — memory, spreadsheets, pages and more.", value: "", placeholder: "e.g. Launch plan", ok: "Create" });
  if (name === null) return;
  try {
    const data = await api("POST", "/metafiles", { body: { name: name || "Untitled metafile" } });
    tokenStore.save(data.id, data.rw_token, data.ro_token);
    await loadDashboard();
    openFile(data.id);
    toast("Metafile created — add your first block.");
  } catch (e) { toast(e.message, true); }
}

/* ================= detail ================= */

async function openFile(id, after) {
  const t = tokenStore.get(id);
  const q = t ? `?token=${encodeURIComponent(t.rw)}` : "";
  try {
    const data = await api("GET", `/m/${id}${q}`);
    state.currentId = id;
    state.current = data;
    if (!data.artifacts.find((a) => a.id === state.activeAid)) {
      state.activeAid = data.artifacts[0] ? data.artifacts[0].id : null;
    }
    show("doc");
    watchFile(id);
    renderDoc();
    if (after) after();
  } catch (e) { toast(e.message, true); }
}

function activeArtifact() {
  return (state.current.artifacts || []).find((a) => a.id === state.activeAid) || null;
}

function renderDoc() {
  const d = state.current;
  document.getElementById("docTitle").value = d.name;
  document.getElementById("deleteFileBtn").innerHTML = ICONS.trash;

  const pct = Math.min(100, (d.bytes_used / d.byte_limit) * 100);
  document.getElementById("docTelemetry").innerHTML = `
    <span class="chip live-chip ${live.connected ? "on" : "off"}" id="liveChip">${live.connected ? "● live" : "○ offline"}</span>
    <span class="chip accent">${d.artifacts.length} block${d.artifacts.length === 1 ? "" : "s"}</span>
    <span class="chip ${d.tier === "paid" ? "ok" : ""}">${d.tier === "paid" ? "Paid · 100 MB" : "Free · 5 MB"}</span>
    <span class="chip">v${String(d.version).padStart(2, "0")}</span>
    <div class="meter"><div class="${pct > 90 ? "full" : pct > 60 ? "warn" : ""}" style="width:${pct}%"></div></div>
    <span class="chip">${fmtBytes(d.bytes_used)} / ${fmtBytes(d.byte_limit)}</span>
    ${d.claimed ? "" : `<button class="btn btn-ghost btn-sm" id="claimBtn">Claim to my account</button>`}
  `;
  document.getElementById("upgradeBtn").style.display = d.tier === "free" && d.claimed ? "" : "none";
  const claimBtn = document.getElementById("claimBtn");
  if (claimBtn) claimBtn.addEventListener("click", () => fileAction(d.id, "claim").then(() => openFile(d.id)));

  const tabsEl = document.getElementById("tabs");
  tabsEl.innerHTML =
    d.artifacts.map((a) => `
      <button class="tab ${a.id === state.activeAid ? "active" : ""}" data-aid="${a.id}">
        ${ICONS[a.type] || ICONS.folder}${escapeHtml(a.name)}
      </button>`).join("") +
    `<button class="tab add-tab" id="addTab">${ICONS.plus}Add block</button>`;

  tabsEl.querySelectorAll(".tab[data-aid]").forEach((b) => {
    b.addEventListener("click", () => { state.activeAid = b.dataset.aid; renderDoc(); });
  });
  document.getElementById("addTab").addEventListener("click", addArtifactFlow);

  renderArtifact();
}

async function refreshCurrent() {
  if (state.currentId) {
    const keepAid = state.activeAid;
    await openFile(state.currentId);
    state.activeAid = keepAid;
    renderDoc();
  }
}

/* ================= live sync (SSE) ================= */

function streamEvents(url, headers, onEvent, onStatus) {
  const ctrl = new AbortController();
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  (async () => {
    while (!ctrl.signal.aborted) {
      try {
        const res = await fetch(url, { headers, signal: ctrl.signal, cache: "no-store" });
        if (!res.ok || !res.body) {
          if (onStatus) onStatus("retry");
          await sleep(2500);
          continue;
        }
        if (onStatus) onStatus("open");
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let i;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const chunk = buf.slice(0, i);
            buf = buf.slice(i + 2);
            const data = chunk.split("\n")
              .filter((l) => l.startsWith("data:"))
              .map((l) => l.slice(5).trim())
              .join("\n");
            if (data) {
              try { onEvent(JSON.parse(data)); } catch (e) { /* keepalive/parse */ }
            }
          }
        }
      } catch (e) {
        if (ctrl.signal.aborted) return;
      }
      if (onStatus) onStatus("retry");
      await sleep(2500);
    }
  })();
  return { abort: () => ctrl.abort() };
}

let live = { id: null, handle: null, connected: false, pending: false };
let liveRefreshTimer = null;

function watchFile(id) {
  stopWatch();
  const t = tokenStore.get(id);
  const headers = {};
  let url = `${API}/events/m/${id}`;
  if (t) url += `?token=${encodeURIComponent(t.rw)}`;
  else headers["Authorization"] = `Bearer ${Auth.token}`;
  live = { id, handle: streamEvents(url, headers, (ev) => onLiveEvent(id, ev), (st) => {
    live.connected = st === "open";
    updateLiveChip();
  }), connected: false, pending: false };
}

function stopWatch() {
  if (live.handle) live.handle.abort();
  live = { id: null, handle: null, connected: false, pending: false };
}

function updateLiveChip() {
  const el = document.getElementById("liveChip");
  if (!el) return;
  el.className = "chip live-chip " + (live.connected ? "on" : "off");
  el.textContent = live.connected ? "● live" : "○ offline";
}

function isTypingNow() {
  const el = document.activeElement;
  if (!el) return false;
  if (el.id === "docTitle") return true;
  const panel = document.getElementById("panel");
  return !!panel && panel.contains(el) && (el.tagName === "INPUT" || el.tagName === "TEXTAREA");
}

function scheduleLiveRefresh() {
  if (liveRefreshTimer) return;
  liveRefreshTimer = setTimeout(async () => {
    liveRefreshTimer = null;
    if (isTypingNow()) { live.pending = true; return; }
    live.pending = false;
    if (state.currentId === live.id) await refreshCurrent();
  }, 350);
}

async function onLiveEvent(id, ev) {
  if (state.currentId !== id) return;
  if (ev.kind === "deleted") {
    stopWatch();
    toast("This metafile was deleted elsewhere.");
    show("dash");
    await loadDashboard();
    return;
  }
  scheduleLiveRefresh();
}

/* ---- artifact toolbar + dispatch ---- */

function artifactBar(art, { history = true } = {}) {
  return `
    <div class="artifact-bar">
      <h3>${escapeHtml(art.name)}</h3>
      <span class="chip accent">${TYPE_META[art.type].label}</span>
      <span class="chip">v${String(art.version).padStart(2, "0")}</span>
      <span class="spacer"></span>
      <button class="icon-btn" data-ab="rename" title="Rename block">${ICONS.pencil}</button>
      ${history ? `<button class="icon-btn" data-ab="history" title="Edit history">${ICONS.history}</button>` : ""}
      <button class="icon-btn danger" data-ab="del" title="Delete block">${ICONS.trash}</button>
    </div>
    <div class="artifact-body"></div>`;
}

function wireArtifactBar(panel, art) {
  panel.querySelectorAll("[data-ab]").forEach((b) => {
    b.addEventListener("click", async () => {
      const act = b.dataset.ab;
      if (act === "rename") {
        const name = await promptModal({ title: "Rename block", value: art.name, ok: "Rename" });
        if (name === null) return;
        try {
          await api("PATCH", `/metafiles/${state.currentId}/artifacts/${art.id}${capQuery(state.currentId)}&agent=${AGENT}&if_version=${state.current.version}`, { body: { name } });
          await refreshCurrent();
        } catch (e) { toast(e.message, true); }
      }
      if (act === "history") openHistoryModal(art);
      if (act === "del") {
        const ok = await confirmModal({ title: "Delete block?", message: `“${escapeHtml(art.name)}” will be permanently deleted.`, ok: "Delete block" });
        if (!ok) return;
        try {
          await api("DELETE", `/metafiles/${state.currentId}/artifacts/${art.id}${capQuery(state.currentId)}&agent=${AGENT}&if_version=${state.current.version}`);
          state.activeAid = null;
          await refreshCurrent();
        } catch (e) { toast(e.message, true); }
      }
    });
  });
}

function renderArtifact() {
  const panel = document.getElementById("panel");
  const art = activeArtifact();
  if (!art) {
    panel.innerHTML = `
      <div class="empty-state">
        <div class="big-ic">${ICONS.folder}</div>
        <h3>Empty metafile</h3>
        <p>Add your first block to start — any agent with the link can read and update it.</p>
        <button class="btn btn-primary" id="emptyAdd">+ Add block</button>
      </div>`;
    document.getElementById("emptyAdd").addEventListener("click", addArtifactFlow);
    return;
  }
  panel.innerHTML = artifactBar(art);
  wireArtifactBar(panel, art);
  const body = panel.querySelector(".artifact-body");
  ({
    facts: renderFacts, spreadsheet: renderGrid, html: renderHtmlEditor,
    canvas: renderCanvas, calendar: renderCalendar, timer: renderTimers, media: renderMedia,
  }[art.type] || ((b) => { b.innerHTML = "<p>Unsupported block type.</p>"; }))(body, art);
}

async function addArtifactFlow() {
  const { close, body } = openModal({
    title: "Add block",
    sub: `Choose a block type for “${state.current.name}”.`,
    wide: true,
    body: `<div class="type-pick">${Object.entries(TYPE_META).map(([t, m]) => `
      <button data-type="${t}">
        <span class="pick-ic">${ICONS[t]}</span>
        <span><b>${m.label}</b><span>${m.desc}</span></span>
      </button>`).join("")}</div>`,
  });
  body.querySelectorAll("[data-type]").forEach((b) => {
    b.addEventListener("click", async () => {
      const type = b.dataset.type;
      close();
      try {
        const res = await api("POST", `/metafiles/${state.currentId}/artifacts${capQuery(state.currentId)}`, {
          body: { artifact_type: type, agent: AGENT, if_version: state.current.version },
        });
        state.activeAid = res.artifact.id;
        await refreshCurrent();
        toast(`${TYPE_META[type].label} block added.`);
      } catch (e) { toast(e.message, true); }
    });
  });
}

/* ---- mutations ---- */

async function mutate(op, path, value) {
  const art = activeArtifact();
  if (!art) return null;
  const t = tokenStore.get(state.currentId);
  const p = new URLSearchParams({ op, agent: AGENT, if_version: art.version, artifact: art.id });
  if (t) p.set("token", t.rw);
  if (path !== undefined && path !== null) p.set("path", path);
  if (value !== undefined && value !== null) p.set("value", value);
  try {
    const data = await api("GET", `/m/${state.currentId}?${p.toString()}`);
    state.current = data;
    state.activeAid = art.id;
    return data;
  } catch (e) {
    if (e.status === 409) { toast("Someone else edited first — refreshed."); await refreshCurrent(); return null; }
    if (e.status === 402) { toast("Over the size limit — upgrade to keep writing.", true); return null; }
    toast(e.message, true);
    return null;
  }
}

async function bulkMutate(op, value, artifactId) {
  const art = activeArtifact();
  const aid = artifactId || (art && art.id);
  if (!aid) return null;
  const t = tokenStore.get(state.currentId);
  const q = t ? `?token=${encodeURIComponent(t.rw)}` : "";
  const cur = (state.current.artifacts || []).find((a) => a.id === aid) || art;
  try {
    const data = await api("POST", `/m/${state.currentId}/bulk${q}`, {
      body: { op, artifact: aid, value, if_version: cur.version, agent: AGENT },
    });
    state.current = data;
    state.activeAid = aid;
    return data;
  } catch (e) {
    if (e.status === 409) { toast("Version conflict — refreshed."); await refreshCurrent(); return null; }
    if (e.status === 402) { toast("Over the size limit — upgrade to keep writing.", true); return null; }
    toast(e.message, true);
    return null;
  }
}

/* ---- facts ---- */

function renderFacts(body, art) {
  const facts = art.content.facts || [];
  body.innerHTML = `
    <div class="inline-form" style="margin:0 0 8px;">
      <input class="text-input" id="searchQ" placeholder="Search these facts…">
    </div>
    <div id="searchResults"></div>
    <div class="ledger" id="factsList" style="margin-top:10px;">${facts.map((f) => `
      <div class="ledger-row">
        <div class="ledger-main">${escapeHtml(f.text)}</div>
        <div class="ledger-sub">${timeAgo(f.at)}</div>
        <button class="row-x" data-id="${f.id}">×</button>
      </div>`).join("") || `<div style="color:var(--faint);font-size:13px;padding:14px 0;">No facts yet.</div>`}</div>
    <div class="inline-form">
      <input class="text-input" id="newFact" placeholder="Add a fact any agent can fetch or search…">
      <button class="btn btn-primary" id="addFactBtn">Add</button>
    </div>`;
  const add = async () => {
    const input = document.getElementById("newFact");
    if (!input.value.trim()) return;
    const data = await mutate("append", null, input.value.trim());
    if (data) renderDoc();
  };
  document.getElementById("addFactBtn").addEventListener("click", add);
  document.getElementById("newFact").addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
  body.querySelectorAll(".row-x").forEach((b) => {
    b.addEventListener("click", async () => {
      const data = await mutate("delete", b.dataset.id, null);
      if (data) renderDoc();
    });
  });
  const runSearch = async () => {
    const q = document.getElementById("searchQ").value.trim();
    const box = document.getElementById("searchResults");
    if (!q) { box.innerHTML = ""; return; }
    const t = tokenStore.get(state.currentId);
    const p = new URLSearchParams({ op: "search", artifact: art.id, q });
    if (t) p.set("token", t.rw);
    try {
      const data = await api("GET", `/m/${state.currentId}?${p.toString()}`);
      box.innerHTML = `<div class="ledger" style="margin-bottom:6px;">${data.results.map((r) => `
        <div class="ledger-row">
          <div class="ledger-main">${escapeHtml(r.fact.text)}</div>
          <div class="score-track"><div style="width:${Math.round(r.score * 100)}%"></div></div>
        </div>`).join("") || `<div style="color:var(--faint);font-size:13px;">No matches.</div>`}</div>`;
    } catch (e) { toast(e.message, true); }
  };
  let deb;
  document.getElementById("searchQ").addEventListener("input", () => { clearTimeout(deb); deb = setTimeout(runSearch, 300); });
}

/* ---- spreadsheet ---- */

function renderGrid(body, art) {
  const cols = art.content.cols || 8;
  const rows = art.content.rows || 20;
  const cells = art.content.cells || {};
  const evaluated = (art.computed && art.computed.evaluated) || {};
  const L = (i) => String.fromCharCode(65 + i);
  let html = `<div class="sheet-wrap"><table class="sheet"><tr><th></th>${Array.from({ length: cols }, (_, c) => `<th>${L(c)}</th>`).join("")}</tr>`;
  for (let r = 0; r < rows; r++) {
    html += `<tr><td class="row-head">${r + 1}</td>`;
    for (let c = 0; c < cols; c++) {
      const ref = `${L(c)}${r + 1}`;
      const cell = cells[ref];
      html += `<td><input data-ref="${ref}" value="${escapeAttr(cell ? cell.formula || cell.value || "" : "")}"></td>`;
    }
    html += "</tr>";
  }
  body.innerHTML = html + "</table></div>";
  body.querySelectorAll("input[data-ref]").forEach((input) => {
    const ref = input.dataset.ref;
    const cell = cells[ref];
    input.addEventListener("focus", () => { input.value = cell ? cell.formula || cell.value || "" : ""; });
    input.addEventListener("blur", async () => {
      const val = input.value;
      const prev = cell ? cell.formula || cell.value || "" : "";
      if (val === prev) { if (evaluated[ref] !== undefined) input.value = evaluated[ref]; return; }
      const data = await mutate(val === "" ? "delete" : "set", ref, val === "" ? null : val);
      if (data) renderDoc();
    });
  });
}

/* ---- html ---- */

function renderHtmlEditor(body, art) {
  const html = art.content.html || "";
  body.innerHTML = `
    <div class="html-grid">
      <div><div class="pane-label">Source — any agent can rewrite this</div><textarea id="htmlSrc">${escapeHtml(html)}</textarea></div>
      <div><div class="pane-label">Rendered — sandboxed</div><iframe id="htmlPreview" sandbox="allow-scripts"></iframe></div>
    </div>
    <div style="margin-top:14px;"><button class="btn btn-primary btn-sm" id="renderBtn">Save &amp; render</button></div>`;
  document.getElementById("htmlPreview").srcdoc = html;
  document.getElementById("renderBtn").addEventListener("click", async () => {
    const src = document.getElementById("htmlSrc").value;
    const data = await bulkMutate("set", { html: src });
    if (data) { document.getElementById("htmlPreview").srcdoc = src; toast("Saved."); }
  });
}

/* ---- canvas ---- */

function renderCanvas(body, art) {
  const c = art.content;
  const colors = ["#1D1D1F", "#55555A", "#8E8E93", "#C7C7CC", "#000000"];
  let activeColor = colors[0];
  body.innerHTML = `
    <div class="canvas-bar">
      ${colors.map((col) => `<button class="swatch ${col === activeColor ? "active" : ""}" data-c="${col}" style="background:${col}"></button>`).join("")}
      <span class="micro" style="margin-left:8px;">Strokes append — concurrent drawers merge</span>
    </div>
    <canvas id="drawCanvas" width="${c.width || 800}" height="${c.height || 600}"></canvas>`;
  const canvas = document.getElementById("drawCanvas");
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "white"; ctx.fillRect(0, 0, canvas.width, canvas.height);
  const drawStroke = (stroke) => {
    if (!stroke.points || stroke.points.length < 2) return;
    ctx.strokeStyle = stroke.color || "#000"; ctx.lineWidth = 3; ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(stroke.points[0][0], stroke.points[0][1]);
    stroke.points.forEach((p) => ctx.lineTo(p[0], p[1])); ctx.stroke();
  };
  (c.strokes || []).forEach(drawStroke);
  body.querySelectorAll(".swatch").forEach((b) => {
    b.addEventListener("click", () => {
      activeColor = b.dataset.c;
      body.querySelectorAll(".swatch").forEach((x) => x.classList.toggle("active", x === b));
    });
  });
  let drawing = false, points = [];
  const pos = (e) => { const r = canvas.getBoundingClientRect(); return [Math.round(e.clientX - r.left), Math.round(e.clientY - r.top)]; };
  canvas.addEventListener("mousedown", (e) => { drawing = true; points = [pos(e)]; });
  canvas.addEventListener("mousemove", (e) => {
    if (!drawing) return;
    points.push(pos(e));
    drawStroke({ points: points.slice(-2), color: activeColor });
  });
  window.addEventListener("mouseup", async () => {
    if (!drawing) return;
    drawing = false;
    if (points.length > 1) await bulkMutate("append", { tool: "pen", color: activeColor, points });
  }, { once: true });
}

/* ---- calendar ---- */

function renderCalendar(body, art) {
  const events = art.content.events || [];
  body.innerHTML = `
    <div class="ledger">${events.map((e) => {
      const d = e.start ? new Date(e.start) : null;
      const label = d ? d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—";
      return `<div class="ledger-row"><div class="ledger-sub" style="width:130px;color:var(--accent);font-weight:700;">${label}</div>
        <div class="ledger-main">${escapeHtml(e.title)}</div><button class="row-x" data-id="${e.id}">×</button></div>`;
    }).join("") || `<div style="color:var(--faint);font-size:13px;padding:14px 0;">No events yet.</div>`}</div>
    <div class="inline-form">
      <input class="text-input" id="evTitle" placeholder="Event title" style="flex:2;">
      <input class="text-input" id="evStart" type="datetime-local" style="flex:1;">
      <button class="btn btn-primary" id="addEvBtn">Add</button>
    </div>`;
  document.getElementById("addEvBtn").addEventListener("click", async () => {
    const title = document.getElementById("evTitle").value.trim();
    const start = document.getElementById("evStart").value;
    if (!title || !start) return toast("Title and start time are required.", true);
    const data = await bulkMutate("append", { title, start: new Date(start).toISOString() });
    if (data) renderDoc();
  });
  body.querySelectorAll(".row-x").forEach((b) => {
    b.addEventListener("click", async () => {
      const data = await mutate("delete", b.dataset.id, null);
      if (data) renderDoc();
    });
  });
}

/* ---- timer ---- */

function renderTimers(body, art) {
  const timers = art.content.timers || [];
  body.innerHTML = `
    <div class="ledger">${timers.map((t) => {
      const mins = Math.floor(t.remaining_seconds / 60), secs = Math.floor(t.remaining_seconds % 60);
      return `<div class="ledger-row">
        <div class="timer-big">${mins}:${String(secs).padStart(2, "0")}</div>
        <div class="ledger-main">${escapeHtml(t.label)}</div>
        <span class="status-dot ${t.status === "running" ? "running" : ""}">${t.status}</span>
        ${t.status === "running"
          ? `<button class="btn btn-ghost btn-sm" data-id="${t.id}" data-action="pause">Pause</button>`
          : `<button class="btn btn-ghost btn-sm" data-id="${t.id}" data-action="start">Start</button>`}
        <button class="btn btn-ghost btn-sm" data-id="${t.id}" data-action="reset">Reset</button>
        <button class="row-x" data-id="${t.id}">×</button>
      </div>`;
    }).join("") || `<div style="color:var(--faint);font-size:13px;padding:14px 0;">No timers yet.</div>`}</div>
    <div class="inline-form">
      <input class="text-input" id="timerLabel" placeholder="Label">
      <input class="text-input" id="timerSecs" type="number" placeholder="Seconds" style="max-width:130px;" value="300">
      <button class="btn btn-primary" id="addTimerBtn">Add</button>
    </div>`;
  document.getElementById("addTimerBtn").addEventListener("click", async () => {
    const label = document.getElementById("timerLabel").value.trim() || "Timer";
    const duration_seconds = Number(document.getElementById("timerSecs").value) || 300;
    const data = await bulkMutate("append", { label, duration_seconds });
    if (data) renderDoc();
  });
  body.querySelectorAll("[data-action]").forEach((b) => {
    b.addEventListener("click", async () => {
      const data = await mutate("set", b.dataset.id, b.dataset.action);
      if (data) renderDoc();
    });
  });
  body.querySelectorAll(".row-x").forEach((b) => {
    b.addEventListener("click", async () => {
      const data = await mutate("delete", b.dataset.id, null);
      if (data) renderDoc();
    });
  });
  if (timers.some((t) => t.status === "running")) {
    setTimeout(() => {
      if (state.activeAid === art.id && document.getElementById("panel")) {
        refreshCurrent();
      }
    }, 5000);
  }
}

/* ---- media ---- */

function renderMedia(body, art) {
  const items = art.content.items || [];
  body.innerHTML = `
    <input type="file" id="mediaFile" accept="image/*,audio/*,video/*" style="display:none;">
    <button class="btn btn-primary btn-sm" id="uploadBtn" style="margin-bottom:16px;">Upload media</button>
    <div class="media-grid">${items.map((item) => `
      <div class="media-item" data-id="${item.id}">
        <div class="media-slot" style="height:110px;display:flex;align-items:center;justify-content:center;color:var(--faint);font-size:11px;">loading…</div>
        <div class="media-caption">${escapeHtml(item.caption || item.kind)}</div>
      </div>`).join("") || `<div style="color:var(--faint);font-size:13px;">No media yet.</div>`}</div>`;
  document.getElementById("uploadBtn").addEventListener("click", () => document.getElementById("mediaFile").click());
  document.getElementById("mediaFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const kind = file.type.startsWith("image") ? "image" : file.type.startsWith("video") ? "video" : "audio";
    const reader = new FileReader();
    reader.onload = async () => {
      const base64 = reader.result.split(",")[1];
      const data = await bulkMutate("append", { kind, mime: file.type, data_base64: base64, caption: file.name });
      if (data) { toast("Uploaded."); renderDoc(); }
      else toast("Upload failed — likely over the size cap.", true);
    };
    reader.readAsDataURL(file);
  });
  loadMediaThumbs(items);
}

async function loadMediaThumbs(items) {
  const t = tokenStore.get(state.currentId);
  for (const item of items.slice(0, 24)) {
    const el = document.querySelector(`.media-item[data-id="${item.id}"] .media-slot`);
    if (!el) continue;
    const p = new URLSearchParams({ op: "get", artifact: state.activeAid, path: item.id });
    if (t) p.set("token", t.rw);
    try {
      const full = await api("GET", `/m/${state.currentId}?${p.toString()}`);
      const src = `data:${full.mime};base64,${full.data_base64}`;
      if (item.kind === "image") el.outerHTML = `<img src="${src}">`;
      else if (item.kind === "video") el.outerHTML = `<video src="${src}" controls></video>`;
      else el.outerHTML = `<audio src="${src}" controls></audio>`;
    } catch (e) { /* keep placeholder */ }
  }
}

/* ---- history modal ---- */

async function openHistoryModal(art) {
  const { body } = openModal({ title: `History — ${art.name}`, sub: "Every write, signed by its agent." });
  body.innerHTML = `<div style="color:var(--faint);font-size:13px;">Loading…</div>`;
  const t = tokenStore.get(state.currentId);
  const p = new URLSearchParams({ op: "history", artifact: art.id, limit: 50 });
  if (t) p.set("token", t.rw);
  try {
    const data = await api("GET", `/m/${state.currentId}?${p.toString()}`);
    body.innerHTML = `<div class="ledger">${data.history.map((h) => `
      <div class="ledger-row">
        <div class="ledger-main"><b style="color:var(--accent);">${escapeHtml(h.agent)}</b> · ${escapeHtml(h.summary || h.op)}
          <span class="ledger-sub"> (v${h.old_version}→v${h.new_version})</span></div>
        <div class="ledger-sub">${timeAgo(h.at)}</div>
      </div>`).join("") || `<div style="color:var(--faint);">No history yet.</div>`}</div>`;
  } catch (e) { body.innerHTML = `<div style="color:var(--danger);">${escapeHtml(e.message)}</div>`; }
}

/* ================= share modal ================= */

async function openShareModal() {
  const d = state.current;
  let tokens = tokenStore.get(d.id);
  const { close, body } = openModal({
    title: "Share links",
    sub: "Anyone holding a link can use this metafile — no account needed. The token <i>is</i> the credential.",
  });
  const paint = () => {
    tokens = tokenStore.get(d.id);
    body.innerHTML = tokens ? `
      <div class="link-row"><span class="tag">RW</span><code>${escapeHtml(`${API}/m/${d.id}?token=${tokens.rw}`)}</code>
        <button class="icon-btn" data-copy="rw" title="Copy read-write link">${ICONS.link}</button></div>
      <div class="link-row"><span class="tag ro">RO</span><code>${escapeHtml(`${API}/m/${d.id}?token=${tokens.ro}`)}</code>
        <button class="icon-btn" data-copy="ro" title="Copy read-only link">${ICONS.link}</button></div>
      <p style="font-size:12.5px;color:var(--ink-2);">Read-write links can edit. Read-only links can only fetch. Rotating invalidates all old links instantly.</p>
      <div class="modal-foot" style="margin-top:6px;">
        <button class="btn btn-danger-ghost btn-sm" id="rotateBtn">Rotate links</button>
      </div>` : `
      <p style="font-size:13.5px;color:var(--ink-2);">No links stored in this browser (this file was claimed or opened on another device). Rotate to mint a fresh pair.</p>
      <div class="modal-foot" style="margin-top:6px;">
        <button class="btn btn-primary btn-sm" id="rotateBtn">Mint fresh links</button>
      </div>`;
    body.querySelectorAll("[data-copy]").forEach((b) => {
      b.addEventListener("click", () => {
        const url = `${API}/m/${d.id}?token=${b.dataset.copy === "rw" ? tokens.rw : tokens.ro}`;
        copyText(url);
        toast(`${b.dataset.copy === "rw" ? "Read-write" : "Read-only"} link copied.`);
      });
    });
    body.querySelector("#rotateBtn").addEventListener("click", async () => {
      const ok = await confirmModal({
        title: "Rotate share links?",
        message: "All existing links stop working immediately. Use this if a link leaked.",
        ok: "Rotate links", danger: false,
      });
      if (!ok) return;
      try {
        const r = await api("POST", `/metafiles/${d.id}/rotate`);
        tokenStore.save(d.id, r.rw_token, r.ro_token);
        toast("Fresh links minted.");
        paint();
      } catch (e) { toast(e.message, true); }
    });
  };
  paint();
  void close;
}

/* ================= pay / upgrade ================= */

let payPoll = null;

async function openPayModal() {
  const d = state.current;
  let cfg;
  try {
    cfg = await api("GET", "/billing/config", { auth: false });
  } catch (e) { return toast(e.message, true); }

  if (!cfg.configured) {
    openModal({
      title: "Upgrade to paid",
      sub: "100 MB per metafile, one-time payment.",
      body: `<div class="form-error show">Payments aren't connected on this server yet. Add <span class="mono">PAYSTACK_SECRET_KEY</span> to <span class="mono">backend/.env</span> and restart to accept live card and bank payments.</div>`,
      actions: [{ label: "Close", kind: "primary", onClick: (c) => c() }],
    });
    return;
  }

  const { close, body } = openModal({
    title: "Upgrade to paid",
    sub: "One-time payment · 100 MB caps · all blocks included",
    body: `
      <div class="pay-amount"><div class="big">${escapeHtml(cfg.amount_display)}</div><div class="per">one-time · ${escapeHtml(d.name)}</div></div>
      <div class="pay-channels">
        <div class="chan">${ICONS.card}Card</div>
        <div class="chan">${ICONS.bank}Bank account</div>
        <div class="chan">${ICONS.link}Transfer</div>
      </div>
      <div class="modal-foot" style="margin-top:0;">
        <button class="btn btn-ghost" id="payCancel">Cancel</button>
        <button class="btn btn-primary" id="payGo">Pay with Paystack</button>
      </div>
      <div class="pay-status" id="payStatus">You'll complete payment securely on Paystack, then return here.</div>`,
  });

  const status = (msg, cls = "") => {
    const el = body.querySelector("#payStatus");
    if (el) { el.textContent = msg; el.className = "pay-status " + cls; }
  };
  body.querySelector("#payCancel").addEventListener("click", () => { clearInterval(payPoll); close(); });

  const verifyRef = async (reference) => {
    try {
      const r = await api("POST", `/metafiles/${d.id}/upgrade/verify`, { body: { reference } });
      if (r.tier === "paid") {
        clearInterval(payPoll);
        localStorage.removeItem("mf_pending_pay");
        status("Payment confirmed — welcome to paid.", "ok");
        setTimeout(async () => { close(); await refreshCurrent(); toast("Upgraded to 100 MB."); }, 900);
        return true;
      }
    } catch (e) {
      if (e.status !== 402) { status(e.message, "err"); return true; }
    }
    return false;
  };

  body.querySelector("#payGo").addEventListener("click", async () => {
    status("Creating a secure checkout…");
    try {
      const init = await api("POST", `/metafiles/${d.id}/upgrade/init`);
      localStorage.setItem("mf_pending_pay", JSON.stringify({ ref: init.reference, mid: d.id }));
      window.open(init.authorization_url, "_blank", "noopener");
      status("Checkout open — complete payment, then wait for auto-verify…");
      clearInterval(payPoll);
      payPoll = setInterval(async () => {
        if (!document.body.contains(body)) { clearInterval(payPoll); return; }
        if (await verifyRef(init.reference)) clearInterval(payPoll);
      }, 4000);
    } catch (e) { status(e.message, "err"); }
  });
}

async function checkPaidCallback() {
  const params = new URLSearchParams(window.location.search);
  const ref = params.get("paid");
  if (!ref) return;
  window.history.replaceState({}, "", window.location.pathname);
  let pending = null;
  try { pending = JSON.parse(localStorage.getItem("mf_pending_pay") || "null"); } catch (e) { /* ignore */ }
  if (!pending || pending.ref !== ref) return;
  try {
    const r = await api("POST", `/metafiles/${pending.mid}/upgrade/verify`, { body: { reference: ref } });
    if (r.tier === "paid") {
      localStorage.removeItem("mf_pending_pay");
      await loadDashboard();
      toast("Payment confirmed — upgraded to 100 MB.");
    }
  } catch (e) { /* user can verify from the upgrade modal later */ }
}

/* ================= playgrounds ================= */

async function openSessionsModal(prefillForField = false) {
  let sessions = [];
  try { sessions = await api("GET", "/sessions", { auth: false }); }
  catch (e) { return toast(e.message, true); }

  let fieldAll = prefillForField; // default in field mode: throw ALL blocks in
  const { close, body } = openModal({
    title: prefillForField ? "Send to field" : "Playgrounds",
    sub: prefillForField
      ? "Place blocks from this metafile as live windows. Anyone with the link sees changes as they happen."
      : "Live arrangements of metafile windows. Hand the collaborator link to an AI.",
    wide: true,
    body: `
      ${prefillForField ? `
      <div class="field-mode" id="fieldMode">
        <button data-fmode="all" class="active">All blocks (${state.current.artifacts.length})</button>
        <button data-fmode="one">Active block only</button>
      </div>` : ""}
      <div id="sessList">${sessions.map((s) => `
        <div class="sess-row" data-id="${s.id}">
          <div><b>${escapeHtml(s.name)}</b><span>${s.window_count} windows · v${s.version}</span></div>
          <button class="btn btn-ghost btn-sm" data-open="${s.id}">${prefillForField ? "Place here" : "Open"}</button>
        </div>`).join("") || `<p style="color:var(--faint);font-size:13.5px;">No playgrounds yet — create one below.</p>`}</div>
      <div class="inline-form">
        <input class="text-input" id="newSessName" placeholder="New playground name…">
        <button class="btn btn-primary" id="newSessBtn">Create</button>
      </div>`,
  });

  if (prefillForField) {
    body.querySelectorAll("[data-fmode]").forEach((b) => {
      b.addEventListener("click", () => {
        fieldAll = b.dataset.fmode === "all";
        body.querySelectorAll("[data-fmode]").forEach((x) => x.classList.toggle("active", x === b));
      });
    });
  }

  const openSession = (id) => {
    const s = sessionStore.get(id);
    if (!s) return toast("No local token for this playground.", true);
    window.open(`playground.html?s=${id}&t=${s.owner}`, "_blank", "noopener");
  };

  const placeInto = async (id) => {
    const s = sessionStore.get(id);
    if (!s) return toast("No local token for this playground.", true);
    try {
      const sess = await api("GET", `/session/${id}/${s.owner}?op=fetch`, { auth: false });
      const t = tokenStore.get(state.currentId);
      if (!t) return toast("Mint share links first (Share links).", true);
      const p = new URLSearchParams({
        if_version: sess.version, agent: AGENT,
        metafile_id: state.currentId, m_token: t.rw,
      });
      if (fieldAll) {
        p.set("op", "place_all");
      } else {
        p.set("op", "add_window");
        const art = activeArtifact();
        if (art) p.set("artifact_id", art.id);
      }
      await api("GET", `/session/${id}/${s.owner}?${p.toString()}`, { auth: false });
      close();
      toast(fieldAll ? "All blocks placed in the field." : "Block placed in the field.");
      openSession(id);
    } catch (e) { toast(e.message, true); }
  };

  body.querySelectorAll("[data-open]").forEach((b) => {
    b.addEventListener("click", () => {
      const id = b.dataset.open;
      if (!prefillForField) { close(); openSession(id); return; }
      placeInto(id);
    });
  });

  body.querySelector("#newSessBtn").addEventListener("click", async () => {
    const name = body.querySelector("#newSessName").value.trim() || "Untitled playground";
    try {
      const data = await api("POST", "/sessions", { body: { name, agent: AGENT }, auth: false });
      const owner = data.owner_token || data.owner_url.split("/").pop();
      const collab = data.collaborator_token || data.collaborator_url.split("/").pop();
      sessionStore.save(data.id, owner, collab, data.name);
      if (prefillForField) { close(); await placeInto(data.id); return; }
      close();
      openSession(data.id);
    } catch (e) { toast(e.message, true); }
  });
}

/* ================= wiring ================= */

function copyText(text) {
  if (navigator.clipboard) navigator.clipboard.writeText(text).catch(() => {});
  else {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (e) { /* ignore */ }
    ta.remove();
  }
}

function escapeHtml(s) {
  return (s === undefined || s === null ? "" : String(s)).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function escapeAttr(s) { return escapeHtml(s); }
function fmtBytes(n) {
  n = n || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
function timeAgo(ts) {
  const s = Math.floor(Date.now() / 1000 - (ts || 0));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function wireStatic() {
  document.getElementById("logoutBtn").innerHTML = ICONS.logout;
  document.getElementById("emptyIc").innerHTML = ICONS.folder;
  document.getElementById("backBtn").innerHTML = `${ICONS.back} Dashboard`;
  document.getElementById("deleteFileBtn").innerHTML = ICONS.trash;
  document.getElementById("shareBtn").innerHTML = `${ICONS.link} Share links`;
  document.getElementById("fieldBtn").innerHTML = `Open in field →`;
  document.getElementById("upgradeBtn").innerHTML = `${ICONS.bolt} Upgrade`;
  document.getElementById("newFileBtn").innerHTML = `${ICONS.plus} New metafile`;
  document.getElementById("emptyNewBtn").innerHTML = `${ICONS.plus} Create metafile`;
  document.getElementById("playgroundsBtn").innerHTML = `${ICONS.users} Playgrounds`;
  document.querySelector("#dashSearchWrap").insertAdjacentHTML("afterbegin", ICONS.search);

  const points = [
    ["folder", "Many blocks, one address — memory, sheets, pages, canvas & more"],
    ["pencil", "Every edit signed — optimistic concurrency, no silent overwrites"],
    ["link", "Agents read the guide at /llms.txt, then work through one URL"],
    ["bolt", "Free 5 MB per metafile — upgrade with Paystack anytime"],
  ];
  document.getElementById("authPoints").innerHTML = points
    .map(([ic, tx]) => `<li>${ICONS[ic]}<span>${tx}</span></li>`).join("");

  document.getElementById("tabSignin").addEventListener("click", () => setAuthMode("signin"));
  document.getElementById("tabSignup").addEventListener("click", () => setAuthMode("signup"));
  document.getElementById("authSubmit").addEventListener("click", submitAuth);
  ["authEmail", "authPassword", "authName"].forEach((id) => {
    document.getElementById(id).addEventListener("keydown", (e) => { if (e.key === "Enter") submitAuth(); });
  });
  document.getElementById("logoutBtn").addEventListener("click", () => { showAuth(); toast("Signed out."); });

  document.getElementById("navDash").addEventListener("click", () => { show("dash"); loadDashboard(); });
  document.getElementById("navPlay").addEventListener("click", () => openSessionsModal(false));
  document.getElementById("playgroundsBtn").addEventListener("click", () => openSessionsModal(false));
  document.getElementById("newFileBtn").addEventListener("click", createFileFlow);
  document.getElementById("emptyNewBtn").addEventListener("click", createFileFlow);
  document.getElementById("dashSearch").addEventListener("input", renderDashboard);

  document.getElementById("backBtn").addEventListener("click", async () => { show("dash"); await loadDashboard(); });
  document.getElementById("docTitle").addEventListener("change", async (e) => {
    const name = e.target.value.trim() || "Untitled metafile";
    try {
      await api("PATCH", `/metafiles/${state.currentId}${capQuery(state.currentId)}`, { body: { name } });
      await loadDashboard();
      toast("Renamed.");
    } catch (err) { toast(err.message, true); e.target.value = state.current.name; }
  });
  document.getElementById("deleteFileBtn").addEventListener("click", async () => {
    const d = state.current;
    const ok = await confirmModal({
      title: "Delete metafile?",
      message: `“${escapeHtml(d.name)}” and its ${d.artifacts.length} block(s) will be permanently deleted.`,
      ok: "Delete forever",
    });
    if (!ok) return;
    try {
      await api("DELETE", `/metafiles/${state.currentId}`);
      toast("Deleted.");
      show("dash");
      await loadDashboard();
    } catch (err) { toast(err.message, true); }
  });
  document.getElementById("shareBtn").addEventListener("click", openShareModal);
  document.getElementById("fieldBtn").addEventListener("click", () => openSessionsModal(true));
  document.getElementById("upgradeBtn").addEventListener("click", openPayModal);

  // deferred live refresh: if a change arrived while the user was typing,
  // apply it as soon as they leave the inputs
  const flushPending = () => {
    setTimeout(() => {
      if (live.pending && !isTypingNow()) {
        live.pending = false;
        refreshCurrent();
      }
    }, 150);
  };
  document.getElementById("panel").addEventListener("focusout", flushPending);
  document.getElementById("docTitle").addEventListener("blur", flushPending);
}

/* ================= boot ================= */

wireStatic();
if (Auth.token) {
  bootAfterLogin().catch(() => showAuth());
} else {
  showAuth();
}