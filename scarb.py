#!/usr/bin/env python3
"""
SCARB — a self-improving assistant.

The scarab rolls its world forward and is reborn from it. SCARB does tasks, and
when it meets one it can't do, it writes a new *skill* to do it, tests it, keeps
it, and gets a little more capable. It is shaped by two files it reads on every
turn — identity.md (what it does) and soul.md (who it is) — and it can read and
improve its own code and skills.

One file, Python standard library only. Runs a cloud model (Anthropic or any
OpenAI-compatible endpoint) and/or a local one (Ollama). Serves a live web UI
— chat plus a skills panel that updates in real time as SCARB builds itself —
that works on desktop and phone over your Tailscale network.

    python3 scarb.py            # then open the printed URL

Config via environment (all optional; see README):
    SCARB_PROVIDER   anthropic | openai | openrouter | ollama   (default: ollama)
    SCARB_API_KEY    key for the cloud provider
    SCARB_MODEL      model id
    SCARB_BASE_URL   override the API base (e.g. a local Ollama or a proxy)
    SCARB_LOCAL_MODEL / SCARB_LOCAL_BASE_URL   a local fallback model (Ollama)
    SCARB_TOKEN      shared secret required from clients (set this on Tailscale!)
    SCARB_PORT       default 8787
    SCARB_HOST       default 0.0.0.0 (reachable over Tailscale)
"""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import traceback
import urllib.request
import urllib.error
import urllib.parse
import importlib.util
import subprocess
import select
import html as _html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(HERE, "skills")
WEB_DIR = os.path.join(HERE, "web")
MEMORY_DIR = os.path.join(HERE, "memory")
VERSION = "0.1"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def env(name, default=""):
    return os.environ.get(name, default)

CONFIG_PATH = os.path.join(HERE, "config.json")

PROVIDERS = ["anthropic", "openrouter", "openai", "ollama-cloud", "ollama"]

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "openrouter": "anthropic/claude-sonnet-4.6",
    "ollama-cloud": "gpt-oss:120b",
}

DEFAULT_BASE = {
    "anthropic": "https://api.anthropic.com/v1",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama-cloud": "https://ollama.com/v1",
}

# Fields the UI can edit and that we persist to config.json. token/port/host
# stay environment-only, so nobody can weaken the auth from the browser. Keys
# and models are kept PER PROVIDER so switching providers never sends one
# service's key to another.
UI_FIELDS = ("provider", "keys", "models", "local_model", "local_base_url", "molt",
             "eleven_key", "eleven_voice")


def _load_saved():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}

_SAVED = _load_saved()


def _migrate(saved):
    """Fold an older single-key config into the per-provider maps."""
    keys = dict(saved.get("keys") or {})
    models = dict(saved.get("models") or {})
    prov = saved.get("provider") or env("SCARB_PROVIDER", "ollama")
    if saved.get("api_key") and prov not in keys:
        keys[prov] = saved["api_key"]
    if saved.get("model") and prov not in models:
        models[prov] = saved["model"]
    # seed a cloud key from the environment if one is set and unclaimed
    envkey = env("SCARB_API_KEY", "")
    if envkey and prov != "ollama" and prov not in keys:
        keys[prov] = envkey
    return keys, models

_KEYS, _MODELS = _migrate(_SAVED)

CONFIG = {
    "provider": _SAVED.get("provider") or env("SCARB_PROVIDER", "ollama"),
    "keys": _KEYS,       # {provider: api_key}
    "models": _MODELS,   # {provider: model_id}
    "local_model": _SAVED.get("local_model") or env("SCARB_LOCAL_MODEL", "llama3.1"),
    "local_base_url": _SAVED.get("local_base_url") or env("SCARB_LOCAL_BASE_URL", "http://127.0.0.1:11434/v1"),
    "molt": _SAVED.get("molt", False),
    "molt_interval": int(env("SCARB_MOLT_INTERVAL", "1200")),
    "eleven_key": _SAVED.get("eleven_key", env("ELEVENLABS_API_KEY", "")),
    "eleven_voice": _SAVED.get("eleven_voice", ""),
    "token": env("SCARB_TOKEN", ""),
    "port": int(env("SCARB_PORT", "8787")),
    "host": env("SCARB_HOST", "0.0.0.0"),
}


def save_config():
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump({k: CONFIG[k] for k in UI_FIELDS}, f, indent=2)
    except Exception as e:
        BUS.emit("log", text=f"could not save config: {e}")


def key_for(provider):
    return CONFIG["keys"].get(provider, "")


def model_for(provider):
    return CONFIG["models"].get(provider) or DEFAULT_MODELS.get(provider, "")


def provider_for(kind):
    """Resolve a (provider, model, base_url, api_key) tuple for 'cloud' or 'local'."""
    if kind == "local":
        return ("ollama", CONFIG["local_model"], CONFIG["local_base_url"], "")
    p = CONFIG["provider"]
    if p == "ollama":
        return ("ollama", model_for("ollama") or CONFIG["local_model"],
                CONFIG["local_base_url"], "")
    model = model_for(p)
    base = DEFAULT_BASE.get(p, "")
    return (p, model, base, key_for(p))


def ollama_host():
    """The Ollama root URL (its native /api lives there, not under /v1)."""
    base = CONFIG["local_base_url"].rstrip("/")
    return base[:-3].rstrip("/") if base.endswith("/v1") else base


def list_ollama_models():
    """Ask a local Ollama what models are installed. Empty list if it's not running."""
    try:
        req = urllib.request.Request(ollama_host() + "/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def fetch_models(provider):
    """The live catalogue for a provider (its /models endpoint), sorted."""
    if provider == "ollama":
        return list_ollama_models()
    base = DEFAULT_BASE.get(provider)
    if not base:
        raise LLMError(f"unknown provider '{provider}'")
    key = key_for(provider)
    headers = {}
    if provider == "anthropic":
        if not key:
            raise LLMError("add your Anthropic key first")
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    elif key:
        headers["authorization"] = f"Bearer {key}"  # OpenRouter's list is public; others need a key
    req = urllib.request.Request(base.rstrip("/") + "/models", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise LLMError(f"{e.code}: {e.read().decode(errors='replace')[:200]}")
    except urllib.error.URLError as e:
        raise LLMError(f"cannot reach {provider}: {e.reason}")
    arr = data.get("data") or data.get("models") or []
    ids = [m.get("id") or m.get("name") for m in arr if isinstance(m, dict)]
    return sorted(i for i in ids if i)


# ---------------------------------------------------------------------------
# Event bus — pushes live updates (steps, skill changes) to the web UI over SSE
# ---------------------------------------------------------------------------

class EventBus:
    def __init__(self):
        self.clients = []
        self.lock = threading.Lock()
        self.log = []  # recent events, so a fresh page can catch up

    def subscribe(self):
        q = queue.Queue()
        with self.lock:
            self.clients.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)

    def emit(self, kind, **data):
        event = {"kind": kind, "t": time.time(), **data}
        with self.lock:
            self.log = (self.log + [event])[-200:]
            targets = list(self.clients)
        for q in targets:
            try:
                q.put_nowait(event)
            except Exception:
                pass
        return event

BUS = EventBus()


# ---------------------------------------------------------------------------
# LLM client — Anthropic, OpenAI-compatible (OpenRouter/…), and Ollama (local)
# ---------------------------------------------------------------------------

class LLMError(Exception):
    pass


def llm_chat(system, messages, kind="cloud", max_tokens=2048):
    """messages: list of {"role": "user"|"assistant", "content": str}. Returns text."""
    provider, model, base, key = provider_for(kind)
    if not base:
        raise LLMError(f"no base URL for provider '{provider}'")
    if provider == "anthropic":
        return _anthropic(system, messages, model, base, key, max_tokens)
    return _openai_compatible(system, messages, model, base, key, max_tokens)


def _http_json(url, payload, headers, timeout=180):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise LLMError(f"{e.code} {e.reason}: {detail[:400]}")
    except urllib.error.URLError as e:
        raise LLMError(f"cannot reach {url}: {e.reason}")


def _anthropic(system, messages, model, base, key, max_tokens):
    if not key:
        raise LLMError("SCARB_API_KEY is required for Anthropic")
    payload = {"model": model, "max_tokens": max_tokens, "system": system,
               "messages": messages}
    headers = {"content-type": "application/json", "x-api-key": key,
               "anthropic-version": "2023-06-01"}
    data = _http_json(base.rstrip("/") + "/messages", payload, headers)
    parts = data.get("content", [])
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    if not text:
        raise LLMError("empty response from Anthropic")
    return text


def _openai_compatible(system, messages, model, base, key, max_tokens):
    msgs = [{"role": "system", "content": system}] + messages
    payload = {"model": model, "messages": msgs, "max_tokens": max_tokens,
               "stream": False}
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    data = _http_json(base.rstrip("/") + "/chat/completions", payload, headers)
    if "error" in data:
        raise LLMError(str(data["error"]))
    choices = data.get("choices", [])
    if not choices:
        raise LLMError("no choices returned")
    msg = choices[0].get("message", {})
    text = msg.get("content")
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text)
    if not text:
        # some reasoning models put text under reasoning fields
        text = msg.get("reasoning_content") or msg.get("reasoning") or ""
    if not text:
        raise LLMError("empty response")
    return text


