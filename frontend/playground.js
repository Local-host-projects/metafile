const API = window.location.origin;
const AGENT = "studio-ui";

const params = new URLSearchParams(window.location.search);
const SID = params.get("s");
const TOKEN = params.get("t");

if (!SID || !TOKEN) {
  document.body.innerHTML = `<div style="padding:60px;text-align:center;color:#55555A;font-family:Inter,sans-serif;">
    Missing playground link. Open a playground from the dashboard, or paste a full
    <code>playground.html?s=...&t=...</code> URL.</div>`;
  throw new Error("no session params");
}

// shares the same localStorage key as app.js, so metafiles created in the
// workspace are addable here without re-entering tokens
const tokenStore = {
  all() { return JSON.parse(localStorage.getItem("metafile_tokens") || "{}"); },
  save(id, rw, ro) {
    const t = this.all(); t[id] = { rw, ro };
    localStorage.setItem("metafile_tokens", JSON.stringify(t));
  },
  get(id) { return this.all()[id] || null; },
};
const sessionStore = {
  all() { return JSON.parse(localStorage.getItem("metafile_sessions") || "{}"); },
  save(id, owner, collab, name) {
    const s = this.all(); s[id] = { owner, collab, name };
    localStorage.setItem("metafile_sessions", JSON.stringify(s));
  },
};

/* ================= live sync (SSE, fetch-stream with reconnect) ================= */

function streamEvents(url, headers, onEvent) {
  const ctrl = new AbortController();
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  (async () => {
    while (!ctrl.signal.aborted) {
      try {
        const res = await fetch(url, { headers, signal: ctrl.signal, cache: "no-store" });
        if (!res.ok || !res.body) { await sleep(2500); continue; }
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
              try { onEvent(JSON.parse(data)); } catch (e) { /* keepalive */ }
            }
          }
        }
      } catch (e) {
        if (ctrl.signal.aborted) return;
      }
      await sleep(2500);
    }
  })();
  return { abort: () => ctrl.abort() };
}

let session = null;   // {id, name, version, layout, role}
let role = "collaborator";
const windowEls = {}; // window_id -> DOM node

// ------------------------------------------------------------- ZUI (zoom + pan)
// The field is an infinite canvas: #pgWorld is translated/scaled inside
// #pgCanvas. Window coordinates are world coordinates; pointer deltas are
// divided by the current zoom when dragging so windows track the cursor.

const view = { x: 60, y: 40, z: 1 };
const Z_MIN = 0.25, Z_MAX = 2.5;

