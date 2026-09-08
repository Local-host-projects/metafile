"""
Calendar artifact. {"events": [{"id","title","start","end","all_day","notes","at"}]}
start/end are ISO 8601 strings. No recurrence rules in this pass --
each occurrence is its own event.
"""
import time
import uuid


def get_state(content: dict) -> dict:
    return {"events": sorted(content.get("events", []), key=lambda e: e.get("start", ""))}


def apply_patch(content: dict, op: str, path, value) -> dict:
    content.setdefault("events", [])
    if op == "append":
        v = value if isinstance(value, dict) else {"title": value}
        event = {
            "id": uuid.uuid4().hex[:10],
            "title": v.get("title", "Untitled event"),
            "start": v.get("start"),
            "end": v.get("end", v.get("start")),
            "all_day": bool(v.get("all_day", False)),
            "notes": v.get("notes", ""),
            "at": time.time(),
        }
        if not event["start"]:
            raise ValueError("Calendar events need a 'start' (ISO 8601)")
        content["events"].append(event)
    elif op == "set":
        for e in content["events"]:
            if e["id"] == path:
                if isinstance(value, dict):
                    e.update(value)
                e["at"] = time.time()
                break
        else:
            raise ValueError(f"No event with id {path}")
    elif op == "delete":
        content["events"] = [e for e in content["events"] if e["id"] != path]
    elif op == "bulk_set":
        content["events"] = value.get("events", [])
    else:
        raise ValueError(f"Unsupported op for calendar artifact: {op}")
    return content


def events_in_range(content: dict, start: str, end: str):
    return [e for e in content.get("events", []) if e.get("start") and start <= e["start"] <= end]