def openai_message(system, messages, kind, tools, max_tokens=2048):
    """Native tool-calling call for OpenAI-compatible providers. Returns the raw
    assistant message dict — which carries structured `tool_calls` the model
    cannot fake into prose, so it can't claim it did something it didn't."""
    provider, model, base, key = provider_for(kind)
    msgs = [{"role": "system", "content": system}] + messages
    payload = {"model": model, "messages": msgs, "max_tokens": max_tokens, "stream": False}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    data = _http_json(base.rstrip("/") + "/chat/completions", payload, headers)
    if "error" in data:
        raise LLMError(str(data["error"]))
    choices = data.get("choices", [])
    if not choices:
        raise LLMError("no choices returned")
    return choices[0].get("message", {}) or {}


def tool_specs():
    """OpenAI-style function schemas for every core tool and skill. Args are a
    free-form object; each tool's description says what keys to pass."""
    core_desc = {
        "create_skill": "Create a NEW skill. args: name, description, code (a full Python module defining run(args)).",
        "update_skill": "Rewrite an existing skill. args: name, description, code.",
        "read_skill": "Read a skill's source. args: name.",
        "delete_skill": "Delete a skill. args: name.",
        "list_skills": "List every skill you have. args: {}.",
        "read_file": "Read a file (path relative to SCARB's folder). args: path.",
        "write_file": "Write a file. args: path, content.",
        "run_shell": "Run a shell command on this machine. args: command, timeout.",
        "read_self": "Read your own scarb.py / identity.md / soul.md. args: file.",
        "applescript": "Run AppleScript to control this Mac. args: script.",
        "open_app": "Open an app or a URL/file. args: name or url.",
        "type_text": "Type text into the frontmost app. args: text.",
        "screenshot": "Capture the screen to memory/screen.png. args: {}.",
    }
    specs = []
    for name in CORE_TOOLS:
        specs.append({"type": "function", "function": {
            "name": name, "description": core_desc.get(name, name)[:1000],
            "parameters": {"type": "object", "additionalProperties": True}}})
    for s in SKILLS.list():
        specs.append({"type": "function", "function": {
            "name": s["name"], "description": s["description"][:1000],
            "parameters": {"type": "object", "additionalProperties": True}}})
    return specs


# ---- voice: ElevenLabs text-to-speech (optional; free OS voice otherwise) --

# A "premade" voice that free ElevenLabs plans can synthesize via the API
# (shared "library" voices require a paid plan). "Sarah" — warm and natural.
ELEVEN_DEFAULT_VOICE = "EXAVITQu4vr4xnSDxMaL"


