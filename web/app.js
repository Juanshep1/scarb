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

// Strip leftover markdown so replies read as clean text (no *, #, backticks).
function cleanMarkdown(t) {
  return (t || "")
    .replace(/```(\w+)?\n?/g, "").replace(/```/g, "")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*/g, "").replace(/\*/g, "")
    .replace(/^\s{0,3}#{1,6}\s*/gm, "")
    .replace(/^\s*[-•]\s+/gm, "— ")
    .trim();
}

function addScarb(text) {
  clearEmpty();
  const d = document.createElement("div");
  d.className = "msg scarb";
  const who = document.createElement("div"); who.className = "who"; who.textContent = "SCARB";
  const body = document.createElement("div"); body.textContent = cleanMarkdown(text);
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

// live screenshot in the chat, so you see exactly what SCARB is looking at
function addShot(url) {
  clearEmpty();
  const full = url + (TOKEN ? "&token=" + encodeURIComponent(TOKEN) : "");
  const wrap = document.createElement("div");
  wrap.className = "shot";
  const img = document.createElement("img");
  img.src = full;
  img.alt = "SCARB's view of the screen";
  img.onclick = () => openViewer(full, "Screenshot");   // tap to see it up close
  wrap.appendChild(img);
  stream.appendChild(wrap);
  if (atBottom()) scroll();
}

// ---- full-screen viewer + live desktop view ------------------------------
let liveTimer = null;
function openViewer(src, title) {
  stopLive();
  $("viewerTitle").textContent = title || "Screenshot";
  $("viewerLive").hidden = true;
  $("viewerImg").src = src;
  $("viewerStage").classList.remove("zoomed");
  $("viewer").hidden = false;
}
function openLive() {
  $("viewerTitle").textContent = "Your Mac";
  $("viewerLive").hidden = false;
  $("viewerStage").classList.remove("zoomed");
  $("viewer").hidden = false;
  const tick = () => {
    $("viewerImg").src = "/api/live?t=" + Date.now() + (TOKEN ? "&token=" + encodeURIComponent(TOKEN) : "");
  };
  tick();
  liveTimer = setInterval(tick, 1600);   // refresh ~every 1.6s
}
function stopLive() { if (liveTimer) { clearInterval(liveTimer); liveTimer = null; } }
function closeViewer() { stopLive(); $("viewer").hidden = true; $("viewerImg").src = ""; }
$("liveBtn").onclick = openLive;
$("viewerClose").onclick = closeViewer;
$("viewerZoom").onclick = () => $("viewerStage").classList.toggle("zoomed");
$("viewerImg").onclick = () => $("viewerStage").classList.toggle("zoomed");

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
let BOOT_T = 0;   // set at boot; events older than this were already rendered from saved history
function handle(ev) {
  const id = ev.kind + ":" + ev.t;
  if (seen.has(id)) return; seen.add(id);
  // The event stream replays recent events on connect. The saved conversation
  // is already on screen, so drop stale chat/step replays to avoid duplicates.
  if (ev.t && BOOT_T && ev.t < BOOT_T - 0.5 &&
      ["user", "assistant", "thought", "action", "result", "error"].includes(ev.kind)) {
    return;
  }
  switch (ev.kind) {
    case "user": /* echoed locally already */ break;
    case "thought": addStep("thought", "reasoning", esc(ev.text)); break;
    case "action":
      addStep("action", "tool", "<span class='tool'>" + esc(ev.tool) + "</span> " +
        esc(JSON.stringify(ev.args || {}).slice(0, 200))); break;
    case "result":
      addStep("result" + (ev.ok ? "" : " bad"), ev.ok ? "result" : "failed",
        esc(ev.tool), typeof ev.result === "string" ? ev.result : JSON.stringify(ev.result)); break;
    case "assistant": addScarb(ev.text); speak(ev.text, onReplyDone); break;
    case "screenshot": addShot(ev.url); break;
    case "error": addStep("error", "error", esc(ev.text)); break;
    case "status":
      setStatus(ev.text, ev.text !== "idle");
      if (ev.model) $("subtitle").textContent = (ev.where || "") + " · " + ev.model;
      break;
    case "skill": onSkillEvent(ev); break;
    case "molt_start": $("moltBanner").classList.add("show"); document.body.classList.add("molting"); break;
    case "molt": addEvolve(ev); break;
    case "molt_done":
      $("moltBanner").classList.remove("show"); document.body.classList.remove("molting");
      onSkillEvent({ action: "saved" });   // refresh skills panel
      if (ev.ok === false && ev.text) addStep("error", "molt", esc(ev.text));
      break;
    case "molt_config": setMolt(ev.enabled); break;
    case "doc": refreshDocs(); break;
    case "config": $("subtitle").textContent = (ev.provider || "") + " · " + (ev.model || ""); break;
    case "reset": stream.innerHTML = ""; break;
    case "log": break;
  }
}

// ---- metamorphosis (self-improvement) ------------------------------------
let MOLT_ON = false;
function setMolt(on) { MOLT_ON = !!on; $("moltBtn").classList.toggle("on", MOLT_ON); }
$("moltBtn").onclick = async () => {
  const turningOn = !MOLT_ON;
  setMolt(turningOn);
  // turning it on also molts once right away, so you see it happen
  const r = await api("/api/molt", "POST", { enabled: turningOn, now: turningOn });
  if (r && r.error) { addStep("error", "molt", esc(r.error)); setMolt(r.molt); }
};

function addEvolve(ev) {
  clearEmpty();
  const d = document.createElement("div");
  d.className = "evolve";
  const h = document.createElement("div"); h.className = "h";
  h.textContent = "🦋 SCARB evolved";
  const s = document.createElement("div"); s.className = "s"; s.textContent = ev.summary || "improved a skill";
  d.appendChild(h); d.appendChild(s);
  if (ev.skills && ev.skills.length) {
    const k = document.createElement("div"); k.className = "k"; k.textContent = "→ " + ev.skills.join(", ");
    d.appendChild(k);
  }
  stream.appendChild(d); if (atBottom()) scroll();
}

function setStatus(text, busy) {
  $("statusText").textContent = text;
  $("statusBadge").classList.toggle("busy", !!busy);
  document.body.classList.toggle("busy", !!busy);   // drives the scarab animation
  const working = !!busy && text !== "reconnecting…";
  $("send").hidden = working;                        // swap Send ↔ Stop while working
  $("stop").hidden = !working;
}
$("stop").onclick = async () => {
  stopSpeaking();
  try { await api("/api/stop", "POST", {}); } catch (e) {}
};

// ---- conversation history drawer -----------------------------------------
function openDrawer() { loadConvos(); $("drawer").classList.add("open"); $("drawerScrim").classList.add("open"); }
function closeDrawer() { $("drawer").classList.remove("open"); $("drawerScrim").classList.remove("open"); }
$("markBtn").onclick = openDrawer;
$("drawerScrim").onclick = closeDrawer;

async function loadConvos() {
  const r = await api("/api/conversations");
  const list = $("convoList"); list.innerHTML = "";
  (r.conversations || []).forEach((c) => {
    const row = document.createElement("div");
    row.className = "convo" + (c.current ? " active" : "");
    const body = document.createElement("div"); body.className = "body";
    const t = document.createElement("div"); t.className = "t"; t.textContent = c.title || "New chat";
    const meta = document.createElement("div"); meta.className = "meta";
    meta.textContent = c.count + " msg · " + timeAgo(c.updated);
    body.appendChild(t); body.appendChild(meta);
    const del = document.createElement("button"); del.className = "del"; del.textContent = "✕";
    del.onclick = async (e) => { e.stopPropagation(); await api("/api/conversation", "POST", { action: "delete", id: c.id }); loadConvos(); };
    row.appendChild(body); row.appendChild(del);
    row.onclick = () => loadConversation(c.id);
    list.appendChild(row);
  });
}

async function loadConversation(id) {
  const r = await api("/api/conversation", "POST", { action: "load", id });
  stream.innerHTML = "";
  renderHistory(r.messages);
  BOOT_T = Date.now() / 1000;
  closeDrawer();
}

async function newConversation() {
  await api("/api/conversation", "POST", { action: "new" });
  stream.innerHTML = "";
  BOOT_T = Date.now() / 1000;
  closeDrawer();
}
$("newChat").onclick = newConversation;
$("drawerNew").onclick = newConversation;

// Render a saved conversation, skipping the tool-call plumbing we now persist
// (tool results, and assistant messages that were only tool calls).
function renderHistory(messages) {
  (messages || []).forEach((m) => {
    const content = (m.content || "").toString();
    if (m.role === "user") {
      if (content.startsWith("TOOL RESULT:") || content.startsWith("(You've reached the step limit")) return;
      addUser(content);
    } else if (m.role === "assistant") {
      if (!content.trim() || m.tool_calls) return;   // skip pure tool-call turns
      addScarb(content);
    }
    // role "tool" and anything else: skip
  });
}

function timeAgo(t) {
  if (!t) return "";
  const s = Date.now() / 1000 - t;
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
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
  // voice / elevenlabs
  $("elevenKey").value = "";
  $("elevenKey").placeholder = c.has_eleven ? "•••••• (saved — blank keeps it)" : "optional — blank uses the free voice";
  $("elevenState").textContent = c.has_eleven ? "✓ saved" : "using free voice";
  $("elevenState").className = "setup-note" + (c.has_eleven ? " ok" : "");
  populateVoices(voiceCache.length ? voiceCache : (c.eleven_voice ? [{ id: c.eleven_voice, name: "saved voice" }] : []), c.eleven_voice);
  if (c.has_eleven && !voiceCache.length) fetchVoices(c.eleven_voice);
}

let voiceCache = [];
function populateVoices(list, selected) {
  const sel = $("elevenVoice"); sel.innerHTML = "";
  const opt0 = document.createElement("option"); opt0.value = ""; opt0.textContent = "Rachel (default)"; sel.appendChild(opt0);
  list.forEach((v) => {
    const o = document.createElement("option"); o.value = v.id; o.textContent = v.name;
    if (v.id === selected) o.selected = true;
    sel.appendChild(o);
  });
  if (selected && ![...sel.options].some(o => o.value === selected)) {
    const o = document.createElement("option"); o.value = selected; o.textContent = selected; o.selected = true; sel.appendChild(o);
  }
}
async function fetchVoices(selected) {
  const r = await api("/api/voices");
  if (r.voices && r.voices.length) { voiceCache = r.voices; populateVoices(r.voices, selected || $("elevenVoice").value); }
}
$("refreshVoices").onclick = async () => {
  const key = $("elevenKey").value.trim();
  if (key) await api("/api/config", "POST", { eleven_key: key });
  fetchVoices();
};
$("voiceSave").onclick = async () => {
  const body = { eleven_voice: $("elevenVoice").value };
  const key = $("elevenKey").value.trim(); if (key) body.eleven_key = key;
  const b = $("voiceSave"); b.textContent = "Saving…";
  await api("/api/config", "POST", body);
  b.textContent = "Saved ✓"; setTimeout(() => b.textContent = "Save", 1200);
  loadConfig();
};
$("voiceTest").onclick = async () => {
  const key = $("elevenKey").value.trim();
  if (key) await api("/api/config", "POST", { eleven_key: key, eleven_voice: $("elevenVoice").value });
  $("voiceResult").textContent = "playing…"; $("voiceResult").className = "setup-note";
  const prev = VOICE_OUT; VOICE_OUT = true;
  await speak("Hello — this is SCARB. Your voice is set up.");
  VOICE_OUT = prev;
  $("voiceResult").textContent = "";
};

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
  // Auto-load the full live catalogue when we can (public lists always work;
  // keyed providers need a saved key) so the dropdown fills itself in.
  const publicList = (p === "openrouter" || p === "ollama-cloud");
  if (!MODEL_CACHE[p] && (publicList || hasKey || p === "ollama")) fetchModels(p);
}