function applyView() {
  const world = document.getElementById("pgWorld");
  if (world) world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.z})`;
  const label = document.getElementById("zoomLabel");
  if (label) label.textContent = Math.round(view.z * 100) + "%";
}

function zoomAt(px, py, factor) {
  const nz = Math.min(Z_MAX, Math.max(Z_MIN, view.z * factor));
  if (nz === view.z) return;
  view.x = px - (px - view.x) * (nz / view.z);
  view.y = py - (py - view.y) * (nz / view.z);
  view.z = nz;
  applyView();
}

function initZUI() {
  const canvas = document.getElementById("pgCanvas");
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = canvas.getBoundingClientRect();
    zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0016));
  }, { passive: false });

  canvas.addEventListener("mousedown", (e) => {
    if (e.target !== canvas && e.target.id !== "pgGrid") return;
    const startX = e.clientX, startY = e.clientY;
    const ox = view.x, oy = view.y;
    canvas.classList.add("panning");
    const onMove = (ev) => {
      view.x = ox + (ev.clientX - startX);
      view.y = oy + (ev.clientY - startY);
      applyView();
    };
    const onUp = () => {
      canvas.classList.remove("panning");
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  });

  document.getElementById("zoomIn").addEventListener("click", () => {
    const r = canvas.getBoundingClientRect();
    zoomAt(r.width / 2, r.height / 2, 1.25);
  });
  document.getElementById("zoomOut").addEventListener("click", () => {
    const r = canvas.getBoundingClientRect();
    zoomAt(r.width / 2, r.height / 2, 0.8);
  });
  document.getElementById("zoomReset").addEventListener("click", () => {
    view.x = 60; view.y = 40; view.z = 1;
    applyView();
  });
  applyView();
}

const TYPE_META = {
  facts: "Memory", spreadsheet: "Spreadsheet", html: "HTML render",
  canvas: "Canvas", calendar: "Calendar", timer: "Timer", media: "Media",
};

// ------------------------------------------------------------------ boot

async function loadSession() {
  const res = await fetch(`${API}/session/${SID}/${TOKEN}?op=fetch`);
  if (!res.ok) {
    document.body.innerHTML = `<div style="padding:60px;text-align:center;color:#55555A;font-family:Inter,sans-serif;">
      Couldn't open this field — the link may be invalid.</div>`;
    return;
  }
  session = await res.json();
  if (session.role) role = session.role; // only present on fetch
  document.getElementById("pgName").value = session.name;
  document.getElementById("pgName").disabled = role !== "owner";
  document.getElementById("addBtn").style.display = "inline-flex";
  if (role !== "owner") document.getElementById("addBtn").textContent = "+ Propose artifact";
  document.getElementById("pgSid").textContent = session.id;
  document.getElementById("pgRole").textContent = role;
  document.getElementById("pgVer").textContent = "v" + String(session.version).padStart(2, "0");
  document.getElementById("pgCount").textContent = session.layout.length;
  renderAllWindows();
  refreshProposalsDot();
  watchSession();
}

/* ---- live session watch: layout + proposal changes appear instantly ---- */

let sessWatch = null;

function watchSession() {
  if (sessWatch) sessWatch.abort();
  sessWatch = streamEvents(`${API}/events/session/${SID}/${TOKEN}`, {}, () => {
    onSessionChanged();
  });
}

async function onSessionChanged() {
  try {
    const res = await fetch(`${API}/session/${SID}/${TOKEN}?op=fetch`);
    if (!res.ok) return;
    session = await res.json();
    document.getElementById("pgName").value = session.name;
    document.getElementById("pgVer").textContent = "v" + String(session.version).padStart(2, "0");
    document.getElementById("pgCount").textContent = session.layout.length;
    renderAllWindows();
    refreshProposalsDot();
  } catch (e) { /* transient */ }
}

/* ---- per-metafile watches: content changes reload their windows ---- */

const mfWatch = {};      // metafile_id -> handle
const mfReloadTimers = {};

function tokenForMf(id) {
  const w = session.layout.find((x) => x.metafile_id === id);
  return w ? w.token : null;
}

function syncMfWatchers() {
  const need = new Set(session.layout.map((w) => w.metafile_id));
  Object.keys(mfWatch).forEach((id) => {
    if (!need.has(id)) { mfWatch[id].abort(); delete mfWatch[id]; }
  });
  need.forEach((id) => {
    if (mfWatch[id]) return;
    const tok = tokenForMf(id);
    if (!tok) return;
    mfWatch[id] = streamEvents(
      `${API}/events/m/${id}?token=${encodeURIComponent(tok)}`, {},
      () => scheduleMfReload(id)
    );
  });
}

function scheduleMfReload(id) {
  clearTimeout(mfReloadTimers[id]);
  mfReloadTimers[id] = setTimeout(() => {
    session.layout.forEach((win) => {
      if (win.metafile_id === id && windowEls[win.window_id]) {
        loadWindowContent(win, windowEls[win.window_id]);
      }
    });
  }, 350);
}