def elevenlabs_tts(text):
    """Return MP3 bytes for `text`, or None if no key / it fails (client then
    falls back to the browser's built-in voice)."""
    key = CONFIG.get("eleven_key", "")
    if not key or not text.strip():
        return None
    voice = CONFIG.get("eleven_voice") or ELEVEN_DEFAULT_VOICE
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    payload = {"text": text[:1500], "model_id": "eleven_turbo_v2_5",
               "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"xi-api-key": key, "content-type": "application/json",
                                          "accept": "audio/mpeg"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception as e:
        BUS.emit("log", text=f"ElevenLabs TTS failed: {e}")
        return None


def elevenlabs_voices():
    key = CONFIG.get("eleven_key", "")
    if not key:
        return []
    req = urllib.request.Request("https://api.elevenlabs.io/v1/voices",
                                 headers={"xi-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        return [{"id": v["voice_id"], "name": v["name"]} for v in data.get("voices", [])]
    except Exception:
        return []


def friendly_error(err, kind):
    """Turn a raw LLM error into something that tells you how to fix it."""
    msg = str(err)
    provider, model, base, key = provider_for(kind)
    local = provider == "ollama" or kind == "local"
    if "Connection refused" in msg or "cannot reach" in msg:
        if local:
            return ("Can't reach Ollama at " + base + ". Start it with `ollama serve`, "
                    "pull a model with `ollama pull llama3.2`, or open Setup → Cloud model and add an API key.")
        return f"Can't reach {provider} ({base}). Check your connection, or pick another provider in Setup."
    if "not found" in msg.lower() and local:
        return (f"Ollama doesn't have the model '{model}'. Run `ollama pull {model}` "
                "(or tap Detect Ollama in Setup and choose one you have).")
    if "401" in msg or "invalid" in msg.lower() or "api key" in msg.lower():
        return f"{provider} rejected the API key. Re-check it in Setup → Cloud model."
    return msg


def strip_thinking(text):
    while "<think>" in text and "</think>" in text:
        a = text.index("<think>")
        b = text.index("</think>") + len("</think>")
        text = text[:a] + text[b:]
    return text.strip()


# ---------------------------------------------------------------------------
# Skills — SCARB's growable set of abilities. Each is skills/<name>.py with a
# `# name:` / `# description:` header and a run(args) -> value function.
# ---------------------------------------------------------------------------

SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


class Skill:
    def __init__(self, name, description, path, run):
        self.name = name
        self.description = description
        self.path = path
        self.run = run

    def to_dict(self):
        return {"name": self.name, "description": self.description,
                "source": os.path.basename(self.path)}


class Skills:
    def __init__(self, directory):
        self.dir = directory
        self.skills = {}
        os.makedirs(directory, exist_ok=True)
        self.reload_all()

    def reload_all(self):
        self.skills = {}
        for fn in sorted(os.listdir(self.dir)):
            if fn.endswith(".py") and not fn.startswith("_"):
                try:
                    self._load_file(os.path.join(self.dir, fn))
                except Exception as e:
                    BUS.emit("log", text=f"skill {fn} failed to load: {e}")

    def _load_file(self, path):
        with open(path) as f:
            src = f.read()
        name = _header(src, "name") or os.path.splitext(os.path.basename(path))[0]
        desc = _header(src, "description") or "(no description)"
        # Compile straight from source into a fresh namespace. This avoids
        # importlib's bytecode cache, which would otherwise serve a skill's OLD
        # code after an edit made within the same filesystem-mtime second — the
        # reason "editing a skill did nothing".
        ns = {"__name__": f"skill_{name}", "__file__": path}
        code = compile(src, path, "exec")
        exec(code, ns)
        run = ns.get("run")
        if not callable(run):
            raise ValueError("skill must define a run(args) function")
        self.skills[name] = Skill(name, desc, path, run)
        return self.skills[name]

    def list(self):
        return [s.to_dict() for s in sorted(self.skills.values(), key=lambda s: s.name)]

    def has(self, name):
        return name in self.skills

    def run(self, name, args):
        if name not in self.skills:
            raise KeyError(name)
        return self.skills[name].run(args or {})

    def write(self, name, description, code):
        if not SKILL_NAME_RE.match(name):
            raise ValueError("skill name must be lowercase letters, digits, underscores")
        if "def run(" not in code:
            raise ValueError("skill code must define run(args)")
        # Models editing a skill often paste back the existing "# name:" /
        # "# description:" header inside the code; strip those leading meta
        # lines so we don't stack duplicate headers on every edit.
        lines = code.splitlines()
        while lines and re.match(r"^\s*#\s*(name|description)\s*:", lines[0]):
            lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
        code = "\n".join(lines)
        header = f"# name: {name}\n# description: {description.strip()}\n"
        path = os.path.join(self.dir, f"{name}.py")
        with open(path, "w") as f:
            f.write(header + code.rstrip() + "\n")
        skill = self._load_file(path)  # validates + hot-loads; raises on error
        BUS.emit("skill", action="saved", skill=skill.to_dict())
        return skill

    def read(self, name):
        path = os.path.join(self.dir, f"{name}.py")
        with open(path) as f:
            return f.read()

    def delete(self, name):
        path = os.path.join(self.dir, f"{name}.py")
        if os.path.exists(path):
            os.remove(path)
        self.skills.pop(name, None)
        BUS.emit("skill", action="deleted", skill={"name": name})


def _header(src, field):
    m = re.search(rf"^#\s*{field}\s*:\s*(.+)$", src, re.MULTILINE)
    return m.group(1).strip() if m else None

SKILLS = Skills(SKILLS_DIR)


# ---------------------------------------------------------------------------
# Core tools — the built-in verbs the model can use, beyond its skills. The
# headline ones are create_skill / update_skill: how SCARB grows.
# ---------------------------------------------------------------------------

def tool_create_skill(args):
    name = str(args.get("name", "")).strip()
    desc = str(args.get("description", "")).strip()
    code = args.get("code", "")
    if not name or not code:
        return {"ok": False, "error": "need name, description, and code"}
    try:
        skill = SKILLS.write(name, desc, code)
        return {"ok": True, "result": f"skill '{name}' created and loaded"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_update_skill(args):
    return tool_create_skill(args)  # same path: overwrite + reload + validate


def tool_read_skill(args):
    name = str(args.get("name", "")).strip()
    try:
        return {"ok": True, "result": SKILLS.read(name)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_delete_skill(args):
    name = str(args.get("name", "")).strip()
    SKILLS.delete(name)
    return {"ok": True, "result": f"deleted '{name}'"}


def tool_list_skills(args):
    return {"ok": True, "result": SKILLS.list()}


def _safe_path(p):
    full = os.path.abspath(os.path.join(HERE, p)) if not os.path.isabs(p) else os.path.abspath(p)
    return full


def tool_read_file(args):
    try:
        with open(_safe_path(args.get("path", "")), "r", errors="replace") as f:
            data = f.read()
        return {"ok": True, "result": data[:20000]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_write_file(args):
    try:
        path = _safe_path(args.get("path", ""))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(args.get("content", ""))
        return {"ok": True, "result": f"wrote {path}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class Shell:
    """A terminal with a persistent working directory: `cd` carries over between
    commands, like a terminal you keep open. Each command is its own bash, so
    chain env within one command (`source venv/bin/activate && python …`)."""
    def __init__(self):
        self.cwd = os.path.expanduser("~")
        self.lock = threading.Lock()

    def run(self, command, timeout=120):
        with self.lock:
            marker = "__SCARB_CWD__"
            script = f"{command}\n__rc=$?\nprintf '%s%s' '{marker}' \"$(pwd)\"\nexit $__rc"
            try:
                p = subprocess.run(["/bin/bash", "-c", script], cwd=self.cwd,
                                   capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": f"command still running after {timeout}s"}
            except FileNotFoundError:
                self.cwd = os.path.expanduser("~")
                return {"ok": False, "error": "working directory was gone; reset to home"}
            out = p.stdout or ""
            new_cwd = self.cwd
            if marker in out:
                out, _, cwd = out.rpartition(marker)
                new_cwd = cwd.strip() or self.cwd
            if p.stderr:
                out = out + p.stderr
            if os.path.isdir(new_cwd):
                self.cwd = new_cwd
            return {"ok": p.returncode == 0, "exit_code": p.returncode, "cwd": self.cwd,
                    "result": (out.strip()[-9000:]) or "(no output)"}

    def reset(self):
        self.cwd = os.path.expanduser("~")

SHELL = Shell()


def tool_run_shell(args):
    cmd = args.get("command", "")
    if not cmd:
        return {"ok": False, "error": "no command"}
    if args.get("reset"):
        SHELL.reset()
    return SHELL.run(cmd, timeout=int(args.get("timeout", 120)))


# ---- computer use (control the actual machine) ---------------------------

def _is_mac():
    return sys.platform == "darwin"


def tool_applescript(args):
    """Run AppleScript — the master key to macOS: open/close/arrange apps,
    click buttons and menus, type text, read the screen's UI, etc."""
    if not _is_mac():
        return {"ok": False, "error": "AppleScript is macOS-only"}
    script = args.get("script", "")
    if not script:
        return {"ok": False, "error": "no script"}
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True,
                              text=True, timeout=int(args.get("timeout", 30)))
        out = (proc.stdout + proc.stderr).strip()
        return {"ok": proc.returncode == 0, "result": out[:6000]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "script timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_open_app(args):
    name = args.get("name", "")
    if not name:
        return {"ok": False, "error": "no app name"}
    target = ["-a", name]
    if args.get("url"):
        target = [args["url"]]
    try:
        subprocess.run(["open"] + target, capture_output=True, text=True, timeout=15)
        return {"ok": True, "result": f"opened {args.get('url') or name}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_type_text(args):
    """Type text into the frontmost app. Pass "enter": true to submit (press
    Return after) — e.g. running a terminal command or a search."""
    if not _is_mac():
        return {"ok": False, "error": "typing is macOS-only"}
    text = args.get("text", "")
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    r = tool_applescript({"script": f'tell application "System Events" to keystroke "{safe}"'})
    if r.get("ok") and (args.get("enter") or args.get("submit")):
        # key code 36 = Return (the WORD "return" would just be typed)
        tool_applescript({"script": 'tell application "System Events" to key code 36'})
        r["result"] = f"typed and pressed Enter"
    return r


def tool_screenshot(args):
    """Capture the screen to a PNG under memory/. A vision-capable model can
    then read it with read_file to actually see the screen."""
    if not _is_mac():
        return {"ok": False, "error": "screenshot is macOS-only"}
    os.makedirs(MEMORY_DIR, exist_ok=True)
    path = os.path.join(MEMORY_DIR, "screen.png")
    try:
        subprocess.run(["screencapture", "-x", path], capture_output=True, timeout=15)
        if os.path.exists(path):
            return {"ok": True, "result": {"path": path, "bytes": os.path.getsize(path)}}
        return {"ok": False, "error": "capture produced no file (grant Screen Recording permission)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_read_self(args):
    which = args.get("file", "scarb.py")
    allowed = {"scarb.py", "identity.md", "soul.md"}
    if which not in allowed:
        return {"ok": False, "error": f"file must be one of {sorted(allowed)}"}
    try:
        with open(os.path.join(HERE, which)) as f:
            return {"ok": True, "result": f.read()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


CORE_TOOLS = {
    "create_skill": tool_create_skill,
    "update_skill": tool_update_skill,
    "read_skill": tool_read_skill,
    "delete_skill": tool_delete_skill,
    "list_skills": tool_list_skills,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "run_shell": tool_run_shell,
    "read_self": tool_read_self,
    # computer use
    "applescript": tool_applescript,
    "open_app": tool_open_app,
    "type_text": tool_type_text,
    "screenshot": tool_screenshot,
}


def dispatch(tool, args):
    if tool in CORE_TOOLS:
        return CORE_TOOLS[tool](args or {})
    if SKILLS.has(tool):
        try:
            result = SKILLS.run(tool, args or {})
            if isinstance(result, dict) and "ok" in result:
                return result
            return {"ok": True, "result": result}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc()[-1500:]}
    return {"ok": False, "error": f"no tool or skill named '{tool}'. "
            "If you need this ability, create it with create_skill."}


# ---------------------------------------------------------------------------
# The agent loop — read soul + identity, plan, act with tools, build skills,
# stream every step to the UI, and finish when the task is truly done.
# ---------------------------------------------------------------------------

def read_doc(name, fallback=""):
    try:
        with open(os.path.join(HERE, name)) as f:
            return f.read()
    except Exception:
        return fallback


ACTION_RULES = """
HOW YOU ACT
You work in steps. To use a tool, output a single JSON object as the LAST thing in your reply:
{"tool": "<tool or skill name>", "args": { ... }}
(a ```json fenced block is fine too). Output the action and STOP — do not describe the result or say a task is done until I have actually run the tool and given you the result. NEVER invent a tool result. When the task is truly finished, reply in plain words with NO json object.

CORE TOOLS
- list_skills {} — see what you can already do.
- create_skill {"name","description","code"} — write a NEW skill when no skill fits. code is a full Python module (standard library only) defining run(args) that returns a value or {"ok":bool,"result"/"error":...}. Validated and hot-loaded immediately; if it errors you get the message to fix it. Reuse skills forever.
- update_skill / read_skill / delete_skill {"name"}
- read_file {"path"} / write_file {"path","content"} — read/write files anywhere (absolute paths ok).
- run_shell {"command","timeout"} — the TERMINAL. Run ANY shell command with full power. The working directory PERSISTS between calls (cd carries over), so navigate and work like a real terminal. Chain env in one command (source venv/bin/activate && python …). Use this for git, package managers, scripts, file ops, launching things — anything a terminal can do.
- read_self {"file"} — read your own scarb.py / identity.md / soul.md, to improve yourself.

INTERNET (the `web` skill)
- web {"action":"search","query":"…"} — search the web (results with titles, urls, snippets).
- web {"action":"fetch","url":"…"} — download a page and read its text.
- web {"action":"answer","query":"…"} — a quick instant-answer summary.
Use search to find things and fetch to read a page. You are NOT limited to your training data — look things up.

COMPUTER USE (you control this Mac)
- **`computer` skill — use this to see and click.** You CANNOT see the screen by intuition. To click or interact with anything, FIRST call `computer` with {"action":"see"} to get the REAL list of on-screen buttons, menus, and fields BY NAME (and their coordinates). Then click the exact name you saw: {"action":"click","target":"<exact name>"}. Other actions: {"action":"menu","path":["File","New Window"]}, {"action":"focus","app":"Safari"}, {"action":"apps"}, {"action":"type","text":"…"}, {"action":"key","keys":"cmd+s"}, {"action":"click","x":120,"y":340} (only if there's no named element), {"action":"screenshot"}. NEVER guess a name or coordinate — see first. If a click fails, `see` again to get the current names, and improve the `computer` skill (update_skill) if it's the skill that's wrong.
- To SUBMIT after typing (run a terminal command, send a search/message), type with "enter":true — {"tool":"computer","args":{"action":"type","text":"ls -la","enter":true}} — or press the key: {"action":"key","keys":"enter"}. NEVER type the word "enter"; that just types letters. (After you type, a screenshot of the screen is shown in the chat automatically.)
- applescript {"script"} — raw AppleScript, for anything the `computer` skill doesn't cover.
- open_app {"name"} or {"url"} — launch an app or open a URL/file.
- type_text {"text"} / screenshot {} — lower-level helpers.
(First use may need macOS Accessibility / Screen-Recording permission for the app running SCARB — if `see` returns a permission error, tell the human to grant it.)

Plus every skill below is callable directly by its name as a tool.

SELF-IMPROVING SKILLS (do this on your own, without being asked)
- As you USE skills, improve them in place. The moment a skill errors, returns a wrong/empty/partial result, or you spot a better or more general way to do it, call update_skill to fix it RIGHT THEN — before you finish the task. You never need permission to improve your own skills.
- Never just work around a broken or clumsy skill: repair the skill itself so it's better the next time. A tool result that says a skill failed is your cue to update_skill, not to give up or fake success.
- Keep skills general and robust: handle missing/oddly-typed args, add the option the task revealed you needed, and tidy the code as you go. Growing and refining your skills is the whole point of you.

FULL CONTROL — this is your human's own Mac and they have given you full control of it. Act decisively and autonomously: you do NOT need to ask permission for ordinary actions (running commands, opening/clicking/typing, editing files, searching the web, controlling apps). Just do the task, using as many tool steps as it takes, and report what happened. Only pause to confirm on the genuinely catastrophic and irreversible (wiping a disk, `rm -rf` on important data, force-deleting large amounts of the user's files) — and even then, one quick check, not hand-wringing.

RULES
- Write replies in PLAIN TEXT. No markdown: no ** for bold, no * for italics, no # headings, no backticks. Just clean sentences; for a list use short lines starting with a dash. Keep it readable and conversational.
- If the human confirms something already worked, thanks you, or says stop / leave it / it's fine / that's enough / it was successful — DO NOT redo the task or call any tool. Just acknowledge in one short line. If a task already succeeded earlier in the conversation, treat it as done.
- You can ONLY affect the computer by calling a tool and getting its result back. If you have not received a tool result, the thing did NOT happen.
- NEVER say a task is done, or report a click/file/command/state change, unless a tool result confirmed it. Do not fabricate results. If you haven't called the tool yet, call it now instead of describing it.
- To click or interact with the screen, use the `computer` skill and `see` first. To run commands, use run_shell. To look things up, use the `web` skill. When you lack a capability, create a skill for it and use it.
- Do the task fully; check each tool result. If a result says ok:false, either fix it and retry, or report the actual error — don't pretend it succeeded.
"""


def load_memory():
    """The notes SCARB has chosen to remember (via the `remember` skill)."""
    try:
        with open(os.path.join(MEMORY_DIR, "notes.json")) as f:
            return json.load(f)
    except Exception:
        return {}


def build_system():
    identity = read_doc("identity.md")
    soul = read_doc("soul.md")
    skill_lines = "\n".join(f"- {s['name']}: {s['description']}" for s in SKILLS.list()) or "(none yet)"
    notes = load_memory()
    mem = ""
    if notes:
        # Persistent memory: what SCARB already knows about its human, injected
        # every turn so it carries across sessions. Use `remember` to add more.
        lines = "\n".join(f"- {k}: {v}" for k, v in list(notes.items())[:40])
        mem = f"\n\nWHAT YOU REMEMBER (persistent memory — recall/update it with the `remember` skill):\n{lines}\n"
    return (
        f"You are SCARB.\n\n# IDENTITY\n{identity}\n\n# SOUL\n{soul}\n\n"
        f"{ACTION_RULES}\n\nYOUR SKILLS RIGHT NOW:\n{skill_lines}\n{mem}"
    )


ACTION_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _try_object(text, start):
    """Read a brace-balanced JSON object starting at text[start] ('{'),
    respecting string literals. Returns (obj_or_None, index_after)."""
    depth, instr, esc = 0, False, False
    for j in range(start, len(text)):
        c = text[j]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        else:
            if c == '"':
                instr = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    frag = text[start:j + 1]
                    try:
                        return json.loads(frag), j + 1
                    except Exception:
                        return None, j + 1
    return None, len(text)


def extract_action(text):
    """Find a tool action whether it's in a ```json``` fence OR bare inline
    (smaller / local models often skip the fence). Returns the last valid one."""
    for raw in reversed(ACTION_RE.findall(text)):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and "tool" in obj:
                return obj
        except Exception:
            continue
    found, i, n = None, 0, len(text)
    while i < n:
        if text[i] == "{":
            obj, end = _try_object(text, i)
            if isinstance(obj, dict) and "tool" in obj:
                found = obj
                i = end
                continue
        i += 1
    return found


# ---- conversations: many chats, each persisted, browsable from the UI ------
CONVOS = []            # list of {id, title, created, updated, messages:[...]}
CURRENT_ID = [None]    # boxed so helpers can rebind it
CONVO_LOCK = threading.Lock()
BUSY = threading.Event()
CANCEL = threading.Event()   # set by /api/stop to halt the current turn
CONVOS_PATH = os.path.join(MEMORY_DIR, "conversations.json")
LEGACY_HISTORY = os.path.join(MEMORY_DIR, "history.json")


_ID_COUNTER = [0]


def _new_id():
    _ID_COUNTER[0] += 1
    return f"{int(time.time() * 1000)}-{_ID_COUNTER[0]}"


def _title_from(text):
    t = " ".join(text.strip().split())
    return (t[:44] + "…") if len(t) > 45 else (t or "New chat")


def new_convo():
    c = {"id": _new_id(), "title": "New chat", "created": time.time(),
         "updated": time.time(), "messages": []}
    CONVOS.append(c)
    CURRENT_ID[0] = c["id"]
    return c


def current_convo():
    for c in CONVOS:
        if c["id"] == CURRENT_ID[0]:
            return c
    return new_convo()


def save_convos():
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(CONVOS_PATH, "w") as f:
            json.dump({"current": CURRENT_ID[0], "convos": CONVOS[-100:]}, f)
    except Exception:
        pass


def load_convos():
    try:
        with open(CONVOS_PATH) as f:
            data = json.load(f)
        CONVOS.extend(data.get("convos", []))
        CURRENT_ID[0] = data.get("current")
    except Exception:
        pass
    if not CONVOS:
        # migrate a single legacy history.json into the first conversation
        try:
            with open(LEGACY_HISTORY) as f:
                msgs = json.load(f)
            if isinstance(msgs, list) and msgs:
                c = new_convo()
                c["messages"] = msgs[-400:]
                first_user = next((m["content"] for m in msgs if m["role"] == "user"), "")
                c["title"] = _title_from(first_user)
        except Exception:
            pass
    if not CONVOS:
        new_convo()
    if not any(c["id"] == CURRENT_ID[0] for c in CONVOS):
        CURRENT_ID[0] = CONVOS[-1]["id"]


def convo_summaries():
    out = []
    for c in sorted(CONVOS, key=lambda c: c.get("updated", 0), reverse=True):
        out.append({"id": c["id"], "title": c["title"], "updated": c.get("updated", 0),
                    "count": len(c["messages"]), "current": c["id"] == CURRENT_ID[0]})
    return out


SHOTS_DIR = os.path.join(MEMORY_DIR, "shots")

# Tools/actions that change what's on screen — after these, auto-capture a
# screenshot so you SEE what got opened / typed / clicked / searched.
_VISUAL_COMPUTER = {"click", "rightclick", "menu", "move", "drag", "scroll",
                    "focus", "type", "key", "press", "window"}


def _is_visual_action(tool, args):
    if tool in ("open_app", "type_text", "applescript"):
        return True
    if tool == "computer":
        return str((args or {}).get("action", "")).lower() in _VISUAL_COMPUTER
    return False


def capture_screen():
    """Grab the screen to a uniquely-named file; returns its id (or None). Keeps
    the last ~20 so each inline chat screenshot stays correct."""
    if sys.platform != "darwin":
        return None
    try:
        os.makedirs(SHOTS_DIR, exist_ok=True)
        tag = str(int(time.time() * 1000))
        path = os.path.join(SHOTS_DIR, tag + ".png")
        subprocess.run(["screencapture", "-x", path], capture_output=True, timeout=12)
        if not os.path.exists(path):
            return None
        for old in sorted(os.listdir(SHOTS_DIR))[:-20]:
            try:
                os.remove(os.path.join(SHOTS_DIR, old))
            except Exception:
                pass
        return tag
    except Exception:
        return None


def run_turn(user_message, kind="cloud", max_steps=20):
    """Run one full agent turn (may take several tool steps). Streams via BUS."""
    if BUSY.is_set():
        BUS.emit("error", text="SCARB is already working on something.")
        return
    BUSY.set()
    CANCEL.clear()
    try:
        with CONVO_LOCK:
            convo = current_convo()
            convo["messages"].append({"role": "user", "content": user_message})
            if convo["title"] == "New chat":
                convo["title"] = _title_from(user_message)
            convo["updated"] = time.time()
            messages = list(convo["messages"])
            save_convos()
        BUS.emit("user", text=user_message)
        BUS.emit("status", text="thinking", model=provider_for(kind)[1], where=kind)

        system = build_system()
        native = provider_for(kind)[0] != "anthropic"   # everyone but Anthropic gets native tool-calls
        specs = tool_specs() if native else None

        def do_action(name, args):
            BUS.emit("action", tool=name, args=args or {})
            result = dispatch(name, args or {})
            BUS.emit("result", tool=name, ok=bool(result.get("ok", True)), result=_short(result))
            # Show the desktop live: if the action changed the screen (or took a
            # screenshot itself), capture it and drop it inline in the chat so you
            # see exactly what got opened / typed / clicked / searched.
            res = result.get("result")
            explicit = isinstance(res, dict) and str(res.get("path", "")).endswith(".png")
            if (explicit or _is_visual_action(name, args)) and result.get("ok", True):
                tag = capture_screen()
                if tag:
                    BUS.emit("screenshot", url=f"/api/screen?id={tag}")
            return result

        def result_content(name, result):
            body = json.dumps(result)[:6000]
            # When a SKILL fails while being used, nudge SCARB to repair the
            # skill itself right now — automatic self-improvement.
            if SKILLS.has(name) and not result.get("ok", True):
                body += ("\n\n[SCARB: this skill errored while you used it. Fix the skill "
                         "itself now with update_skill so it works next time — don't just "
                         "work around it.]")
            return body

        for step in range(max_steps):
            if CANCEL.is_set():
                BUS.emit("assistant", text="(stopped)")
                messages.append({"role": "assistant", "content": "(stopped by you)"})
                _persist_turn(messages)
                return
            # --- get one model turn (with the local fallback) ---
            try:
                if native:
                    msg = openai_message(system, messages, kind, specs)
                else:
                    msg = {"content": llm_chat(system, messages, kind=kind)}
            except LLMError as e:
                if kind == "cloud" and provider_for("cloud")[0] != "ollama" and CONFIG["local_base_url"]:
                    BUS.emit("status", text="cloud failed; trying local")
                    try:
                        kind = "local"; native = True; specs = tool_specs()
                        msg = openai_message(system, messages, kind, specs)
                    except LLMError as e2:
                        BUS.emit("error", text=friendly_error(e2, "local"))
                        return
                else:
                    BUS.emit("error", text=friendly_error(e, kind))
                    return

            content = strip_thinking(msg.get("content") or "")
            tool_calls = msg.get("tool_calls") or []

            # --- native structured tool calls (can't be faked as prose) ---
            if tool_calls:
                if content:
                    BUS.emit("thought", text=content)
                messages.append({"role": "assistant", "content": content or None,
                                 "tool_calls": tool_calls})
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    raw = fn.get("arguments", "{}")
                    try:
                        args = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                    except Exception:
                        args = {}
                    result = do_action(name, args)
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                     "content": result_content(name, result)})
                continue

            # --- prose-JSON action (fallback for models that ignore tools) ---
            action = extract_action(content)
            if action:
                prose = ACTION_RE.sub("", content).strip()
                if prose:
                    BUS.emit("thought", text=prose)
                result = do_action(action["tool"], action.get("args", {}))
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": "TOOL RESULT:\n" + result_content(action["tool"], result)})
                continue

            # --- no tool call → final answer ---
            BUS.emit("assistant", text=content)
            messages.append({"role": "assistant", "content": content})
            _persist_turn(messages)
            return

        # --- step limit: don't dead-end. Ask for a plain summary (no tools) so
        # the turn closes with a real answer that is SAVED to the conversation,
        # so a later "it worked" / "leave it" isn't answered by redoing it.
        messages.append({"role": "user", "content":
                         "(You've reached the step limit for this task.) Reply now in plain words "
                         "with the outcome — what you got done and anything still left. Do NOT call any tool."})
        try:
            final = (openai_message(system, messages, kind, None) if native
                     else {"content": llm_chat(system, messages, kind=kind)})
            summary = strip_thinking(final.get("content") or "") or "I reached my step limit on this task."
        except Exception:
            summary = "I reached my step limit on this task — tell me to continue if there's more to do."
        BUS.emit("assistant", text=summary)
        messages.append({"role": "assistant", "content": summary})
        _persist_turn(messages)
    finally:
        BUS.emit("status", text="idle")
        BUSY.clear()


def _trim_messages(msgs, limit=300):
    """Cap conversation length without orphaning tool_call/tool pairs."""
    if len(msgs) <= limit:
        return msgs
    m = msgs[-limit:]
    while m and (m[0].get("role") == "tool"
                 or (m[0].get("role") == "assistant" and m[0].get("tool_calls"))
                 or (m[0].get("role") == "user" and str(m[0].get("content", "")).startswith("TOOL RESULT"))):
        m.pop(0)
    return m


def _persist_turn(messages):
    """Save the WHOLE turn — user message, every tool call and result, and the
    final answer — so the conversation is a true record. This is what lets a
    follow-up like 'it worked' be understood instead of triggering a redo."""
    with CONVO_LOCK:
        convo = current_convo()
        convo["messages"] = _trim_messages(list(messages))
        convo["updated"] = time.time()
        save_convos()


def _short(result):
    s = json.dumps(result.get("result", result.get("error", "")), default=str)
    return s[:4000]   # show plenty so you can see what SCARB saw/did


# ===========================================================================
# METAMORPHOSIS — SCARB molts. When enabled, it improves its OWN skills on its
# own initiative, with no prompt from you: picks a skill, makes it more robust
# or capable (or invents a small new one), validates it, keeps it, and logs
# what it taught itself. The scarab grows by molting; so does SCARB.
# ===========================================================================

SKILL_TOOLS = {"create_skill", "update_skill", "read_skill", "delete_skill", "list_skills"}
EVOLUTION = []   # [{t, summary, skills}]
EVOLUTION_PATH = os.path.join(MEMORY_DIR, "evolution.json")


def load_evolution():
    try:
        with open(EVOLUTION_PATH) as f:
            EVOLUTION.extend(json.load(f)[-200:])
    except Exception:
        pass


def log_evolution(summary, skills):
    entry = {"t": time.time(), "summary": summary[:400], "skills": skills}
    EVOLUTION.append(entry)
    try:
        with open(EVOLUTION_PATH, "w") as f:
            json.dump(EVOLUTION[-200:], f)
    except Exception:
        pass
    return entry


def molt_system():
    soul = read_doc("soul.md")
    skills = "\n".join(f"- {s['name']}: {s['description']}" for s in SKILLS.list()) or "(none yet)"
    return (
        "You are SCARB, MOLTING — improving yourself with nobody asking. The scarab "
        "grows by shedding its shell; this is you doing the same to your own abilities.\n\n"
        "Do ONE meaningful thing this molt:\n"
        "• take an existing skill and make it more robust or more capable (handle bad/missing "
        "args, add an obviously-useful option, fix a latent bug, generalize it), OR\n"
        "• add ONE small, genuinely useful, SELF-CONTAINED skill.\n\n"
        "HARD LIMITS: use ONLY these tools — read_skill, list_skills, create_skill, update_skill. "
        "Skills you write must be pure Python standard library and SAFE: no shell, no network, no "
        "file deletion, no controlling apps. Don't delete skills. Read a skill before you rewrite it. "
        "Make a real improvement, not a cosmetic one.\n\n"
        "When done, reply with ONE short sentence (no tool call) describing what you improved and why — "
        "written as 'I …'.\n\n"
        f"SOUL\n{soul}\n\nYOUR SKILLS\n{skills}\n"
    )


def model_ready():
    p = provider_for("cloud")[0]
    if p == "ollama":
        return bool(list_ollama_models())
    return bool(key_for(p))


def molt_once():
    """One autonomous self-improvement pass."""
    if BUSY.is_set() or not model_ready():
        return
    BUSY.set()
    try:
        BUS.emit("molt_start")
        before = set(SKILLS.skills.keys())
        touched, summary = [], ""
        system = molt_system()
        messages = [{"role": "user", "content": "Molt now. Improve yourself."}]
        native = provider_for("cloud")[0] != "anthropic"
        specs = [s for s in tool_specs() if s["function"]["name"] in SKILL_TOOLS] if native else None
        for _ in range(8):
            try:
                msg = openai_message(system, messages, "cloud", specs) if native \
                    else {"content": llm_chat(system, messages, kind="cloud")}
            except LLMError as e:
                BUS.emit("molt_done", ok=False, text="couldn't molt: " + friendly_error(e, "cloud"))
                return
            content = strip_thinking(msg.get("content") or "")
            tcs = msg.get("tool_calls") or []
            if tcs:
                messages.append({"role": "assistant", "content": content or None, "tool_calls": tcs})
                for tc in tcs:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    raw = fn.get("arguments", "{}")
                    try:
                        args = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                    except Exception:
                        args = {}
                    if name not in SKILL_TOOLS:
                        res = {"ok": False, "error": "during a molt you may only use skill tools"}
                    else:
                        BUS.emit("action", tool=name, args=args)
                        res = dispatch(name, args)
                        BUS.emit("result", tool=name, ok=bool(res.get("ok", True)), result=_short(res))
                        if name in ("create_skill", "update_skill") and res.get("ok") and args.get("name"):
                            touched.append(args["name"])
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                     "content": json.dumps(res)[:4000]})
                continue
            action = extract_action(content)
            if action and action.get("tool") in SKILL_TOOLS:
                name = action["tool"]; args = action.get("args", {})
                BUS.emit("action", tool=name, args=args)
                res = dispatch(name, args)
                BUS.emit("result", tool=name, ok=bool(res.get("ok", True)), result=_short(res))
                if name in ("create_skill", "update_skill") and res.get("ok") and args.get("name"):
                    touched.append(args["name"])
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": "TOOL RESULT:\n" + json.dumps(res)[:4000]})
                continue
            summary = content
            break
        new = list(set(SKILLS.skills.keys()) - before)
        touched = list(dict.fromkeys(touched + new))
        if touched or summary:
            entry = log_evolution(summary or ("Refined " + ", ".join(touched)),
                                  touched or ["(no change)"])
            BUS.emit("molt", **entry)
        BUS.emit("molt_done", ok=True, text=summary or "molt complete", skills=touched)
    finally:
        BUSY.clear()


def molt_loop():
    """Background heartbeat: molt every so often while metamorphosis is on."""
    while True:
        time.sleep(max(120, int(CONFIG.get("molt_interval", 1200))))
        if CONFIG.get("molt") and not BUSY.is_set():
            try:
                molt_once()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# HTTP server — serves the UI and the API, streams events over SSE.
# ---------------------------------------------------------------------------

def authed(handler):
    if not CONFIG["token"]:
        return True
    supplied = handler.headers.get("X-Scarb-Token", "")
    if supplied == CONFIG["token"]:
        return True
    qs = handler.path.split("token=")
    return len(qs) > 1 and qs[1].split("&")[0] == CONFIG["token"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/" or path == "/index.html":
            return self._serve_file("index.html", "text/html; charset=utf-8")
        if path == "/app.js":
            return self._serve_file("app.js", "text/javascript; charset=utf-8")
        if path == "/style.css":
            return self._serve_file("style.css", "text/css; charset=utf-8")
        if path == "/manifest.json":
            return self._serve_file("manifest.json", "application/manifest+json")
        if path == "/api/ping":
            # Unauthenticated: lets the UI learn whether a token is required
            # before it tries anything, so it never guesses wrong.
            return self._send(200, {"ok": True, "needs_token": bool(CONFIG["token"]),
                                    "version": VERSION})
        if path == "/api/state":
            if not authed(self):
                return self._send(401, {"error": "bad token"})
            with CONVO_LOCK:
                convo = current_convo()
                history = convo["messages"][-80:]
                convo_id, convo_title = convo["id"], convo["title"]
                summaries = convo_summaries()
            return self._send(200, {
                "version": VERSION,
                "skills": SKILLS.list(),
                "identity": read_doc("identity.md"),
                "soul": read_doc("soul.md"),
                "history": history,
                "conversation_id": convo_id,
                "conversation_title": convo_title,
                "conversations": summaries,
                "provider": provider_for("cloud")[0],
                "model": provider_for("cloud")[1],
                "local_model": CONFIG["local_model"],
                "molt": bool(CONFIG.get("molt")),
                "evolution": EVOLUTION[-40:],
                "busy": BUSY.is_set(),
            })
        if path == "/api/evolution":
            if not authed(self):
                return self._send(401, {"error": "bad token"})
            return self._send(200, {"evolution": EVOLUTION[-100:], "molt": bool(CONFIG.get("molt"))})
        if path == "/api/voices":
            if not authed(self):
                return self._send(401, {"error": "bad token"})
            return self._send(200, {"voices": elevenlabs_voices()})
        if path == "/api/screen":
            if not authed(self):
                return self._send(401, {"error": "bad token"})
            qs = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            sid = (qs.get("id", [""])[0])
            if sid and sid.isdigit():
                shot = os.path.join(SHOTS_DIR, sid + ".png")
            else:
                shot = os.path.join(MEMORY_DIR, "screen.png")
            try:
                with open(shot, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                self._send(404, {"error": "no screenshot yet"})
            return
        if path == "/api/conversations":
            if not authed(self):
                return self._send(401, {"error": "bad token"})
            with CONVO_LOCK:
                return self._send(200, {"conversations": convo_summaries()})
        if path == "/api/config":
            if not authed(self):
                return self._send(401, {"error": "bad token"})
            p = CONFIG["provider"]
            return self._send(200, {
                "provider": p,
                "model": model_for(p) if p != "ollama" else (model_for("ollama") or CONFIG["local_model"]),
                "local_model": CONFIG["local_model"],
                "local_base_url": CONFIG["local_base_url"],
                "has_key": bool(key_for(p)),
                "keys_present": {prov: bool(key_for(prov)) for prov in PROVIDERS},
                "models": dict(CONFIG["models"]),
                "default_models": DEFAULT_MODELS,
                "providers": PROVIDERS,
                "has_eleven": bool(CONFIG.get("eleven_key")),
                "eleven_voice": CONFIG.get("eleven_voice", ""),
            })
        if path == "/api/ollama":
            if not authed(self):
                return self._send(401, {"error": "bad token"})
            models = list_ollama_models()
            return self._send(200, {"running": bool(models), "models": models,
                                    "host": ollama_host()})
        if path == "/api/models":
            if not authed(self):
                return self._send(401, {"error": "bad token"})
            qs = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            provider = (qs.get("provider", [CONFIG["provider"]])[0])
            try:
                return self._send(200, {"ok": True, "provider": provider,
                                        "models": fetch_models(provider)})
            except Exception as e:
                return self._send(200, {"ok": False, "error": str(e)[:300]})
        if path == "/events":
            return self._serve_events()
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if not authed(self):
            return self._send(401, {"error": "bad token"})
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}
        if path == "/api/send":
            message = str(body.get("message", "")).strip()
            kind = "local" if body.get("local") else "cloud"
            if not message:
                return self._send(400, {"error": "empty message"})
            threading.Thread(target=run_turn, args=(message, kind), daemon=True).start()
            return self._send(200, {"ok": True})
        if path == "/api/stop":
            CANCEL.set()
            BUS.emit("status", text="idle")
            return self._send(200, {"ok": True})
        if path == "/api/tts":
            # Speak text with ElevenLabs if a key is set; else 204 → the client
            # uses the browser's free built-in voice.
            audio = elevenlabs_tts(str(body.get("text", "")))
            if audio:
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(audio)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(audio)
                return
            return self._send(204, b"")
        if path == "/api/molt":
            # Toggle metamorphosis, and/or molt right now so you can watch it.
            if "enabled" in body:
                CONFIG["molt"] = bool(body["enabled"])
                save_config()
                BUS.emit("molt_config", enabled=CONFIG["molt"])
            if body.get("now") or body.get("enabled"):
                if not model_ready():
                    return self._send(200, {"ok": False, "molt": CONFIG["molt"],
                                            "error": "connect a model in Setup first"})
                threading.Thread(target=molt_once, daemon=True).start()
            return self._send(200, {"ok": True, "molt": bool(CONFIG.get("molt"))})
        if path == "/api/save_doc":
            name = body.get("name")
            if name not in ("identity.md", "soul.md"):
                return self._send(400, {"error": "name must be identity.md or soul.md"})
            with open(os.path.join(HERE, name), "w") as f:
                f.write(body.get("content", ""))
            BUS.emit("doc", name=name)
            return self._send(200, {"ok": True})
        if path == "/api/reset" or path == "/api/conversation":
            # action: new (default) | load | delete
            action = body.get("action", "new")
            with CONVO_LOCK:
                if action == "load":
                    cid = body.get("id")
                    if any(c["id"] == cid for c in CONVOS):
                        CURRENT_ID[0] = cid
                    save_convos()
                    convo = current_convo()
                    result = {"ok": True, "id": convo["id"], "title": convo["title"],
                              "messages": convo["messages"][-80:]}
                elif action == "delete":
                    cid = body.get("id")
                    CONVOS[:] = [c for c in CONVOS if c["id"] != cid]
                    if not CONVOS:
                        new_convo()
                    if not any(c["id"] == CURRENT_ID[0] for c in CONVOS):
                        CURRENT_ID[0] = CONVOS[-1]["id"]
                    save_convos()
                    result = {"ok": True, "conversations": convo_summaries()}
                else:  # new
                    convo = new_convo()
                    save_convos()
                    result = {"ok": True, "id": convo["id"]}
            BUS.emit("reset")
            return self._send(200, result)
        if path == "/api/config":
            # Which provider these edits apply to (defaults to the active one).
            if "provider" in body and str(body["provider"]).strip():
                CONFIG["provider"] = str(body["provider"]).strip()
            p = CONFIG["provider"]
            # Keys and models are stored per provider, so they never clash.
            if "api_key" in body and str(body["api_key"]).strip():
                CONFIG["keys"][p] = str(body["api_key"]).strip()
            if body.get("clear_key"):
                CONFIG["keys"].pop(p, None)
            if "model" in body:
                m = str(body["model"]).strip()
                if m:
                    CONFIG["models"][p] = m
                else:
                    CONFIG["models"].pop(p, None)
            for k in ("local_model", "local_base_url"):
                if k in body and str(body[k]).strip():
                    CONFIG[k] = str(body[k]).strip()
            if "eleven_key" in body and str(body["eleven_key"]).strip():
                CONFIG["eleven_key"] = str(body["eleven_key"]).strip()
            if body.get("clear_eleven"):
                CONFIG["eleven_key"] = ""
            if "eleven_voice" in body:
                CONFIG["eleven_voice"] = str(body["eleven_voice"]).strip()
            save_config()
            BUS.emit("config", provider=CONFIG["provider"], model=provider_for("cloud")[1])
            return self._send(200, {"ok": True, "model": provider_for("cloud")[1]})
        if path == "/api/test_model":
            kind = "local" if body.get("local") else "cloud"
            try:
                reply = llm_chat("You are a connectivity check. Reply with the single word: ok.",
                                 [{"role": "user", "content": "say ok"}], kind=kind, max_tokens=16)
                return self._send(200, {"ok": True, "reply": reply.strip()[:80],
                                        "model": provider_for(kind)[1]})
            except Exception as e:
                return self._send(200, {"ok": False, "error": str(e)[:300]})
        return self._send(404, {"error": "not found"})

    def _serve_file(self, name, ctype):
        try:
            with open(os.path.join(WEB_DIR, name), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self._send(404, "not found", "text/plain")

    def _serve_events(self):
        if not authed(self):
            return self._send(401, {"error": "bad token"})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q = BUS.subscribe()
        try:
            for event in BUS.log[-30:]:
                self._write_event(event)
            while True:
                try:
                    event = q.get(timeout=20)
                    self._write_event(event)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            BUS.unsubscribe(q)

    def _write_event(self, event):
        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
        self.wfile.flush()


def tailscale_state(port):
    """Returns ('url', http://100.x:port) if connected, ('login', msg) if
    installed-but-logged-out, or (None, None) if not installed."""
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True,
                             text=True, timeout=5)
        ip = "".join(l for l in out.stdout.strip().split("\n") if l.startswith("100."))
        if ip:
            return ("url", f"http://{ip}:{port}")
        blob = (out.stdout + out.stderr).lower()
        if "needslogin" in blob or "logged out" in blob:
            return ("login", "Tailscale is installed but logged out — run `tailscale up` and log in, then restart SCARB.")
        return ("login", "Tailscale is installed but has no IP yet — run `tailscale up`.")
    except FileNotFoundError:
        return (None, None)
    except Exception:
        return (None, None)


def hold_awake():
    """While SCARB is running, keep the Mac from idle-sleeping so it stays
    reachable over Tailscale (e.g. with the lid closed). `caffeinate` is tied to
    our PID, so it stops automatically when SCARB does. For lid-closed on
    battery you also need Amphetamine's closed-display mode (the amphetamine
    skill can enable it) and, ideally, AC power."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def ensure_tailscale():
    """Best-effort: keep Tailscale connected so the Mac stays reachable (e.g.
    with the lid closed). If it's stopped/down, bring it up; if logged out, we
    can't fix that automatically — that needs a one-time `tailscale up` login."""
    try:
        st = subprocess.run(["tailscale", "status"], capture_output=True, text=True, timeout=6)
        blob = (st.stdout + st.stderr).lower()
        if "100." in st.stdout and "stopped" not in blob:
            return  # already connected
        if "logged out" in blob or "needslogin" in blob:
            return  # needs interactive login; can't auto-fix
        # Stopped or not connected → try to bring it up (non-blocking-ish).
        subprocess.run(["tailscale", "up", "--accept-routes"], capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def enable_tailscale_serve(port):
    """Expose SCARB over HTTPS on the Mac's MagicDNS name via Tailscale Serve.
    This gives a valid TLS cert (no warnings), which browsers require before
    they'll grant microphone access — so the mic works in Safari/Chrome, not
    just the app. Returns the https URL, or None. Best-effort."""
    try:
        out = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=6)
        name = ""
        try:
            name = json.loads(out.stdout).get("Self", {}).get("DNSName", "").rstrip(".")
        except Exception:
            pass
        # idempotent: point https:443 at our local http port
        subprocess.run(["tailscale", "serve", "--bg", "--https=443",
                        f"http://127.0.0.1:{port}"], capture_output=True, text=True, timeout=15)
        return f"https://{name}" if name else None
    except Exception:
        return None


def tailscale_keepalive():
    while True:
        try:
            ensure_tailscale()
        except Exception:
            pass
        time.sleep(60)


def local_ip():
    try:
        for iface in ("en0", "en1"):
            r = subprocess.run(["ipconfig", "getifaddr", iface], capture_output=True, text=True, timeout=3)
            if r.stdout.strip():
                return r.stdout.strip()
    except Exception:
        pass
    return None


def make_server(host, port):
    """Serve on BOTH IPv4 and IPv6. Tailscale gives the Mac a 100.x (IPv4) and
    an fd7a: (IPv6) address, and phones often prefer IPv6 — if we only bound
    IPv4, an IPv6 client would hit a closed port and the app would look
    unreachable even though Tailscale is connected."""
    import socket

    class DualStackServer(ThreadingHTTPServer):
        address_family = socket.AF_INET6

        def server_bind(self):
            # accept both IPv6 and IPv4-mapped connections on one socket
            try:
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            except (AttributeError, OSError):
                pass
            super().server_bind()

    try:
        # "::" listens on all IPv6 + (with V6ONLY off) all IPv4 too
        bind_host = "::" if host in ("0.0.0.0", "::", "") else host
        return DualStackServer((bind_host, port), Handler)
    except OSError:
        # fall back to IPv4-only if dual stack isn't available
        return ThreadingHTTPServer((host, port), Handler)


def main():
    load_convos()
    load_evolution()
    hold_awake()
    ensure_tailscale()
    threading.Thread(target=molt_loop, daemon=True).start()
    threading.Thread(target=tailscale_keepalive, daemon=True).start()
    server = make_server(CONFIG["host"], CONFIG["port"])
    port = CONFIG["port"]
    print(f"\n  ✦ SCARB {VERSION} — self-improving assistant")
    print(f"    local:     http://127.0.0.1:{port}")
    lan = local_ip()
    if lan:
        print(f"    wifi:      http://{lan}:{port}   (same-WiFi devices, e.g. your phone)")
    kind, msg = tailscale_state(port)
    if kind == "url":
        print(f"    tailscale: {msg}   (open this on your phone, anywhere)")
        https = enable_tailscale_serve(port)
        if https:
            print(f"    🔊 https:   {https}   (use THIS in a browser — mic + install-to-home work)")
    elif kind == "login":
        print(f"    tailscale: {msg}")
    prov, model, _, key = provider_for("cloud")
    print(f"    cloud:     {prov} / {model}" + ("" if key or prov == "ollama" else "  (no SCARB_API_KEY set)"))
    print(f"    local:     ollama / {CONFIG['local_model']}")
    if not CONFIG["token"]:
        print("    ⚠  no SCARB_TOKEN set — anyone on your network can use SCARB. Set one before exposing it.")
    else:
        print("    🔒 token auth on")
    print(f"    skills:    {len(SKILLS.skills)} loaded")
    print("    ☕ holding the Mac awake while SCARB runs. For LID-CLOSED reachability:")
    print("       keep it on AC power + turn on Amphetamine's closed-display mode")
    print("       (ask SCARB: \"amphetamine for the day with lid_closed\"), or run once:")
    print("       sudo pmset -a disablesleep 1   (undo: sudo pmset -a disablesleep 0)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  scarab sleeps.")


if __name__ == "__main__":
    main()
