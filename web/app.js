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
    case "config": $("subtitle").textContent = (ev.provider || "") + " · " + (ev.model || ""); break;
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
const PANELS = ["skills", "setup", "identity", "soul"];
document.querySelectorAll(".tabs button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    PANELS.forEach((t) => $("panel-" + t).classList.toggle("hidden", t !== b.dataset.tab));
    if (b.dataset.tab === "setup") loadConfig();
  };
});

// ---- setup / model config ------------------------------------------------
// Keys and models are stored PER PROVIDER, so switching providers in the form
// shows that provider's own saved key/model — they never clash.
const DEFAULT_MODELS = {};
let KEYS_PRESENT = {};
let SAVED_MODELS = {};
// A short known-good list per provider so the dropdown is never empty before a
// live refresh. The ⟳ button pulls each provider's full, current catalogue.
const CURATED = {
  anthropic: ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
  openrouter: ["anthropic/claude-sonnet-4.6", "anthropic/claude-opus-4.8", "openai/gpt-4o", "google/gemini-2.5-flash"],
  openai: ["gpt-4o", "gpt-4o-mini", "o3-mini"],
  "ollama-cloud": ["gpt-oss:120b", "qwen3-coder:480b", "deepseek-v3.1:671b"],
  ollama: [],
};
const MODEL_CACHE = {}; // provider -> live-fetched list

async function loadConfig() {
  const c = await api("/api/config");
  Object.assign(DEFAULT_MODELS, c.default_models || {});
  KEYS_PRESENT = c.keys_present || {};
  SAVED_MODELS = c.models || {};
  $("cfgProvider").value = c.provider;
  reflectProvider();
}

function reflectProvider() {
  const p = $("cfgProvider").value;
  const isLocal = p === "ollama";
  const hasKey = !!KEYS_PRESENT[p];
  $("cfgKey").value = "";
  $("cfgKey").disabled = isLocal;
  $("cfgKey").parentElement.style.opacity = isLocal ? ".45" : "1";
  $("cfgKey").placeholder = isLocal ? "not needed for local" :
    (hasKey ? "•••••• (saved for " + p + " — blank keeps it)" : "paste your " + p + " key");
  $("keyState").textContent = isLocal ? "" : (hasKey ? "✓ saved" : "not set");
  $("keyState").className = "setup-note" + (isLocal ? "" : (hasKey ? " ok" : " bad"));
  populateModels(MODEL_CACHE[p] || CURATED[p] || [], SAVED_MODELS[p] || "");
  updateModelHint();
}

function populateModels(list, selected) {
  const sel = $("cfgModel");
  const items = list.slice();
  // keep whatever is already saved/selected even if it's not in the list
  if (selected && !items.includes(selected)) items.unshift(selected);
  sel.innerHTML = "";
  if (!items.length) {
    const o = document.createElement("option");
    o.value = ""; o.textContent = "(default) — tap ⟳ to load models";
    sel.appendChild(o);
  }
  items.forEach((m) => {
    const o = document.createElement("option");
    o.value = m; o.textContent = m;
    if (m === selected) o.selected = true;
    sel.appendChild(o);
  });
}

function updateModelHint() {
  const p = $("cfgProvider").value;
  const d = p === "ollama" ? "your local model" : (DEFAULT_MODELS[p] || "");
  $("modelHint").textContent = d ? "default: " + d : "";
}
$("cfgProvider").onchange = reflectProvider;

$("refreshModels").onclick = async () => {
  const p = $("cfgProvider").value;
  const icon = $("refreshModels"); icon.classList.add("spin");
  const note = $("modelsNote"); note.textContent = "fetching models…"; note.className = "setup-note";
  const r = await api("/api/models?provider=" + encodeURIComponent(p));
  icon.classList.remove("spin");
  if (r.ok && r.models.length) {
    MODEL_CACHE[p] = r.models;
    populateModels(r.models, SAVED_MODELS[p] || $("cfgModel").value);
    note.textContent = r.models.length + " models"; note.className = "setup-note ok";
  } else {
    note.textContent = r.error ? "✗ " + r.error : "no models returned";
    note.className = "setup-note bad";
  }
};

$("cfgSave").onclick = async () => {
  const body = { provider: $("cfgProvider").value, model: $("cfgModel").value.trim() };
  const key = $("cfgKey").value.trim();
  if (key) body.api_key = key;
  const btn = $("cfgSave"); btn.disabled = true; btn.textContent = "Saving…";
  const r = await api("/api/config", "POST", body);
  btn.textContent = "Saved ✓"; setTimeout(() => { btn.textContent = "Save"; btn.disabled = false; }, 1200);
  $("subtitle").textContent = body.provider + " · " + (r.model || "");
  loadConfig();
};

$("cfgTest").onclick = async () => {
  const el = $("testResult"); el.textContent = "testing…"; el.className = "setup-note";
  // save current form first so the test uses it
  const body = { provider: $("cfgProvider").value, model: $("cfgModel").value.trim() };
  const key = $("cfgKey").value.trim(); if (key) body.api_key = key;
  await api("/api/config", "POST", body);
  const r = await api("/api/test_model", "POST", {});
  if (r.ok) { el.textContent = "✓ " + r.model + " replied: " + r.reply; el.className = "setup-note ok"; }
  else { el.textContent = "✗ " + r.error; el.className = "setup-note bad"; }
};

let ollamaModels = [];
$("detectOllama").onclick = async () => {
  const btn = $("detectOllama"); btn.disabled = true; btn.textContent = "Looking…";
  const r = await api("/api/ollama");
  btn.disabled = false; btn.textContent = "Detect Ollama";
  const state = $("ollamaState");
  if (!r.running) {
    state.className = "setup-note bad";
    state.innerHTML = "Ollama isn't running. Install it, then run <code>ollama pull llama3.1</code> and try again.";
    $("ollamaModels").innerHTML = ""; return;
  }
  state.className = "setup-note ok";
  state.textContent = "Ollama is running at " + r.host + " — tap a model to use it:";
  ollamaModels = r.models;
  MODEL_CACHE.ollama = r.models;               // also feed the dropdown
  if ($("cfgProvider").value === "ollama") populateModels(r.models, $("cfgModel").value);
  renderOllamaModels();
};

function renderOllamaModels() {
  const box = $("ollamaModels"); box.innerHTML = "";
  const current = $("cfgProvider").value === "ollama" ? $("cfgModel").value : "";
  ollamaModels.forEach((m) => {
    const b = document.createElement("button");
    b.className = "model-chip" + (m === current ? " active" : "");
    b.textContent = m;
    b.onclick = async () => {
      await api("/api/config", "POST", { provider: "ollama", model: m });
      $("subtitle").textContent = "ollama · " + m;
      await loadConfig();
      renderOllamaModels();
      $("testResult").textContent = "";
    };
    box.appendChild(b);
  });
}
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
    // Deep-link: /#setup opens the model-setup panel straight away.
    const tab = (location.hash || "").replace("#", "");
    if (["setup", "identity", "soul", "skills"].includes(tab)) {
      const btn = document.querySelector(`.tabs button[data-tab="${tab}"]`);
      if (btn) btn.click();
      if (window.innerWidth <= 820) $("app").classList.add("show-skills");
    }
  } catch (e) { /* gate is showing */ }
}
boot();