async function fetchModels(p) {
  const note = $("modelsNote"); note.textContent = "loading models…"; note.className = "setup-note";
  const icon = $("refreshModels"); icon.classList.add("spin");
  const r = await api("/api/models?provider=" + encodeURIComponent(p));
  icon.classList.remove("spin");
  if ($("cfgProvider").value !== p) return;   // user moved on
  if (r.ok && r.models.length) {
    MODEL_CACHE[p] = r.models;
    populateModels(r.models, SAVED_MODELS[p] || $("cfgModel").value);
    note.textContent = r.models.length + " models"; note.className = "setup-note ok";
  } else {
    note.textContent = r.error ? "✗ " + r.error : "";
    note.className = "setup-note" + (r.error ? " bad" : "");
  }
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

$("refreshModels").onclick = () => {
  const p = $("cfgProvider").value;
  delete MODEL_CACHE[p];   // force a fresh pull
  fetchModels(p);
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

// Chat/Skills tabs are visible by default. Swipe down tucks them away for more
// chat space; swipe up brings them back.
function showTabs() { $("app").classList.remove("tabs-hidden"); }
function hideTabs() { $("app").classList.add("tabs-hidden"); }
(function () {
  let startY = 0, startX = 0, tracking = false;
  window.addEventListener("touchstart", (e) => {
    const t = e.touches[0];
    startY = t.clientY; startX = t.clientX;
    tracking = t.clientY > window.innerHeight * 0.55;   // gesture lives in the lower half
  }, { passive: true });
  window.addEventListener("touchend", (e) => {
    if (!tracking) return;
    const t = e.changedTouches[0];
    const dy = t.clientY - startY, dx = Math.abs(t.clientX - startX);
    if (dx < 60 && dy < -50) showTabs();
    else if (dx < 60 && dy > 50) hideTabs();
  }, { passive: true });
})();
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

// ---- voice: talking to SCARB (mic) and SCARB talking back (TTS) ----------
const micBtn = $("micBtn");
let listening = false, recog = null;

// In the native app a message handler named "mic" exists; use it so the app's
// native speech recognition drives the same button. In a browser, use the
// built-in Web Speech API. The native side calls window.scarbVoiceInput(text).
const nativeMic = !!(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.mic);
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

window.scarbSetInput = (text) => {            // live partial transcript (native)
  input.value = (text || "").trimStart();
  autoGrow();
};
window.scarbVoiceInput = (text) => {          // final transcript → send (native)
  input.value = (text || "").trim();
  autoGrow();
  if (input.value) send();
};
window.scarbSetListening = (on) => {
  listening = !!on; micBtn.classList.toggle("on", listening);
  // native mic went idle without a transcript, and we're in a conversation:
  // keep listening (unless SCARB is busy replying).
  if (!on && CONVO_MODE && !input.value.trim() && !document.body.classList.contains("busy")) {
    setTimeout(beginListening, 300);
  }
};

function autoGrow() { input.style.height = "auto"; input.style.height = input.scrollHeight + "px"; }

function startWebListening() {
  if (!window.isSecureContext) {
    addStep("error", "voice", "The mic needs a secure (https) connection. Open SCARB at its https:// Tailscale address (shown when the server starts) — then tap 🎤 again. Or use the app.");
    return;
  }
  if (!SR) { addStep("error", "voice", "This browser can't do speech input — try Safari or Chrome."); return; }
  if (listening) return;
  recog = new SR();
  recog.lang = "en-US"; recog.interimResults = true; recog.continuous = false;
  const base = input.value ? input.value + " " : "";
  recog.onresult = (e) => {
    let s = "";
    for (let i = e.resultIndex; i < e.results.length; i++) s += e.results[i][0].transcript;
    input.value = (base + s).trimStart(); autoGrow();
  };
  recog.onend = () => {
    listening = false; micBtn.classList.remove("on");
    if (input.value.trim()) send();
    else if (CONVO_MODE) setTimeout(beginListening, 300);   // heard nothing — keep listening
  };
  recog.onerror = () => { listening = false; micBtn.classList.remove("on"); };
  listening = true; micBtn.classList.add("on"); recog.start();
}

micBtn.onclick = () => {
  if (nativeMic) { window.webkit.messageHandlers.mic.postMessage(listening ? "stop" : "start"); return; }
  if (listening) { recog && recog.stop(); return; }
  startWebListening();
};

// ---- hands-free conversation mode ----------------------------------------
// Tap once: SCARB listens, you talk, it auto-detects when you stop, sends,
// speaks its reply, then listens again — a natural back-and-forth, no buttons.
let CONVO_MODE = false;
function setConvo(on) {
  CONVO_MODE = on;
  $("convoBtn").classList.toggle("on", on);
  if (on) {
    setVoiceOut(true);           // conversation implies spoken replies
    beginListening();
  } else {
    if (listening) { if (nativeMic) window.webkit.messageHandlers.mic.postMessage("stop"); else recog && recog.stop(); }
    stopSpeaking();
  }
}
$("convoBtn").onclick = () => setConvo(!CONVO_MODE);

function beginListening() {
  if (!CONVO_MODE) return;
  if (listening) return;
  if (nativeMic) window.webkit.messageHandlers.mic.postMessage("start");
  else startWebListening();
}

// after SCARB finishes speaking a reply, listen again (conversation loop)
function onReplyDone() {
  if (CONVO_MODE) setTimeout(beginListening, 250);
}

// ---- SCARB speaks its replies --------------------------------------------
let VOICE_OUT = localStorage.getItem("scarb_voice") === "1";
let currentAudio = null;
function setVoiceOut(on) {
  VOICE_OUT = on;
  localStorage.setItem("scarb_voice", on ? "1" : "0");
  $("voiceBtn").textContent = on ? "🔊" : "🔈";
  $("voiceBtn").classList.toggle("on", on);
  if (!on) stopSpeaking();
}
$("voiceBtn").onclick = () => setVoiceOut(!VOICE_OUT);

function cleanForSpeech(t) {
  return (t || "")
    .replace(/```[\s\S]*?```/g, " (code) ")
    .replace(/[*_#`>]/g, "")
    .replace(/\s+/g, " ")
    .trim().slice(0, 1200);
}

async function speak(text, onDone) {
  const done = typeof onDone === "function" ? onDone : () => {};
  if (!VOICE_OUT) { done(); return; }
  const clean = cleanForSpeech(text);
  if (!clean) { done(); return; }
  stopSpeaking();
  // Prefer ElevenLabs (if a key is set on the server); otherwise the OS voice.
  try {
    const res = await fetch("/api/tts", { method: "POST", headers: headers(), body: JSON.stringify({ text: clean }) });
    const type = res.headers.get("content-type") || "";
    if (res.status === 200 && type.includes("audio")) {
      const buf = await res.arrayBuffer();
      const url = URL.createObjectURL(new Blob([buf], { type: "audio/mpeg" }));
      currentAudio = new Audio(url);
      currentAudio.onended = done;
      currentAudio.onerror = () => speakLocal(clean, done);
      currentAudio.play().catch(() => speakLocal(clean, done));
      return;
    }
  } catch (e) { /* fall through to local voice */ }
  speakLocal(clean, done);
}

function speakLocal(text, onDone) {
  const done = typeof onDone === "function" ? onDone : () => {};
  if (!window.speechSynthesis) { done(); return; }
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.03; u.pitch = 1.0;
  const pick = () => {
    const vs = speechSynthesis.getVoices();
    // prefer the natural / neural Apple & Google voices
    return vs.find(v => /(Ava|Samantha|Zoe|Allison|Siri|Natural|Neural|Google US English)/i.test(v.name))
        || vs.find(v => v.lang && v.lang.startsWith("en")) || vs[0];
  };
  const v = pick();
  if (v) u.voice = v;
  u.onend = done; u.onerror = done;
  speechSynthesis.speak(u);
}
function stopSpeaking() {
  if (window.speechSynthesis) speechSynthesis.cancel();
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
}
// some browsers load voices async
if (window.speechSynthesis) speechSynthesis.onvoiceschanged = () => {};

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
    renderHistory(state.history);
    setMolt(state.molt);
    setVoiceOut(VOICE_OUT);
    BOOT_T = Date.now() / 1000;
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