function renderAllWindows() {
  const world = document.getElementById("pgWorld");
  document.getElementById("pgEmpty").style.display = session.layout.length ? "none" : "block";
  const countEl = document.getElementById("pgCount");
  if (countEl) countEl.textContent = session.layout.length;
  const seen = new Set();
  session.layout.forEach(win => {
    seen.add(win.window_id);
    if (windowEls[win.window_id]) {
      positionWindow(windowEls[win.window_id], win);
    } else {
      const el = createWindowEl(win);
      world.appendChild(el);
      windowEls[win.window_id] = el;
      loadWindowContent(win, el);
    }
  });
  Object.keys(windowEls).forEach(id => {
    if (!seen.has(id)) { windowEls[id].remove(); delete windowEls[id]; }
  });
  syncMfWatchers();
}

function positionWindow(el, win) {
  el.style.left = `${win.x}px`;
  el.style.top = `${win.y}px`;
  el.style.width = `${win.w}px`;
  el.style.height = `${win.h}px`;
  el.style.zIndex = win.z || 1;
}

// --------------------------------------------------------------- windows

function createWindowEl(win) {
  const el = document.createElement("div");
  el.className = "pg-window";
  positionWindow(el, win);
  el.innerHTML = `
    <div class="pg-window-bar">
      <span class="pg-window-title">Loading…</span>
      ${role === "owner" ? '<button class="pg-window-close">×</button>' : ""}
    </div>
    <div class="pg-window-body">…</div>
    ${role === "owner" ? '<div class="pg-resize-handle"></div>' : ""}
  `;

  if (role === "owner") {
    makeDraggable(el, win);
    makeResizable(el, win);
    el.querySelector(".pg-window-close").addEventListener("click", async (e) => {
      e.stopPropagation();
      await sessionOp("remove_window", { window_id: win.window_id });
    });
  }
  return el;
}

function makeDraggable(el, win) {
  const bar = el.querySelector(".pg-window-bar");
  bar.addEventListener("mousedown", (e) => {
    if (e.target.closest(".pg-window-close")) return;
    e.preventDefault();
    const startX = e.clientX, startY = e.clientY;
    const origX = win.x, origY = win.y;
    el.classList.add("dragging");
    const onMove = (ev) => {
      win.x = origX + (ev.clientX - startX) / view.z;
      win.y = origY + (ev.clientY - startY) / view.z;
      positionWindow(el, win);
    };
    const onUp = async () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      el.classList.remove("dragging");
      await sessionOp("move_resize", { window_id: win.window_id, x: win.x, y: win.y });
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  });
}

function makeResizable(el, win) {
  const handle = el.querySelector(".pg-resize-handle");
  handle.addEventListener("mousedown", (e) => {
    e.preventDefault(); e.stopPropagation();
    const startX = e.clientX, startY = e.clientY;
    const origW = win.w, origH = win.h;
    el.classList.add("resizing");
    const onMove = (ev) => {
      win.w = Math.max(240, origW + (ev.clientX - startX) / view.z);
      win.h = Math.max(160, origH + (ev.clientY - startY) / view.z);
      positionWindow(el, win);
    };
    const onUp = async () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      el.classList.remove("resizing");
      await sessionOp("move_resize", { window_id: win.window_id, w: win.w, h: win.h });
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  });
}

async function sessionOp(op, extra) {
  const p = new URLSearchParams({ op, if_version: session.version, agent: AGENT, ...extra });
  const res = await fetch(`${API}/session/${SID}/${TOKEN}?${p.toString()}`);
  if (res.status === 409) {
    toast("Playground changed elsewhere — refreshing.");
    await loadSession();
    return null;
  }
  if (!res.ok) { toast("Action failed."); return null; }
  session = await res.json();
  const verEl = document.getElementById("pgVer");
  if (verEl) verEl.textContent = "v" + String(session.version).padStart(2, "0");
  renderAllWindows();
  return session;
}

// ------------------------------------------------------- window content

function pickArtifact(data, win) {
  const arr = data.artifacts || [];
  return arr.find((a) => a.id === win.artifact_id) || arr[0] || null;
}

