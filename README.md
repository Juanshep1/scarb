# 🪲 SCARB — a self-improving assistant

The scarab rolls its world forward and is reborn from it. **SCARB** does real
tasks on your own machine, and when it meets a task it can't do yet, it **writes
a new skill** to do it, tests it, keeps it, and gets a little more capable. It's
shaped by two files it reads every turn — `identity.md` (what it does) and
`soul.md` (who it is) — and it can read and improve its own code.

One file, Python standard library only. Runs a **cloud** model (Anthropic or any
OpenAI-compatible endpoint) **and/or a local** one (Ollama). Serves a live web UI
— chat plus a skills panel that fills in **in real time** as SCARB builds itself
— that works on **desktop and your phone over Tailscale**.

![it grows itself](https://img.shields.io/badge/skills-self--written-e8c274) ![stdlib only](https://img.shields.io/badge/deps-none-4fd6a0)

## Run it

```bash
git clone https://github.com/Juanshep1/scarb.git
cd scarb
python3 scarb.py
```

Open the printed URL. That's it — no packages to install.

### Point it at a model

SCARB defaults to a **local Ollama** model. To use a cloud model, set a few env
vars (each is optional):

```bash
# Cloud (pick one provider)
export SCARB_PROVIDER=anthropic          # anthropic | openai | openrouter | ollama
export SCARB_API_KEY=sk-...              # your key
export SCARB_MODEL=claude-sonnet-4-6     # optional; sensible default per provider

# Local fallback (used for the "local" toggle, and if the cloud is unreachable)
export SCARB_LOCAL_MODEL=llama3.1
export SCARB_LOCAL_BASE_URL=http://127.0.0.1:11434/v1   # ollama's OpenAI API

python3 scarb.py
```

Flip the **local** switch in the composer to run a single turn on your local
model — private, free, offline. If a cloud turn fails (no signal, key expired),
SCARB automatically retries once on the local model.

## Use it from your phone (Tailscale)

SCARB binds to `0.0.0.0`, so any device on your [Tailscale](https://tailscale.com)
network can reach it. When it starts it prints your tailnet URL:

```
    tailscale: http://100.x.y.z:8787   (open this on your phone)
```

Open that on your phone and you have the same SCARB — same brain, same skills,
same memory. Because SCARB **runs on your desktop**, asking it from your phone to
do something on the desktop *just works*: "restart the render", "pull the repo
and run the tests", "add a cron job" — it happens on the machine it lives on.

**Set a token before you expose it.** With a token, every client must supply it:

```bash
export SCARB_TOKEN=$(openssl rand -hex 16)
python3 scarb.py
```

The UI asks for the token once and remembers it. Without a token, anyone on your
network can use SCARB — fine for a laptop on your desk, not for a shared tailnet.

## How it grows

SCARB works in steps. Each turn it plans, calls a **tool**, reads the result,
and continues until the task is actually done. Its tools are:

- **Its skills** — everything in `skills/`, each a small `run(args)` function,
  callable by name.
- **`create_skill` / `update_skill`** — when no skill fits, SCARB writes one (a
  standard-library Python module), which is validated and hot-loaded on the
  spot. If it errors, SCARB sees the message and fixes it. It never solves the
  same problem from scratch twice. **You watch this happen live in the Skills
  panel.**
- **`read_file` / `write_file` / `run_shell`** — touch the real machine.
- **`read_self`** — read its own `scarb.py`, `identity.md`, or `soul.md`, so it
  can improve itself and fix its own code.

A skill is just a file:

```python
# skills/reverse_text.py
# name: reverse_text
# description: Reverse a string. args {"text": "..."}
def run(args):
    return {"ok": True, "result": str(args.get("text", ""))[::-1]}
```

## Its soul and identity

Two Markdown files steer everything, and you can edit them right in the UI
(Identity / Soul tabs):

- **`identity.md`** — what SCARB is and its goals (do the task, turn effort into
  a permanent skill, get better over time, stay trustworthy).
- **`soul.md`** — who it is while it works (steady, honest, frugal, asks before
  anything destructive).

Change them and the next turn thinks differently. Its long-term notes live in
`memory/`.

## Layout

```
scarb.py        the whole engine: LLM client, agent loop, skills, HTTP + SSE
identity.md     what SCARB does
soul.md         who SCARB is
skills/         its growable abilities (SCARB writes most of these itself)
memory/         long-term notes
web/            the UI (index.html, app.js, style.css)
```

## Safety

SCARB runs commands and edits files on your machine — that's the point of a
personal agent — and its soul tells it to **ask before anything destructive,
irreversible, or far-reaching**. Run it on machines you own, keep a token on it,
and read what it proposes. It's yours; it does what you tell it.

— part of the *build-your-own-x* ecosystem alongside
[Vanta](https://github.com/Juanshep1/vanta), [vcode](https://github.com/Juanshep1/vcode),
and [Harbor](https://github.com/Juanshep1/harbor).
