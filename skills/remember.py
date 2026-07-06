# name: remember
# description: Save or recall structured notes in long-term memory. args {"action":"save","key":"...","value":...} stores any JSON-serializable value (not just strings). {"action":"update","key":"...","value":...} appends to lists, merges dicts, or overwrites scalars. {"action":"recall","key":"..."} reads one. {"action":"delete","key":"..."} removes one. {"action":"list"} shows all keys. {"action":"search","query":"..."} finds keys containing a substring.
import json
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE = os.path.join(_HERE, "memory", "notes.json")


def _load():
    try:
        with open(_STORE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise ValueError(f"memory/notes.json is corrupted: {e}") from e


def _save(data):
    os.makedirs(os.path.dirname(_STORE), exist_ok=True)
    with open(_STORE, "w") as f:
        json.dump(data, f, indent=2)


def _get_key(args, name="key"):
    raw = args.get(name)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ""
    return str(raw).strip()


def run(args):
    action = str(args.get("action", "")).lower()
    if not action:
        return {"ok": False, "error": "action is required (save, update, recall, delete, list, search)"}

    notes = _load()

    if action == "save":
        key = _get_key(args, "key")
        if not key:
            return {"ok": False, "error": "save needs a key"}
        value = args.get("value")
        try:
            json.dumps(value)
        except TypeError:
            return {"ok": False, "error": "value is not JSON-serializable"}
        notes[key] = value
        _save(notes)
        return {"ok": True, "result": f"remembered '{key}'"}

    if action == "update":
        key = _get_key(args, "key")
        if not key:
            return {"ok": False, "error": "update needs a key"}
        value = args.get("value")
        try:
            json.dumps(value)
        except TypeError:
            return {"ok": False, "error": "value is not JSON-serializable"}
        existing = notes.get(key)
        if isinstance(existing, list) and isinstance(value, list):
            notes[key] = existing + value
        elif isinstance(existing, dict) and isinstance(value, dict):
            notes[key] = {**existing, **value}
        else:
            notes[key] = value
        _save(notes)
        return {"ok": True, "result": f"updated '{key}'"}

    if action == "recall":
        key = _get_key(args, "key")
        if not key:
            return {"ok": False, "error": "recall needs a key"}
        if key in notes:
            return {"ok": True, "result": notes[key]}
        return {"ok": False, "error": f"nothing remembered for '{key}'"}

    if action == "delete":
        key = _get_key(args, "key")
        if not key:
            return {"ok": False, "error": "delete needs a key"}
        if key in notes:
            del notes[key]
            _save(notes)
            return {"ok": True, "result": f"forgot '{key}'"}
        return {"ok": False, "error": f"nothing to delete for '{key}'"}

    if action == "list":
        return {"ok": True, "result": sorted(notes.keys())}

    if action == "search":
        query = _get_key(args, "query")
        if not query:
            return {"ok": False, "error": "search needs a query string"}
        matches = sorted(k for k in notes if query in k.lower())
        return {"ok": True, "result": matches}

    return {"ok": False, "error": "action must be save, update, recall, delete, list, or search"}
