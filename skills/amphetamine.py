# name: amphetamine
# description: Keep this Mac awake with the Amphetamine app. args {"action":"start","hours":3} or {"minutes":90}; {"action":"stop"}; {"action":"status"}; {"action":"toggle","hours":2} (starts if idle, stops if a session is running). Omit hours/minutes for an indefinite session. Add "allow_display_sleep": true to let the screen sleep while the Mac stays awake.
import subprocess


def _osa(script):
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)
    return p.returncode == 0, (p.stdout + p.stderr).strip()


def _is_active():
    ok, out = _osa('tell application "Amphetamine" to return session is active')
    return ok and out.strip().lower().startswith("true")


def _remaining():
    ok, out = _osa('tell application "Amphetamine" to return session time remaining')
    try:
        return int(out.strip())
    except Exception:
        return None


def _fmt_remaining(secs):
    if secs is None:
        return ""
    if secs == 0:
        return " (indefinite)"
    if secs < 0:
        return ""  # trigger/app/date-based or none
    h, m = secs // 3600, (secs % 3600) // 60
    if h:
        return f" ({h}h {m}m left)"
    return f" ({m}m left)"


def _start(args):
    hours = args.get("hours")
    minutes = args.get("minutes")
    duration = args.get("duration")
    dsa = "true" if args.get("allow_display_sleep") else "false"

    if hours is not None:
        dur, interval, label = int(round(float(hours))), "hours", f"{hours}h"
    elif minutes is not None:
        dur, interval, label = int(round(float(minutes))), "minutes", f"{minutes}m"
    elif duration is not None:
        dur, interval, label = int(round(float(duration))), "minutes", f"{duration}m"
    else:
        dur, interval, label = 0, 0, "indefinite"   # Amphetamine: 0/0 = infinite

    opts = f"{{duration:{dur}, interval:{interval}, displaySleepAllowed:{dsa}}}"
    ok, out = _osa(f'tell application "Amphetamine" to start new session with options {opts}')
    if not ok:
        return {"ok": False, "error": out or "could not start an Amphetamine session"}
    screen = "screen may sleep" if dsa == "true" else "screen stays on"
    return {"ok": True, "result": f"Amphetamine session started for {label} ({screen})."}


def _stop():
    if not _is_active():
        return {"ok": True, "result": "no Amphetamine session was running."}
    ok, out = _osa('tell application "Amphetamine" to end session')
    if not ok:
        return {"ok": False, "error": out or "could not end the session"}
    return {"ok": True, "result": "Amphetamine session ended — this Mac can sleep normally now."}


def run(args):
    action = str(args.get("action", "toggle")).lower()
    if action == "status":
        if _is_active():
            return {"ok": True, "result": "awake" + _fmt_remaining(_remaining())}
        return {"ok": True, "result": "no session — this Mac sleeps normally"}
    if action == "start":
        return _start(args)
    if action in ("stop", "end", "off"):
        return _stop()
    if action == "toggle":
        return _stop() if _is_active() else _start(args)
    return {"ok": False, "error": "action must be start, stop, toggle, or status"}
