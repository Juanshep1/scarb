# SCARB — changelog

Everything SCARB can do, and every fix, in the order it happened. SCARB is a
self-improving assistant that runs on your own machine, does real tasks, and
writes new skills when it can't do something yet.

## Core (0.1)
- **Single-file agent** (`scarb.py`, standard library only): an LLM client, an
  agent loop, a skills engine, an HTTP server, and a live event stream (SSE).
- **Cloud or local models**: Anthropic, OpenAI, OpenRouter, Ollama Cloud, and
  local Ollama. A per-turn **local** toggle, and an automatic fall-back to a
  local model if the cloud is unreachable.
- **Skills** are its growable abilities — small `run(args)` files in `skills/`.
  When no skill fits a task, SCARB writes one with `create_skill`, which is
  validated and hot-loaded on the spot. It never solves the same problem twice.
- **soul.md + identity.md** shape who it is and what it does; both are read on
  every turn and editable right in the UI.
- **Live web UI**: chat plus a skills panel that fills in as SCARB builds
  itself. Works on desktop and phone over **Tailscale**, with token auth.

## Features added since

### In-UI model setup
Add API keys, pick provider and model, and connect a local model in one tap —
no env vars, no restarts. **Detect Ollama** lists your installed local models;
**Test connection** verifies any provider.

### Keys never clash
Every provider stores its **own** key and model (in `config.json`, gitignored),
so switching providers never sends one service's key to another. Old single-key
configs migrate automatically.

### Model dropdown + live refresh
The Setup model field is a dropdown that auto-loads each provider's full live
catalogue (OpenRouter's ~340 models, Ollama Cloud's list, etc.). ⟳ forces a
fresh pull.

### Computer use (macOS) — real sight, real clicks
The `computer` skill gives SCARB actual eyes: `{"action":"see"}` reads the
frontmost app's real on-screen buttons, menus, fields, and links **by name**
(with coordinates) via the Accessibility API. It then clicks the exact element,
works the menu bar, focuses apps, types, and presses shortcuts. Clicks land as
**real hardware-level CoreGraphics mouse events at the element's center**, so
they work on web content (video thumbnails, links, players) — not accessibility
"clicks" that web pages ignore. Supports double-click and raw-coordinate clicks.

### Amphetamine skill
Start/stop/toggle keep-awake sessions ("keep my Mac awake for 3 hours") via the
Amphetamine app's real AppleScript API.

### Metamorphosis (🦋) — autonomous self-improvement
The scarab grows by molting; so does SCARB. Flip the 🦋 toggle and SCARB, on its
own initiative with no prompt, picks one of its skills, makes it more robust or
capable (or invents a small new one), validates it, keeps it, and logs what it
taught itself — shown live and saved to an evolution log. Molts may only touch
skills and must write safe, self-contained code (no shell, network, deletion,
or app control); opt-in, default off.

### Voice
- **Talk to it** with the 🎤: free browser speech recognition on the web, native
  on-device speech (`SFSpeechRecognizer`) in the iOS app.
- **Hear it** with 🔈: a natural OS voice for free by default, or **ElevenLabs**
  if you add a key (the server proxies TTS so the key stays on your machine).

### Conversations + persistent memory
Every chat is kept and browsable — tap the **scarab icon** for the history
drawer, ＋ for a new one. Facts SCARB stores with `remember` are injected into
its prompt every turn, so it recalls across sessions. On mobile the Chat/Skills
tabs are one swipe away.

### Native iOS app (`app/ios`)
A SwiftUI app that loads the full SCARB UI (so it has every feature) with a
resilient **connection manager**: it probes Tailscale *and* your local network,
connects to whichever answers, and fails over automatically — so if Tailscale
drops it still reaches your Mac. Native mic and audio built in.

## Full-control upgrade (10×)
SCARB now stands on its own as a full agent on your machine — built for use over
Tailscale from anywhere.

- **Terminal** — `run_shell` is a real terminal now: the **working directory
  persists** between commands (`cd` carries over), so it navigates and works
  like a terminal you keep open. Full power, any command.
- **Computer use, expanded** — the `computer` skill gained `read` (read the
  visible text of a window/page), `scroll`, `drag`, `rightclick`, `move`,
  `window` (minimize/close/fullscreen/list), and `clipboard` read/write, on top
  of see/click/menu/type/key/screenshot. Clicks are real hardware clicks that
  work on web content.
- **Internet** — the new `web` skill: `search` the web, `fetch` a page's text,
  or get a quick `answer`. SCARB is no longer limited to its training data.
- **Full control, no friction** — on your own Mac SCARB acts decisively without
  asking permission for ordinary actions; it only pauses on the genuinely
  catastrophic and irreversible.
- **See everything it does** — computer-use results show much more detail in the
  chat, and when SCARB takes a **screenshot it appears inline** so you watch what
  it's looking at.
- **Hands-free conversation** — a 🗣️ mode: tap once, talk, SCARB auto-detects
  when you stop, sends, speaks its reply, and starts listening again — a natural
  back-and-forth with no buttons, on web and in the app.

## Fixes
- **Skills actually build** — the agent used to only parse tool actions inside
  ```` ```json ```` fences; weaker models emit bare JSON, so nothing ran and the
  model would fabricate success. Now every provider except Anthropic uses
  **native tool-calling** (structured tool calls that can't be faked as prose),
  with a prose-JSON fallback, plus a hard rule: SCARB may only report what a
  tool result confirmed.
- **Skill edits take effect** — an edited skill used to keep running its old
  code (Python's bytecode cache saw the same mtime second). Skills now compile
  from source every load.
- **Self-improving skills** — when a skill errors mid-use, SCARB is nudged to
  repair the skill itself right then, not just work around it.
- **Model errors are actionable** — "Ollama isn't running / add a key / bad key"
  instead of raw socket errors.
- **Networking** — the server always bound `0.0.0.0`; the blocker was Tailscale
  being logged out. Startup now prints a same-WiFi URL and Tailscale status.
- **Config & conversation persist** — API keys and chats survive restarts.
- **Mobile UI is static** — 16px inputs (no focus-zoom) and a pinned layout, so
  nothing drifts; Chat/Skills tabs visible by default.
- **Agent memory across a turn** — the loop used to save only the final answer,
  and to save *nothing* when it hit its step limit. So after a long task ended
  at the limit, a follow-up like "it worked" landed in a conversation with no
  record, and SCARB would redo the task. Now the **whole turn is persisted**
  (the user message, every tool call and result, and the final answer), the
  step limit **closes with a real saved summary** instead of a dead-end, the
  step budget is larger, and SCARB is told not to redo a task the human has
  confirmed or told it to leave.
