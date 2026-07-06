# name: computer
# description: See and control this Mac. ALWAYS {"action":"see"} FIRST to get the real on-screen buttons/menus/fields/links (by name, with coordinates) before clicking — don't guess. Then {"action":"click","target":"<exact or partial name>"} clicks that element's real coordinate (works on web videos & links; add "double":1 to double-click). Or {"action":"click","x":120,"y":340} for a raw point. Also: {"action":"menu","path":["File","New Window"]}, {"action":"focus","app":"Safari"}, {"action":"apps"}, {"action":"type","text":"hi"}, {"action":"key","keys":"cmd+s"}, {"action":"screenshot"}. Needs macOS Accessibility permission for the app running SCARB.
import subprocess
import os
import ctypes

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _osa(script, timeout=25):
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    return p.returncode == 0, (p.stdout + p.stderr).strip()


def _frontmost():
    ok, out = _osa('tell application "System Events" to get name of first process whose frontmost is true')
    return out if ok else ""


def _q(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


# ---- SEE: enumerate what's actually on screen, so you never guess ----------

def _see(args):
    app = _frontmost()
    if not app:
        return {"ok": False, "error": "couldn't tell which app is frontmost (grant Accessibility permission)"}
    deep = "true" if args.get("deep") else "false"
    script = f'''
    set report to ""
    tell application "System Events"
      tell process "{_q(app)}"
        try
          set report to report & "WINDOWS: " & (name of windows as string) & linefeed
        end try
        try
          set report to report & "MENUS: " & (name of menu bar items of menu bar 1 as string) & linefeed
        end try
        if (count of windows) > 0 then
          set src to entire contents of window 1
          repeat with el in src
            try
              set r to (role description of el)
              set nm to ""
              try
                set nm to (name of el)
              end try
              if nm is missing value then set nm to ""
              if nm is "" then
                try
                  set nm to (value of el as string)
                end try
              end if
              if (r is in {{"button", "menu button", "pop up button", "checkbox", "radio button", "tab", "text field", "text area", "link", "menu item", "image"}}) and nm is not "" and nm is not "missing value" then
                set p to (position of el)
                set report to report & r & ": \\"" & nm & "\\" @ " & (item 1 of p) & "," & (item 2 of p) & linefeed
              end if
            end try
          end repeat
        end if
      end tell
    end tell
    return report
    '''
    ok, out = _osa(script, timeout=45)
    if not ok:
        return {"ok": False, "error": out or "couldn't read the screen (Accessibility permission?)"}
    lines = [l for l in out.splitlines() if l.strip() and '"missing value"' not in l][:200]
    return {"ok": True, "result": {"app": app, "elements": lines,
                                   "hint": "to click one, use {\"action\":\"click\",\"target\":\"<its name>\"} — it clicks the real coordinate, which works on web videos/links. Add \"double\":1 for a double-click."}}


# ---- CLICK: by element name (robust) or by coordinate ----------------------

def _click(args):
    if "x" in args and "y" in args:
        return _click_point(float(args["x"]), float(args["y"]), int(args.get("double", 0)))
    target = str(args.get("target", "")).strip()
    if not target:
        return {"ok": False, "error": "click needs a target name, or x and y"}
    app = _frontmost()
    # Find the element and return its GEOMETRY. We then click its center with a
    # real CoreGraphics mouse event — which web content (video thumbnails,
    # links, players) actually responds to, unlike an accessibility "click".
    script = f'''
    tell application "System Events" to tell process "{_q(app)}"
      set hits to {{}}
      try
        set hits to (every UI element of (entire contents of window 1) whose name is "{_q(target)}")
      end try
      if hits is {{}} then
        try
          set hits to (every UI element of (entire contents of window 1) whose name contains "{_q(target)}")
        end try
      end if
      if hits is {{}} then
        try
          set hits to (every UI element of (entire contents of window 1) whose value is "{_q(target)}")
        end try
      end if
      if hits is {{}} then error "no on-screen element named " & "{_q(target)}"
      set el to item 1 of hits
      set p to position of el
      set s to size of el
      return ((item 1 of p) as integer) & "," & ((item 2 of p) as integer) & "," & ((item 1 of s) as integer) & "," & ((item 2 of s) as integer)
    end tell
    '''
    ok, out = _osa(script, timeout=45)
    if not ok:
        return {"ok": False, "error": out + " — run action 'see' first to get exact names."}
    try:
        x, y, w, h = [int(v) for v in out.split(",")[:4]]
        cx, cy = x + w // 2, y + h // 2
    except Exception:
        # No geometry — fall back to an accessibility click.
        ok2, out2 = _osa(f'tell application "System Events" to tell process "{_q(app)}" to '
                         f'click (first UI element of (entire contents of window 1) whose name contains "{_q(target)}")')
        return ({"ok": True, "result": f"clicked '{target}'"} if ok2 else {"ok": False, "error": out2})
    res = _click_point(cx, cy, int(args.get("double", 0)))
    if res.get("ok"):
        res["result"] = f"clicked '{target}' at {cx},{cy}"
    return res


def _click_point(x, y, double=0):
    # CoreGraphics mouse events — no dependencies, works on any Mac, and web
    # pages treat these as real clicks. We move, then press/release; for a
    # double-click we set the click-state so players/thumbnails that need it work.
    import time
    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")

        class CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
        cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
        cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        cg.CFRelease.argtypes = [ctypes.c_void_p]
        pt = CGPoint(float(x), float(y))
        CLICK_STATE = 1   # kCGMouseEventClickState

        def post(etype, clicks=1):
            ev = cg.CGEventCreateMouseEvent(None, etype, pt, 0)
            if clicks > 1:
                cg.CGEventSetIntegerValueField(ev, CLICK_STATE, clicks)
            cg.CGEventPost(0, ev)
            cg.CFRelease(ev)

        post(5)                    # mouseMoved
        time.sleep(0.03)
        post(1); post(2)           # down, up  (a real single click)
        if double:
            time.sleep(0.05)
            post(1, 2); post(2, 2)  # second click of a double-click
        return {"ok": True, "result": f"clicked at {int(x)},{int(y)}"}
    except Exception as e:
        return {"ok": False, "error": f"coordinate click failed: {e}"}


def _menu(args):
    path = args.get("path") or []
    if isinstance(path, str):
        path = [path]
    if not path:
        return {"ok": False, "error": "menu needs a path, e.g. [\"File\",\"New Window\"]"}
    app = _frontmost()
    # build: menu item "…" of menu "…" of menu bar item "…" of menu bar 1
    top = _q(path[0])
    if len(path) == 1:
        target = f'menu bar item "{top}" of menu bar 1'
    else:
        chain = f'menu bar item "{top}" of menu bar 1'
        # click through submenu items
        target = f'menu item "{_q(path[-1])}" of menu "{top}" of ' + chain
    script = f'tell application "System Events" to tell process "{_q(app)}" to click {target}'
    ok, out = _osa(script)
    return ({"ok": True, "result": "clicked menu " + " > ".join(path)} if ok
            else {"ok": False, "error": out})


def _focus(args):
    name = str(args.get("app", "")).strip()
    if not name:
        return {"ok": False, "error": "focus needs an app name"}
    ok, out = _osa(f'tell application "{_q(name)}" to activate')
    return ({"ok": True, "result": f"focused {name}"} if ok else {"ok": False, "error": out})


def _apps(args):
    ok, out = _osa('tell application "System Events" to get name of every process whose background only is false')
    if not ok:
        return {"ok": False, "error": out}
    return {"ok": True, "result": [a.strip() for a in out.split(",")]}


def _type(args):
    text = str(args.get("text", ""))
    ok, out = _osa(f'tell application "System Events" to keystroke "{_q(text)}"')
    return ({"ok": True, "result": f"typed {len(text)} chars"} if ok else {"ok": False, "error": out})


_MODS = {"cmd": "command down", "command": "command down", "ctrl": "control down",
         "control": "control down", "alt": "option down", "option": "option down",
         "shift": "shift down", "fn": "function down"}


def _key(args):
    combo = str(args.get("keys", "")).strip().lower()
    if not combo:
        return {"ok": False, "error": "key needs e.g. 'cmd+s'"}
    parts = [p.strip() for p in combo.split("+")]
    mods = [_MODS[p] for p in parts[:-1] if p in _MODS]
    key = parts[-1]
    using = (" using {" + ", ".join(mods) + "}") if mods else ""
    ok, out = _osa(f'tell application "System Events" to keystroke "{_q(key)}"{using}')
    return ({"ok": True, "result": f"pressed {combo}"} if ok else {"ok": False, "error": out})


def _screenshot(args):
    os.makedirs(os.path.join(_HERE, "memory"), exist_ok=True)
    path = os.path.join(_HERE, "memory", "screen.png")
    try:
        subprocess.run(["screencapture", "-x", path], capture_output=True, timeout=15)
        if os.path.exists(path):
            return {"ok": True, "result": {"path": path, "bytes": os.path.getsize(path)}}
        return {"ok": False, "error": "no screenshot (grant Screen Recording permission)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_ACTIONS = {
    "see": _see, "look": _see, "describe": _see,
    "click": _click, "menu": _menu, "focus": _focus, "apps": _apps,
    "type": _type, "key": _key, "screenshot": _screenshot,
}


def run(args):
    action = str(args.get("action", "see")).lower()
    fn = _ACTIONS.get(action)
    if not fn:
        return {"ok": False, "error": f"unknown action '{action}'. Try: {', '.join(sorted(set(_ACTIONS)))}"}
    try:
        return fn(args)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"'{action}' timed out"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
