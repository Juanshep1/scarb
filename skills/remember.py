# name: remember
# description: Save or recall short notes in long-term memory. args {"action": "save", "key": "wifi", "value": "..."} to store, {"action": "recall", "key": "wifi"} to read one, or {"action": "list"} to see all keys.
import json
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE = os.path.join(_HERE, "memory", "notes.json")


def _load():
    try:
        with open(_STORE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data):
    os.makedirs(os.path.dirname(_STORE), exist_ok=True)
    with open(_STORE, "w") as f:
        json.dump(data, f, indent=2)


def run(args):
    action = str(args.get("action", "recall")).lower()
    notes = _load()
    if action == "save":
        key = str(args.get("key", "")).strip()
        if not key:
            return {"ok": False, "error": "save needs a key"}
        notes[key] = args.get("value", "")
        _save(notes)
        return {"ok": True, "result": f"remembered '{key}'"}
    if action == "recall":
        key = str(args.get("key", "")).strip()
        if key in notes:
            return {"ok": True, "result": notes[key]}
        return {"ok": False, "error": f"nothing remembered for '{key}'"}
    if action == "list":
        return {"ok": True, "result": sorted(notes.keys())}
    return {"ok": False, "error": "action must be save, recall, or list"}
