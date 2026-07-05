# Making SCARB a native iOS app

SCARB today is a Python server + a web UI you reach over Tailscale. That already
works great on a phone. This doc is a roadmap for the people (you, later) who
want to wrap it in a real iOS app and add the things only a native app can do.

There are two honest architectures. Pick based on what you want.

## Architecture A — "SCARB Remote" (thin native client) ✅ recommended first
A SwiftUI app that is a beautiful native shell around the SCARB server running
on your Mac (reached over Tailscale). The brain, skills, tools, and computer-use
stay on the Mac — which is the whole point, since that's where your files, apps,
and Amphetamine live.

- **WKWebView shell** — load `http://<tailnet-ip>:8787`, but replace the web
  chrome with native SwiftUI: a real navigation bar, a native conversation list
  (backed by `/api/conversations`), and a native composer.
- **Native chat** — talk to the existing JSON API directly (`/api/send`,
  `/api/state`, SSE `/events`) from Swift with `URLSession` + `EventSource`, and
  render messages/steps/skills in SwiftUI. You already have every endpoint.
- **Keychain** for the access token (`SCARB_TOKEN`) instead of localStorage.
- **Tailscale**: ship with the Tailscale iOS app as a dependency (or Network
  Extension), or just document "install Tailscale, then open the app."
- **Live Activities / Dynamic Island** — show a running task ("SCARB is building
  a skill…") and long tool runs (a 3-hour Amphetamine timer!) on the lock screen.
- **Push notifications** — have the server hit APNs when a task finishes or needs
  your approval (see "approvals" below). Add a `/api/push/register` endpoint.
- **Share Sheet extension** — share a link/photo/text into SCARB as a task
  ("summarize this", "save this to memory").
- **Siri Shortcuts / App Intents** — "Hey Siri, ask SCARB to start a 2-hour
  focus session." Each maps to a `/api/send` call.
- **Widgets** — a home-screen widget showing the last answer, active skills, or
  whether a keep-awake session is running.

This is the fastest path to something that feels like a real app, because the
hard part (the agent) already exists and runs where it should.

## Architecture B — "SCARB on-device" (self-contained) 🚀 ambitious
Run the whole assistant on the phone. Much harder, but fully offline and private.

- **Local model on device** — use **MLX** (Apple's array framework) or
  **llama.cpp** to run a small model (Qwen2.5-3B/7B, Llama-3.2) on the Neural
  Engine/GPU. Wire it to the same tool-calling loop.
- **Port the agent loop to Swift** — reimplement `run_turn`, the tool dispatch,
  and the skills engine. Skills would be sandboxed scripts; on iOS you can't
  `exec` arbitrary Python, so skills become either (a) a fixed native toolbox or
  (b) a small embedded scripting runtime (JavaScriptCore, or a Python via
  Pyodide/wasm in a WKWebView like the Vanta Pocket app does).
- **Tools become native** — `EventKit` (calendar/reminders), `Contacts`,
  `HealthKit`, `CoreLocation`, `Shortcuts`, file access via the Files app,
  `MapKit`, camera/vision. "Computer use" on iOS is really "iOS use."
- **No AppleScript** — the macOS computer-use skills (Amphetamine, Notes, Safari)
  don't exist on iOS; those stay Mac-only. This is the strongest reason to keep
  Architecture A for controlling the desktop.

A good middle path: ship Architecture A, and let it *fall back* to a small
on-device model when the Mac is unreachable (the server already has a local/
cloud split; mirror that idea client-side).

## Concrete improvements worth doing (either architecture)

**Agent & safety**
- **Approvals**: before destructive/irreversible tools, the server emits an
  `approval` event and waits; the app shows a native "Allow / Deny" sheet. (Hook
  it into the soul's "ask before…" rule — make it enforced, not just prompted.)
- **Streaming tokens**: switch the LLM calls to streaming so answers appear word
  by word; emit `token` deltas over SSE.
- **Per-skill permissions**: mark skills that touch shell/files/apps and gate
  them.
- **Cost/usage meter**: track tokens per provider, show it in Settings.

**Skills**
- **Skill marketplace / sync**: push/pull skills to a git repo or iCloud so your
  phone and Mac share the same growing toolbox.
- **Scheduled skills**: cron-like triggers ("every night at 9pm, start a Drive
  Alive session") — Amphetamine already exposes Triggers via AppleScript.
- **Skill tests**: when SCARB writes a skill, have it also write a tiny self-test
  it must pass before the skill is kept.

**Memory**
- **Vector memory**: embed notes + past conversations for real recall instead of
  dumping all notes into the prompt. A small on-device embedding model works.
- **Auto-memory**: after each conversation, SCARB summarizes what's worth keeping
  and writes it to memory (with your ok).

**UI/UX**
- **Voice**: speech-to-text for input (native `SFSpeechRecognizer`), TTS for
  replies.
- **Rich tool results**: render screenshots, files, and tables inline instead of
  as JSON.
- **Multi-device presence**: show which device a message came from.

**Infra**
- **mDNS/Bonjour discovery** so the app finds the Mac without typing an IP.
- **HTTPS + real auth** (currently a shared token over Tailscale, which is fine
  for personal use; a public deployment needs TLS and per-device tokens).
- **A menu-bar Mac app** that runs the server, shows status, and manages the
  token — so "start SCARB" isn't a Terminal command.

## Endpoints already available to build against
```
GET  /api/state           full snapshot (skills, current convo, provider, model)
GET  /events              SSE stream of steps/skills/status (the live feed)
POST /api/send            {message, local?}  run a turn
GET  /api/conversations   list past chats
POST /api/conversation    {action:"new"|"load"|"delete", id?}
GET  /api/config          model/provider config (keys are never returned)
POST /api/config          set provider/key/model (per-provider, no clash)
GET  /api/models?provider=…   live model catalogue
GET  /api/ollama          detect local Ollama + its models
POST /api/save_doc        edit identity.md / soul.md
GET  /api/ping            unauthenticated: does the server need a token?
```
Everything the web UI does, a native app can do the same way. Start with
Architecture A — you'll have a real SCARB app on your phone in a weekend.
