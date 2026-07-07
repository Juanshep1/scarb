# name: computer
# description: Full control of this Mac's screen & mouse. {"action":"see"} FIRST to get the real on-screen buttons/menus/fields/links by name + coordinates (don't guess); {"action":"read"} reads the visible text of the front window (a web page/doc). Click: {"action":"click","target":"Save"} (real click at the element's center — works on web videos/links; "double":1 to double-click) or {"action":"click","x":120,"y":340}. Also {"action":"rightclick","x":..,"y":..}, {"action":"move","x":..,"y":..}, {"action":"drag","from":[x,y],"to":[x,y]}, {"action":"scroll","direction":"down","amount":6}, {"action":"menu","path":["File","New Window"]}, {"action":"focus","app":"Safari"}, {"action":"apps"}, {"action":"window","do":"minimize|close|fullscreen|list"}, {"action":"type","text":"hi"} — to type AND submit (terminal command, search, message) use {"action":"type","text":"ls -la","enter":true}. To press a key: {"action":"key","keys":"enter"} (or "return"/"tab"/"escape"/"cmd+s"/arrows) — this actually presses the key; {"action":"enter"} is a shortcut for Return. {"action":"clipboard"} (read), {"action":"copy","text":".."} (write), {"action":"screenshot"}. Needs macOS Accessibility permission.
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


# Special keys must be sent as key CODES — `keystroke "return"` types the WORD
# "return", it does NOT press the Return/Enter key. This map fixes that.
_KEY_CODES = {
    "return": 36, "enter": 36, "tab": 48, "space": 49, "spacebar": 49,
    "delete": 51, "backspace": 51, "forwarddelete": 117, "escape": 53, "esc": 53,
    "up": 126, "down": 125, "left": 123, "right": 124,
    "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98,
    "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}

_MODS = {"cmd": "command down", "command": "command down", "ctrl": "control down",
         "control": "control down", "alt": "option down", "option": "option down",
         "shift": "shift down", "fn": "function down"}


def _press(combo):
    """Press a key combo. Uses `key code` for named keys (Return/Tab/arrows/…)
    so Enter actually SUBMITS instead of typing the word."""
    combo = str(combo).strip().lower()
    if not combo:
        return False, "no key"
    parts = [p.strip() for p in combo.split("+")]
    mods = [_MODS[p] for p in parts[:-1] if p in _MODS]
    key = parts[-1]
    using = (" using {" + ", ".join(mods) + "}") if mods else ""
    if key in _KEY_CODES:
        return _osa(f'tell application "System Events" to key code {_KEY_CODES[key]}{using}')
    return _osa(f'tell application "System Events" to keystroke "{_q(key)}"{using}')


def _type(args):
    text = str(args.get("text", ""))
    ok, out = _osa(f'tell application "System Events" to keystroke "{_q(text)}"')
    if not ok:
        return {"ok": False, "error": out}
    # {"action":"type","text":"...","enter":true} types THEN presses Return —
    # so it actually submits in a terminal, search box, chat, etc.
    if args.get("enter") or args.get("submit") or args.get("press_enter"):
        import time
        time.sleep(0.05)
        eok, eout = _press("return")
        if not eok:
            return {"ok": False, "error": "typed, but Enter failed: " + eout}
        return {"ok": True, "result": f"typed {len(text)} chars and pressed Enter"}
    return {"ok": True, "result": f"typed {len(text)} chars"}


def _key(args):
    combo = args.get("keys") or args.get("key") or ""
    if not combo:
        return {"ok": False, "error": "key needs e.g. 'enter', 'cmd+s', 'tab', 'escape'"}
    ok, out = _press(combo)
    return ({"ok": True, "result": f"pressed {combo}"} if ok else {"ok": False, "error": out})


def _enter(args):
    ok, out = _press("return")
    return ({"ok": True, "result": "pressed Enter"} if ok else {"ok": False, "error": out})


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


# ---- more mouse: move, scroll, drag, right-click ---------------------------

def _cg():
    return ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


def _post_mouse(etype, x, y, button=0):
    cg = _cg()
    cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, _CGPoint, ctypes.c_uint32]
    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    cg.CFRelease.argtypes = [ctypes.c_void_p]
    ev = cg.CGEventCreateMouseEvent(None, etype, _CGPoint(float(x), float(y)), button)
    cg.CGEventPost(0, ev)
    cg.CFRelease(ev)


def _move(args):
    _post_mouse(5, float(args.get("x", 0)), float(args.get("y", 0)))
    return {"ok": True, "result": f"moved to {args.get('x')},{args.get('y')}"}


