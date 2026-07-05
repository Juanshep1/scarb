# SCARB — the iOS app

A native iPhone/iPad app for SCARB. The brain, skills, memory, and computer-use
all stay on your Mac (that's the whole point — that's where your files and apps
are); this app is a resilient native shell that reaches the SCARB server from
anywhere and gives you the full UI.

## The "always listens to your computer" part
Your Mac is reachable by more than one route: **Tailscale** (works anywhere) and
your **local network** (works on the same WiFi even when Tailscale is down). The
app keeps a list of those routes, probes them all at once, connects to whichever
answers, and re-checks on a timer — so if Tailscale drops, it **fails over to the
local network automatically**, and if the current route dies it finds another.
As long as *any* path to your Mac is up, the app finds it.

## Build it
```bash
brew install xcodegen        # once
cd app/ios
xcodegen generate
open SCARB.xcodeproj          # pick a simulator or your iPhone, press Run
```

## First run
Open **Settings** (gear, top-right) and set your routes:
- **Tailscale**: your Mac's tailnet IP — run `tailscale ip -4` on the Mac (100.x.y.z).
- **WiFi**: your Mac's local IP — `ipconfig getifaddr en0` (10.x / 192.168.x).
- **Port**: 8787 (default). **Token**: only if you set `SCARB_TOKEN` on the server.

Make sure `python3 scarb.py` is running on the Mac. The app shows a live
connection pill (searching / connected · which route / offline) and reconnects
on its own.

## Why a WKWebView shell?
It loads the real SCARB web UI, so the app has **every** feature — chat, the live
skills panel, conversation history, model setup — with zero duplication, and any
improvement to the server UI shows up in the app instantly. The native layer is
the connection resilience, the settings, and the shell. See
[../../IOS_APP.md](../../IOS_APP.md) for where to take it next (Live Activities,
push, Siri Shortcuts, on-device fallback model).