async function loadWindowContent(win, el) {
  const titleEl = el.querySelector(".pg-window-title");
  const bodyEl = el.querySelector(".pg-window-body");
  const res = await fetch(`${API}/m/${win.metafile_id}/${win.token}?op=fetch`);
  if (!res.ok) { bodyEl.textContent = "Couldn't load this metafile."; return; }
  const data = await res.json();
  const art = pickArtifact(data, win);
  if (!art) {
    titleEl.textContent = data.name;
    bodyEl.textContent = "This metafile has no blocks yet.";
    return;
  }
  titleEl.textContent = `${data.name} · ${art.name}`;
  const ctx = {
    api: API, id: win.metafile_id, token: win.token, artifact: art.id,
    refetch: () => loadWindowContent(win, el),
  };
  const renderer = {
    facts: renderFactsMini, spreadsheet: renderSheetMini, html: renderHtmlMini,
    canvas: renderCanvasMini, calendar: renderCalendarMini, timer: renderTimerMini, media: renderMediaMini,
  }[art.type];
  if (renderer) renderer(bodyEl, art, ctx);
  else bodyEl.textContent = "Unsupported block type.";
}

async function currentArtifact(ctx) {
  const cur = await (await fetch(`${API}/m/${ctx.id}/${ctx.token}?op=fetch`)).json();
  const arr = cur.artifacts || [];
  return arr.find((a) => a.id === ctx.artifact) || arr[0] || null;
}

async function miniMutate(ctx, op, path, value) {
  const art = await currentArtifact(ctx);
  if (!art) { toast("No blocks in this metafile."); return null; }
  const p = new URLSearchParams({ op, agent: AGENT, if_version: art.version, artifact: art.id });
  if (path != null) p.set("path", path);
  if (value != null) p.set("value", value);
  const res = await fetch(`${API}/m/${ctx.id}/${ctx.token}?${p.toString()}`);
  if (res.status === 409) { toast("Changed elsewhere — refreshed."); ctx.refetch(); return null; }
  if (!res.ok) { toast("Edit failed."); return null; }
  return res.json();
}

async function miniBulk(ctx, op, value) {
  const art = await currentArtifact(ctx);
  if (!art) { toast("No blocks in this metafile."); return null; }
  const res = await fetch(`${API}/m/${ctx.id}/bulk?token=${ctx.token}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ op, artifact: art.id, value, if_version: art.version, agent: AGENT }),
  });
  if (res.status === 409) { toast("Changed elsewhere — refreshed."); ctx.refetch(); return null; }
  if (!res.ok) { toast("Edit failed."); return null; }
  return res.json();
}

function renderFactsMini(body, art, ctx) {
  const facts = art.content.facts || [];
  body.innerHTML = `
    ${facts.map(f => `<div class="pg-mini-row"><span style="flex:1;">${escapeHtml(f.text)}</span></div>`).join("") || `<div style="color:var(--text-faint);">No facts yet.</div>`}
    <div class="pg-mini-add"><input id="mf-${ctx.id}" placeholder="Add a fact..."><button id="mfb-${ctx.id}">+</button></div>
  `;
  body.querySelector(`#mfb-${ctx.id}`).addEventListener("click", async () => {
    const input = body.querySelector(`#mf-${ctx.id}`);
    if (!input.value.trim()) return;
    await miniMutate(ctx, "append", null, input.value.trim());
    ctx.refetch();
  });
}

