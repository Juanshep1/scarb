// SCARB web client — chat, live skill panel, and identity/soul editors, all
// driven by a Server-Sent Events stream so you watch SCARB think and grow in
// real time.
"use strict";

const $ = (id) => document.getElementById(id);
let TOKEN = localStorage.getItem("scarb_token") || "";
let evtSource = null;

function headers() {
  const h = { "Content-Type": "application/json" };
  if (TOKEN) h["X-Scarb-Token"] = TOKEN;
  return h;
}

async function api(path, method = "GET", body) {
  const res = await fetch(path, { method, headers: headers(),
    body: body ? JSON.stringify(body) : undefined });
  if (res.status === 401) { showGate(); throw new Error("unauthorized"); }
  return res.json();
}

// ---- token gate ----------------------------------------------------------
function showGate() { $("gate").hidden = false; }
$("tokenGo").onclick = () => {
  TOKEN = $("tokenInput").value.trim();
  localStorage.setItem("scarb_token", TOKEN);
  $("gate").hidden = true;
  boot();
};
$("tokenInput").addEventListener("keydown", (e) => { if (e.key === "Enter") $("tokenGo").click(); });

// ---- chat stream ---------------------------------------------------------
const stream = $("stream");
function clearEmpty() { const e = $("empty"); if (e) e.remove(); }
function atBottom() { return stream.scrollHeight - stream.scrollTop - stream.clientHeight < 120; }
function scroll() { stream.scrollTop = stream.scrollHeight; }

function addUser(text) {
  clearEmpty();
  const d = document.createElement("div");
  d.className = "msg user";
  d.textContent = text;
  stream.appendChild(d); scroll();
}

function addScarb(text) {
  clearEmpty();
  const d = document.createElement("div");
  d.className = "msg scarb";
  const who = document.createElement("div"); who.className = "who"; who.textContent = "SCARB";
  const body = document.createElement("div"); body.textContent = text;
  d.appendChild(who); d.appendChild(body);
  stream.appendChild(d); if (atBottom()) scroll();
}

function addStep(cls, kind, main, detail) {
  clearEmpty();
  const wasBottom = atBottom();
  const d = document.createElement("div");
  d.className = "step " + cls;
  const k = document.createElement("span"); k.className = "k"; k.textContent = kind;
  d.appendChild(k);
  const span = document.createElement("span"); span.innerHTML = main; d.appendChild(span);
  if (detail) { const pre = document.createElement("pre"); pre.textContent = detail; d.appendChild(pre); }
  stream.appendChild(d); if (wasBottom) scroll();
}

function esc(s) { const t = document.createElement("span"); t.textContent = s; return t.innerHTML; }

// ---- SSE event handling --------------------------------------------------
function connect() {
  if (evtSource) evtSource.close();
  const url = "/events" + (TOKEN ? "?token=" + encodeURIComponent(TOKEN) : "");
  evtSource = new EventSource(url);
  evtSource.onmessage = (e) => {
    let ev; try { ev = JSON.parse(e.data); } catch { return; }
    handle(ev);
  };
  evtSource.onerror = () => { setStatus("reconnecting…", false); };
}

const seen = new Set();
function handle(ev) {
  const id = ev.kind + ":" + ev.t;
  if (seen.has(id)) return; seen.add(id);
  switch (ev.kind) {
    case "user": /* echoed locally already */ break;
    case "thought": addStep("thought", "reasoning", esc(ev.text)); break;
    case "action":
      addStep("action", "tool", "<span class='tool'>" + esc(ev.tool) + "</span> " +
        esc(JSON.stringify(ev.args || {}).slice(0, 200))); break;
    case "result":
      addStep("result" + (ev.ok ? "" : " bad"), ev.ok ? "result" : "failed",
        esc(ev.tool), typeof ev.result === "string" ? ev.result : JSON.stringify(ev.result)); break;
    case "assistant": addScarb(ev.text); break;
    case "error": addStep("error", "error", esc(ev.text)); break;
    case "status":
      setStatus(ev.text, ev.text !== "idle");
      if (ev.model) $("subtitle").textContent = (ev.where || "") + " · " + ev.model;
      break;
    case "skill": onSkillEvent(ev); break;
    case "doc": refreshDocs(); break;
    case "reset": stream.innerHTML = ""; break;
    case "log": break;
  }
}