def _rightclick(args):
    x, y = float(args.get("x", 0)), float(args.get("y", 0))
    _post_mouse(5, x, y)
    _post_mouse(3, x, y, 1)   # rightMouseDown
    _post_mouse(4, x, y, 1)   # rightMouseUp
    return {"ok": True, "result": f"right-clicked {int(x)},{int(y)}"}


def _drag(args):
    frm = args.get("from") or [args.get("x1"), args.get("y1")]
    to = args.get("to") or [args.get("x2"), args.get("y2")]
    import time
    x1, y1 = float(frm[0]), float(frm[1])
    x2, y2 = float(to[0]), float(to[1])
    _post_mouse(5, x1, y1); _post_mouse(1, x1, y1)      # move, down
    steps = 12
    for i in range(1, steps + 1):
        _post_mouse(6, x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)  # leftMouseDragged
        time.sleep(0.01)
    _post_mouse(2, x2, y2)                               # up
    return {"ok": True, "result": f"dragged {int(x1)},{int(y1)} -> {int(x2)},{int(y2)}"}


def _scroll(args):
    cg = _cg()
    cg.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p
    cg.CGEventCreateScrollWheelEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                                 ctypes.c_int32, ctypes.c_int32]
    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    cg.CFRelease.argtypes = [ctypes.c_void_p]
    dy = int(args.get("dy", 0))
    dx = int(args.get("dx", 0))
    direction = str(args.get("direction", "")).lower()
    amount = int(args.get("amount", 5))
    if direction == "down":
        dy = -amount
    elif direction == "up":
        dy = amount
    elif direction == "left":
        dx = -amount
    elif direction == "right":
        dx = amount
    ev = cg.CGEventCreateScrollWheelEvent(None, 0, 2, dy, dx)  # kCGScrollEventUnitLine=0? use pixel=0
    cg.CGEventPost(0, ev)
    cg.CFRelease(ev)
    return {"ok": True, "result": f"scrolled dx={dx} dy={dy}"}


# ---- clipboard, reading text, windows --------------------------------------

def _clipboard(args):
    try:
        out = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5).stdout
        return {"ok": True, "result": out[:8000]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _copy(args):
    text = str(args.get("text", ""))
    try:
        subprocess.run(["pbcopy"], input=text, text=True, timeout=5)
        return {"ok": True, "result": f"copied {len(text)} chars to the clipboard"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _read(args):
    """Read the visible text of the frontmost window — useful for reading a web
    page, doc, or dialog before acting."""
    app = _frontmost()
    script = f'''
    set out to ""
    tell application "System Events" to tell process "{_q(app)}"
      if (count of windows) > 0 then
        repeat with el in (entire contents of window 1)
          try
            set r to role description of el
            if r is in {{"static text", "text area", "text field", "link", "heading"}} then
              set v to ""
              try
                set v to (value of el as string)
              end try
              if v is "" then
                try
                  set v to (name of el as string)
                end try
              end if
              if v is not "" and v is not "missing value" then set out to out & v & linefeed
            end if
          end try
        end repeat
      end if
    end tell
    return out
    '''
    ok, out = _osa(script, timeout=45)
    if not ok:
        return {"ok": False, "error": out}
    return {"ok": True, "result": out[:9000]}


def _window(args):
    do = str(args.get("do", "list")).lower()
    app = _frontmost()
    if do == "list":
        ok, out = _osa(f'tell application "System Events" to tell process "{_q(app)}" to get name of windows')
        return {"ok": ok, "result": out}
    verb = {"minimize": 'set value of attribute "AXMinimized" of window 1 to true',
            "close": "click button 1 of window 1",
            "fullscreen": 'keystroke "f" using {control down, command down}'}.get(do)
    if not verb:
        return {"ok": False, "error": "window do: list, minimize, close, or fullscreen"}
    ok, out = _osa(f'tell application "System Events" to tell process "{_q(app)}" to {verb}')
    return {"ok": ok, "result": out or f"{do} done"}


_ACTIONS = {
    "see": _see, "look": _see, "describe": _see, "read": _read,
    "click": _click, "rightclick": _rightclick, "menu": _menu,
    "move": _move, "drag": _drag, "scroll": _scroll,
    "focus": _focus, "apps": _apps, "window": _window,
    "type": _type, "key": _key, "press": _key, "enter": _enter, "return": _enter,
    "clipboard": _clipboard, "copy": _copy, "screenshot": _screenshot,
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