function renderSheetMini(body, art, ctx) {
  const cells = art.content.cells || {};
  const evaluated = (art.computed && art.computed.evaluated) || {};
  const cols = 6, rows = 10;
  const colLetter = i => String.fromCharCode(65 + i);
  let html = '<table class="sheet" style="font-size:11px;"><tr><th></th>' +
    Array.from({ length: cols }, (_, c) => `<th>${colLetter(c)}</th>`).join("") + "</tr>";
  for (let r = 0; r < rows; r++) {
    html += `<tr><td class="row-head">${r + 1}</td>`;
    for (let c = 0; c < cols; c++) {
      const ref = `${colLetter(c)}${r + 1}`;
      const val = evaluated[ref] !== undefined ? evaluated[ref] : "";
      html += `<td><input data-ref="${ref}" value="${escapeHtml(String(val))}" style="font-size:11px;padding:4px 6px;"></td>`;
    }
    html += "</tr>";
  }
  html += "</table>";
  body.innerHTML = `<div class="sheet-wrap">${html}</div>`;
  body.querySelectorAll("input[data-ref]").forEach(input => {
    const ref = input.dataset.ref;
    input.addEventListener("focus", () => { const c = cells[ref]; input.value = c ? (c.formula || c.value || "") : ""; });
    input.addEventListener("blur", async () => {
      await miniMutate(ctx, input.value === "" ? "delete" : "set", ref, input.value || null);
      ctx.refetch();
    });
  });
}

function renderHtmlMini(body, art, ctx) {
  const html = art.content.html || "";
  body.innerHTML = `
    <div style="display:flex;gap:6px;margin-bottom:8px;">
      <button class="timer-btn" data-mode="preview">Preview</button>
      <button class="timer-btn" data-mode="edit">Edit</button>
    </div>
    <div id="htmlMiniHost" style="height:calc(100% - 36px);"></div>
  `;
  const host = body.querySelector("#htmlMiniHost");
  const showPreview = () => { host.innerHTML = `<iframe sandbox="allow-scripts" style="width:100%;height:100%;border:1px solid var(--border);border-radius:8px;background:white;" srcdoc="${escapeHtml(html)}"></iframe>`; };
  const showEdit = () => {
    host.innerHTML = `<textarea style="width:100%;height:calc(100% - 34px);background:var(--surface-raised);border:1px solid var(--border);border-radius:8px;color:var(--text);font-family:monospace;font-size:11px;padding:8px;">${escapeHtml(html)}</textarea><button class="timer-btn" id="miniSave" style="margin-top:6px;">Save</button>`;
    host.querySelector("#miniSave").addEventListener("click", async () => {
      await miniBulk(ctx, "set", { html: host.querySelector("textarea").value });
      ctx.refetch();
    });
  };
  body.querySelector('[data-mode="preview"]').addEventListener("click", showPreview);
  body.querySelector('[data-mode="edit"]').addEventListener("click", showEdit);
  showPreview();
}

function renderCanvasMini(body, art, ctx) {
  const c = art.content;
  body.innerHTML = `<canvas width="${Math.min(c.width || 800, 500)}" height="${Math.min(c.height || 600, 300)}" style="background:white;border-radius:8px;cursor:crosshair;width:100%;height:auto;"></canvas>`;
  const canvas = body.querySelector("canvas");
  const cx = canvas.getContext("2d");
  const scaleX = canvas.width / (c.width || 800), scaleY = canvas.height / (c.height || 600);
  (c.strokes || []).forEach(s => {
    if (!s.points || s.points.length < 2) return;
    cx.strokeStyle = s.color || "#000"; cx.lineWidth = 2; cx.lineCap = "round";
    cx.beginPath();
    cx.moveTo(s.points[0][0] * scaleX, s.points[0][1] * scaleY);
    s.points.forEach(p => cx.lineTo(p[0] * scaleX, p[1] * scaleY));
    cx.stroke();
  });
  let drawing = false, points = [];
  const pos = e => { const r = canvas.getBoundingClientRect(); return [(e.clientX - r.left) / scaleX, (e.clientY - r.top) / scaleY]; };
  canvas.addEventListener("mousedown", e => { drawing = true; points = [pos(e)]; });
  canvas.addEventListener("mousemove", e => {
    if (!drawing) return;
    const p = pos(e); points.push(p);
    cx.strokeStyle = "#1D1D1F"; cx.lineWidth = 2; cx.lineCap = "round";
    cx.beginPath(); cx.moveTo(points[points.length - 2][0] * scaleX, points[points.length - 2][1] * scaleY);
    cx.lineTo(p[0] * scaleX, p[1] * scaleY); cx.stroke();
  });
  window.addEventListener("mouseup", async () => {
    if (!drawing) return;
    drawing = false;
    if (points.length > 1) { await miniBulk(ctx, "append", { tool: "pen", color: "#1D1D1F", points }); }
  });
}