function setStatus(text, busy) {
  $("statusText").textContent = text;
  $("statusBadge").classList.toggle("busy", !!busy);
  $("send").disabled = !!busy && text !== "reconnecting…";
}

// ---- skills panel --------------------------------------------------------
const CORE = new Set(); // core tools aren't in the skills list; skills only
let skills = [];
function renderSkills(flashName) {
  $("skillCount").textContent = skills.length + " skill" + (skills.length === 1 ? "" : "s");
  const list = $("skillList"); list.innerHTML = "";
  skills.forEach((s) => {
    const d = document.createElement("div");
    d.className = "skill" + (s.name === flashName ? " flash" : "");
    const name = document.createElement("div"); name.className = "name";
    name.textContent = s.name;
    const desc = document.createElement("div"); desc.className = "desc"; desc.textContent = s.description;
    d.appendChild(name); d.appendChild(desc);
    list.appendChild(d);
  });
}

async function onSkillEvent(ev) {
  const state = await api("/api/state");
  skills = state.skills;
  renderSkills(ev.skill && ev.skill.name);
  if (ev.action === "saved") {
    // little live toast in the chat too
    addStep("result", "skill " + ev.action, "🪲 <b style='color:var(--gold)'>" + esc(ev.skill.name) + "</b> — " + esc(ev.skill.description || ""));
    showSide();
  }
}

// ---- docs (identity / soul) ---------------------------------------------
async function refreshDocs() {
  const state = await api("/api/state");
  $("identityEdit").value = state.identity || "";
  $("soulEdit").value = state.soul || "";
  skills = state.skills; renderSkills();
  $("subtitle").textContent = (state.provider || "") + " · " + (state.model || "");
}

document.querySelectorAll(".doc-save").forEach((b) => {
  b.onclick = async () => {
    const name = b.dataset.doc;
    const content = (name === "identity.md" ? $("identityEdit") : $("soulEdit")).value;
    await api("/api/save_doc", "POST", { name, content });
    b.textContent = "Saved ✓"; setTimeout(() => b.textContent = "Save " + name.replace(".md", ""), 1200);
  };
});

// ---- tabs ----------------------------------------------------------------
document.querySelectorAll(".tabs button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    ["skills", "identity", "soul"].forEach((t) =>
      $("panel-" + t).classList.toggle("hidden", t !== b.dataset.tab));
  };
});
document.querySelectorAll(".mobtabs button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll(".mobtabs button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("app").classList.toggle("show-skills", b.dataset.mob === "skills");
  };
});
function showSide() {
  if (window.innerWidth <= 820) { /* leave user where they are */ }
}

// ---- composer ------------------------------------------------------------
const input = $("input");
input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = input.scrollHeight + "px"; });
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
$("send").onclick = send;
async function send() {
  const text = input.value.trim();
  if (!text) return;
  input.value = ""; input.style.height = "auto";
  addUser(text);
  try {
    await api("/api/send", "POST", { message: text, local: $("localToggle").checked });
  } catch (e) { addStep("error", "error", "could not reach SCARB: " + esc(e.message)); }
}
document.querySelectorAll("#chips .chip").forEach((c) => {
  c.onclick = () => { input.value = c.textContent; send(); };
});

// ---- boot ----------------------------------------------------------------
async function boot() {
  // Ask (without auth) whether a token is even needed; only gate if it is.
  try {
    const ping = await (await fetch("/api/ping")).json();
    if (ping.needs_token && !TOKEN) { showGate(); return; }
  } catch (e) { /* server unreachable; fall through to try state */ }
  try {
    const state = await api("/api/state");
    skills = state.skills; renderSkills();
    $("identityEdit").value = state.identity || "";
    $("soulEdit").value = state.soul || "";
    $("subtitle").textContent = (state.provider || "") + " · " + (state.model || "");
    (state.history || []).forEach((m) => m.role === "user" ? addUser(m.content) : addScarb(m.content));
    connect();
  } catch (e) { /* gate is showing */ }
}
boot();