function renderCalendarMini(body, art, ctx) {
  const events = art.content.events || [];
  body.innerHTML = events.map(e => `<div class="pg-mini-row"><span style="color:var(--gold);font-size:11px;width:70px;">${e.start ? new Date(e.start).toLocaleDateString(undefined,{month:"short",day:"numeric"}) : ""}</span><span>${escapeHtml(e.title)}</span></div>`).join("")
    || `<div style="color:var(--text-faint);">No events.</div>`;
}

function renderTimerMini(body, art, ctx) {
  const timers = art.content.timers || [];
  body.innerHTML = timers.map(t => {
    const m = Math.floor(t.remaining_seconds / 60), s = Math.floor(t.remaining_seconds % 60);
    return `<div class="pg-mini-row"><span style="font-family:monospace;color:var(--pink);width:50px;">${m}:${String(s).padStart(2,"0")}</span><span style="flex:1;">${escapeHtml(t.label)}</span>
      <button class="timer-btn" data-id="${t.id}" data-action="${t.status === "running" ? "pause" : "start"}">${t.status === "running" ? "Pause" : "Start"}</button></div>`;
  }).join("") || `<div style="color:var(--text-faint);">No timers.</div>`;
  body.querySelectorAll("[data-action]").forEach(btn => {
    btn.addEventListener("click", async () => { await miniMutate(ctx, "set", btn.dataset.id, btn.dataset.action); ctx.refetch(); });
  });
  if (timers.some(t => t.status === "running")) setTimeout(() => ctx.refetch(), 1000);
}

function renderMediaMini(body, art, ctx) {
  const items = art.content.items || [];
  body.innerHTML = `<div class="media-grid">${items.slice(0, 6).map(i => `<div class="media-item" data-id="${i.id}"><div class="media-slot" style="height:70px;display:flex;align-items:center;justify-content:center;color:var(--text-faint);font-size:10px;">…</div></div>`).join("") || `<div style="color:var(--text-faint);">No media.</div>`}</div>`;
  items.slice(0, 6).forEach(async item => {
    const res = await fetch(`${API}/m/${ctx.id}/${ctx.token}?op=get&artifact=${ctx.artifact}&path=${item.id}`);
    const full = await res.json();
    const slot = body.querySelector(`.media-item[data-id="${item.id}"] .media-slot`);
    if (!slot) return;
    const src = `data:${full.mime};base64,${full.data_base64}`;
    if (item.kind === "image") slot.outerHTML = `<img src="${src}" style="width:100%;height:70px;object-fit:cover;">`;
  });
}

// --------------------------------------------------------- add artifact

document.getElementById("addBtn").addEventListener("click", () => {
  if (role === "owner") openAddModal(); else openProposeModal();
});

async function createBlockIn(metafileId, type, name) {
  const tokens = tokenStore.get(metafileId);
  if (!tokens) { toast("No write link stored for that metafile."); return null; }
  const curRes = await fetch(`${API}/m/${metafileId}/${tokens.rw}?op=fetch`);
  if (!curRes.ok) { toast("Couldn't open that metafile."); return null; }
  const cur = await curRes.json();
  const res = await fetch(`${API}/metafiles/${metafileId}/artifacts?token=${tokens.rw}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ artifact_type: type, name: name || undefined, agent: AGENT, if_version: cur.version }),
  });
  if (res.status === 409) { toast("Metafile changed — try again."); return null; }
  if (!res.ok) { toast("Couldn't add that block."); return null; }
  return res.json();
}

function openAddModal() {
  const known = Object.entries(tokenStore.all());
  const backdrop = document.createElement("div");
  backdrop.className = "pg-modal-backdrop";
  backdrop.innerHTML = `
    <div class="pg-modal">
      <div class="eyebrow-label">Place — owner only</div>
      <h3>Add a block</h3>
      <div id="pgStepPick">
        <div class="eyebrow-label" style="margin:12px 0 4px;">1 · Pick a metafile</div>
        <div id="pgMfList">
          ${known.length ? known.map(([id]) => `<button class="pg-pick" data-mf="${id}"><span class="mono" style="font-size:11px;">${escapeHtml(id)}</span></button>`).join("") : `<div style="color:var(--text-faint);font-size:13px;">No metafiles with local write links yet — create one in Studio first.</div>`}
        </div>
        <a class="pg-pick" href="index.html" style="text-decoration:none;color:inherit;display:block;">+ New metafile in Studio →</a>
      </div>
      <div id="pgStepType" style="display:none;">
        <div class="eyebrow-label" style="margin:12px 0 4px;">2 · Name + type</div>
        <input class="pg-field" id="pgBlockName" placeholder="Block name…" autocomplete="off">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:4px;">
          ${Object.keys(TYPE_META).map(t => `<button class="pg-btn" data-create="${t}">${TYPE_META[t]}</button>`).join("")}
        </div>
        <button class="pg-btn" id="pgBackBtn" style="width:100%;margin-top:10px;">← Back</button>
      </div>
      <button class="pg-btn" id="closeModal" style="width:100%;margin-top:14px;">Cancel</button>
    </div>`;
  document.body.appendChild(backdrop);
  backdrop.querySelector("#closeModal").addEventListener("click", () => backdrop.remove());
  let targetMf = null;
  backdrop.querySelectorAll("[data-mf]").forEach(btn => {
    btn.addEventListener("click", () => {
      targetMf = btn.dataset.mf;
      backdrop.querySelector("#pgStepPick").style.display = "none";
      backdrop.querySelector("#pgStepType").style.display = "block";
      setTimeout(() => backdrop.querySelector("#pgBlockName").focus(), 60);
    });
  });
  backdrop.querySelector("#pgBackBtn").addEventListener("click", () => {
    backdrop.querySelector("#pgStepType").style.display = "none";
    backdrop.querySelector("#pgStepPick").style.display = "block";
  });
  backdrop.querySelectorAll("[data-create]").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!targetMf) return;
      const name = backdrop.querySelector("#pgBlockName").value.trim();
      const tokens = tokenStore.get(targetMf);
      const made = await createBlockIn(targetMf, btn.dataset.create, name);
      if (made) await sessionOp("add_window", { metafile_id: targetMf, m_token: tokens.rw, artifact_id: made.artifact.id });
      backdrop.remove();
    });
  });
}

function openProposeModal() {
  const backdrop = document.createElement("div");
  backdrop.className = "pg-modal-backdrop";
  backdrop.innerHTML = `
    <div class="pg-modal">
      <div class="eyebrow-label">Signal — needs owner approval</div>
      <h3>Propose an artifact</h3>
      <p style="color:var(--text-faint);font-size:13px;margin-top:-8px;">The session owner will need to approve this before it's created.</p>
      <input id="propName" placeholder="Name" style="width:100%;margin-bottom:8px;padding:10px;background:var(--surface-raised);border:1px solid var(--border);border-radius:8px;color:var(--text);">
      <select id="propType" style="width:100%;margin-bottom:8px;padding:10px;background:var(--surface-raised);border:1px solid var(--border);border-radius:8px;color:var(--text);">
        ${Object.keys(TYPE_META).map(t => `<option value="${t}">${TYPE_META[t]}</option>`).join("")}
      </select>
      <input id="propReason" placeholder="Why? (optional)" style="width:100%;margin-bottom:14px;padding:10px;background:var(--surface-raised);border:1px solid var(--border);border-radius:8px;color:var(--text);">
      <button class="pg-btn primary" id="submitProp" style="width:100%;">Submit proposal</button>
      <button class="pg-btn" id="closeModal" style="width:100%;margin-top:8px;">Cancel</button>
    </div>`;
  document.body.appendChild(backdrop);
  backdrop.querySelector("#closeModal").addEventListener("click", () => backdrop.remove());
  backdrop.querySelector("#submitProp").addEventListener("click", async () => {
    const name = backdrop.querySelector("#propName").value.trim() || "Untitled";
    const artifact_type = backdrop.querySelector("#propType").value;
    const reason = backdrop.querySelector("#propReason").value.trim();
    const p = new URLSearchParams({ name, artifact_type, agent: AGENT, reason });
    await fetch(`${API}/session/${SID}/${TOKEN}/propose?${p.toString()}`, { method: "POST" });
    toast("Proposed — waiting for approval.");
    backdrop.remove();
  });
}

// ----------------------------------------------------------- proposals

async function refreshProposalsDot() {
  if (role !== "owner") { document.getElementById("proposalsDot").style.display = "none"; return; }
  const res = await fetch(`${API}/session/${SID}/${TOKEN}?op=list_proposals&status=pending`);
  const data = await res.json();
  const dot = document.getElementById("proposalsDot");
  if (data.proposals.length > 0) { dot.className = "pg-proposals-dot"; } else { dot.style.display = "none"; }
}

document.getElementById("proposalsBtn").addEventListener("click", async () => {
  const res = await fetch(`${API}/session/${SID}/${TOKEN}?op=list_proposals&status=pending`);
  const data = await res.json();
  const backdrop = document.createElement("div");
  backdrop.className = "pg-modal-backdrop";
  backdrop.innerHTML = `<div class="pg-modal"><h3>Pending proposals</h3>
    <div id="propList">${data.proposals.map(p => `
      <div class="pg-proposal-card" data-id="${p.id}">
        <div class="agent">${escapeHtml(p.agent)}</div>
        <div class="name">${escapeHtml(p.name)} <span style="color:var(--text-faint);font-weight:400;">(${TYPE_META[p.artifact_type] || p.artifact_type})</span></div>
        ${p.reason ? `<div class="reason">${escapeHtml(p.reason)}</div>` : ""}
        ${role === "owner" ? `<div class="pg-proposal-actions"><button class="pg-approve" data-decide="approve">Approve</button><button class="pg-reject" data-decide="reject">Reject</button></div>` : ""}
      </div>`).join("") || `<div style="color:var(--text-faint);">No pending proposals.</div>`}
    </div>
    <button class="pg-btn" id="closeModal" style="width:100%;margin-top:14px;">Close</button>
  </div>`;
  document.body.appendChild(backdrop);
  backdrop.querySelector("#closeModal").addEventListener("click", () => backdrop.remove());
  backdrop.querySelectorAll("[data-decide]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".pg-proposal-card");
      const pid = card.dataset.id;
      const op = btn.dataset.decide === "approve" ? "approve_proposal" : "reject_proposal";
      await sessionOp(op, { proposal_id: pid });
      card.remove();
      refreshProposalsDot();
    });
  });
});

document.getElementById("backBtn").addEventListener("click", () => { window.location.href = "index.html"; });

document.getElementById("pgName").addEventListener("change", async (e) => {
  if (role !== "owner") return;
  await sessionOp("rename", { value: e.target.value.trim() || "Untitled playground" });
  const s = JSON.parse(localStorage.getItem("metafile_sessions") || "{}");
  if (s[SID]) { s[SID].name = session.name; localStorage.setItem("metafile_sessions", JSON.stringify(s)); }
});

// --------------------------------------------------------------- utils

function tickClock() {
  const el = document.getElementById("pgClock");
  if (el) el.textContent = new Date().toISOString().slice(11, 19) + " UTC";
}
tickClock();
setInterval(tickClock, 1000);

initZUI();
loadSession();

function escapeHtml(s) { return (s || "").toString().replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}
